"""Deterministic Text-to-SQL templates.

The MVP does not rely on a language model to write SQL.  A question is mapped to
a reviewed template and the template is rendered with safe date/string literals.
The generated SQL still passes through the validator and read-only executor.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from app.core.config import get_settings


def _q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _d(value: date) -> str:
    return f"DATE '{value.isoformat()}'"


MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _month_bounds(month: int, year: int) -> tuple[date, date]:
    first = date(year, month, 1)
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    return first, last


def resolve_dates(question: str, start_date: date | None = None, end_date: date | None = None) -> tuple[date, date]:
    settings = get_settings()
    as_of = settings.data_end_date
    if end_date is None:
        end_date = as_of
    if start_date is not None:
        return start_date, end_date
    q = question.lower()

    # An explicit ISO date or "September 15" means one day, not the whole month.
    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", q)
    if iso_match:
        try:
            day = date.fromisoformat(iso_match.group(1))
            return day, min(day, as_of)
        except ValueError:
            pass
    month_names = "|".join(MONTHS)
    day_match = re.search(rf"\b({month_names})\s+(\d{{1,2}})(?:,?\s+(\d{{4}}))?\b", q)
    if day_match:
        month = MONTHS[day_match.group(1)]
        year = int(day_match.group(3)) if day_match.group(3) else as_of.year
        try:
            day = date(year, month, int(day_match.group(2)))
            return day, min(day, as_of)
        except ValueError:
            pass

    since_match = re.search(rf"\bsince\s+({month_names})(?:\s+(\d{{4}}))?\b", q)
    if since_match:
        month = MONTHS[since_match.group(1)]
        year = int(since_match.group(2)) if since_match.group(2) else as_of.year
        first, _ = _month_bounds(month, year)
        return first, min(as_of, end_date)

    for name, month in MONTHS.items():
        if re.search(rf"\b{name}\b", q):
            year_match = re.search(rf"\b{name}\s+(\d{{4}})\b", q)
            year = int(year_match.group(1)) if year_match else as_of.year
            first, last = _month_bounds(month, year)
            return first, min(last, as_of)
    if "last 7 days" in q or "past week" in q or "last week" in q:
        return end_date - timedelta(days=6), end_date
    if "last 14 days" in q or "two weeks" in q:
        return end_date - timedelta(days=13), end_date
    if "last 90 days" in q or "past 90" in q or "three months" in q:
        return end_date - timedelta(days=89), end_date
    if "last 60 days" in q:
        return end_date - timedelta(days=59), end_date
    if "last month" in q or "past month" in q or "last 30 days" in q or "30 days" in q:
        return end_date - timedelta(days=29), end_date
    if "since august" in q or "since aug" in q:
        return date(2026, 8, 1), end_date
    if "since september" in q or "since sep" in q:
        return date(2026, 9, 1), end_date
    if "since july" in q:
        return date(2026, 7, 1), end_date
    if "this year" in q or "all time" in q or "overall" in q:
        return settings.data_start_date, end_date
    return end_date - timedelta(days=29), end_date


def _range(start: date, end: date) -> str:
    return f"{_d(start)} AND {_d(end)}"


def _template(question: str, start: date, end: date) -> dict | None:
    q = question.lower()

    if re.search(r"\b(experiment|a/b test|ab test|variant)\b", q):
        return {
            "template": "experiment_results",
            "sql": (
                "SELECT r.experiment_id, r.metric_key, r.variant, r.successes, r.sample_size, "
                "r.rate, r.absolute_lift, r.relative_lift, r.ci_low, r.ci_high, r.p_value, "
                "r.significant FROM analytics.experiment_results r "
                "JOIN analytics.experiments e ON r.experiment_id = e.experiment_id "
                "ORDER BY r.metric_key, r.variant"
            ),
            "title": "Experiment results",
            "chart": {"type": "bar", "x": "variant", "y": "rate", "series": "metric_key"},
        }
    if re.search(r"\b(anomal|unusual|spike|drop|incident)\b", q):
        return {
            "template": "anomalies",
            "sql": (
                "SELECT metric_key, period_start, granularity, observed_value, baseline_value, "
                "deviation, robust_z, severity, sample_size FROM analytics.anomaly_events "
                f"WHERE period_start BETWEEN {_range(start, end)} "
                "ORDER BY period_start DESC, ABS(robust_z) DESC"
            ),
            "title": "Detected anomalies",
            "chart": {"type": "table"},
        }
    if re.search(r"\b(retention|retain|cohort)\b", q):
        if "paid social" in q or "paid-social" in q or "paid_social" in q:
            return {
                "template": "paid_social_retention",
                "sql": (
                    "SELECT cohort_date, period_days, cohort_size, retained_users, retention_rate "
                    "FROM analytics.retention_by_dimension "
                    "WHERE dimension_type = 'channel' AND dimension_value = 'paid_social' "
                    "AND period_days IN (1, 7, 14, 30) "
                    f"AND cohort_date BETWEEN {_range(start, end)} "
                    "ORDER BY cohort_date, period_days"
                ),
                "title": "Paid-social retention",
                "chart": {"type": "line", "x": "cohort_date", "y": "retention_rate", "series": "period_days"},
            }
        return {
            "template": "retention_by_channel",
            "sql": (
                "SELECT dimension_value AS channel, period_days, "
                "SUM(cohort_size) AS cohort_users, SUM(retained_users) AS retained_users, "
                "ROUND(SUM(retained_users) * 1.0 / NULLIF(SUM(cohort_size), 0), 4) AS retention_rate "
                "FROM analytics.retention_by_dimension "
                "WHERE dimension_type = 'channel' AND period_days IN (1, 7, 14, 30) "
                f"AND cohort_date BETWEEN {_range(start, end)} "
                "GROUP BY 1,2 ORDER BY period_days, retention_rate DESC"
            ),
            "title": "Retention by acquisition channel",
            "chart": {"type": "bar", "x": "channel", "y": "retention_rate", "series": "period_days"},
        }
    if re.search(r"\b(feature|adoption|usage)\b", q):
        return {
            "template": "feature_adoption",
            "sql": (
                "SELECT f.feature_name, SUM(a.users) AS users, "
                "ROUND(AVG(a.adoption_rate), 4) AS avg_adoption_rate "
                "FROM analytics.feature_adoption_daily a "
                "JOIN analytics.features f ON a.feature_key = f.feature_key "
                f"WHERE a.metric_date BETWEEN {_range(start, end)} "
                "GROUP BY 1 ORDER BY users DESC"
            ),
            "title": "Feature adoption",
            "chart": {"type": "bar", "x": "feature_name", "y": "users"},
        }
    if re.search(r"\b(checkout|android|payment|purchase completion)\b", q) and re.search(
        r"\b(device|android|ios|web)\b", q
    ):
        return {
            "template": "checkout_conversion_by_device",
            "sql": (
                "SELECT e.device, COUNT(*) AS checkouts, "
                "SUM(CASE WHEN p.user_id IS NOT NULL THEN 1 ELSE 0 END) AS conversions, "
                "ROUND(SUM(CASE WHEN p.user_id IS NOT NULL THEN 1 ELSE 0 END) * 1.0 "
                "/ NULLIF(COUNT(*), 0), 4) AS conversion_rate "
                "FROM analytics.events e "
                "LEFT JOIN analytics.events p ON e.user_id = p.user_id "
                "AND p.event_name = 'purchase_completed' "
                "AND p.event_timestamp >= e.event_timestamp "
                "AND p.event_timestamp <= e.event_timestamp + INTERVAL 7 DAY "
                "WHERE e.event_name = 'checkout_started' "
                f"AND e.event_date BETWEEN {_range(start, end)} "
                "GROUP BY 1 ORDER BY conversion_rate"
            ),
            "title": "Checkout conversion by device",
            "chart": {"type": "bar", "x": "device", "y": "conversion_rate"},
        }
    if re.search(r"\b(cancellations?|cancel|churn|subscription)\b", q):
        return {
            "template": "cancellations_by_plan",
            "sql": (
                "SELECT s.plan, COUNT(*) AS cancellations, ROUND(SUM(s.mrr), 2) AS lost_mrr "
                "FROM analytics.subscriptions s "
                f"WHERE s.cancelled_date BETWEEN {_range(start, end)} "
                "GROUP BY 1 ORDER BY cancellations DESC"
            ),
            "title": "Cancellations by plan",
            "chart": {"type": "bar", "x": "plan", "y": "cancellations"},
        }
    if re.search(r"\b(mrr|revenue|arr)\b", q):
        return {
            "template": "mrr_trend",
            "sql": (
                "SELECT metric_date, mrr, cancellations FROM analytics.daily_metrics "
                f"WHERE metric_date BETWEEN {_range(start, end)} ORDER BY metric_date"
            ),
            "title": "MRR trend",
            "chart": {"type": "line", "x": "metric_date", "y": "mrr"},
        }
    if re.search(r"\b(dau|active users|engagement|stickiness|dau/mau)\b", q):
        return {
            "template": "engagement_trend",
            "sql": (
                "SELECT metric_date, dau, wau, mau, dau_mau_ratio, sessions, events "
                "FROM analytics.daily_metrics "
                f"WHERE metric_date BETWEEN {_range(start, end)} ORDER BY metric_date"
            ),
            "title": "Engagement trend",
            "chart": {"type": "line", "x": "metric_date", "y": "dau"},
        }
    if re.search(r"\b(funnel|conversion)\b", q):
        return {
            "template": "funnel_counts",
            "sql": (
                "SELECT SUM(registered_users) AS registered_users, "
                "SUM(activated_users) AS activated_users, SUM(checkouts) AS checkouts, "
                "SUM(checkout_conversions) AS checkout_conversions, SUM(purchases) AS purchases, "
                "ROUND(SUM(checkout_conversions) * 1.0 / NULLIF(SUM(checkouts), 0), 4) "
                "AS checkout_conversion_rate "
                "FROM analytics.daily_metrics "
                f"WHERE metric_date BETWEEN {_range(start, end)}"
            ),
            "title": "Funnel counts",
            "chart": {"type": "funnel", "x": "stage", "y": "users"},
        }
    if re.search(r"\b(registrations?|signups?|new users)\b", q):
        return {
            "template": "registrations_by_channel",
            "sql": (
                "SELECT acquisition_channel AS channel, COUNT(*) AS users "
                "FROM analytics.users "
                f"WHERE registration_date BETWEEN {_range(start, end)} "
                "GROUP BY 1 ORDER BY users DESC"
            ),
            "title": "Registrations by channel",
            "chart": {"type": "bar", "x": "channel", "y": "users"},
        }
    if re.search(r"\b(session|duration|frequency)\b", q):
        return {
            "template": "sessions_by_device",
            "sql": (
                "SELECT u.device_type AS device, COUNT(*) AS sessions, "
                "ROUND(AVG(s.duration_seconds), 1) AS avg_duration_seconds "
                "FROM analytics.sessions s JOIN analytics.users u ON s.user_id = u.user_id "
                f"WHERE CAST(s.session_start AS DATE) BETWEEN {_range(start, end)} "
                "GROUP BY 1 ORDER BY sessions DESC"
            ),
            "title": "Sessions by device",
            "chart": {"type": "bar", "x": "device", "y": "sessions"},
        }
    return None


def generate_sql(question: str, start_date: date | None = None, end_date: date | None = None) -> dict | None:
    start, end = resolve_dates(question, start_date, end_date)
    result = _template(question, start, end)
    if result:
        result.update(
            {
                "question": question,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "provider": "deterministic-template",
                "model": "template-v1",
                "explanation": (
                    "This SQL was produced by a reviewed deterministic template, not by a "
                    "language model. It is validated and executed read-only."
                ),
            }
        )
        return result

    # Generic metric/dimension fallback, still a reviewed template family.
    metric_patterns = [
        ("purchase_conversion_rate", r"purchase conversion|conversion rate|paying conversion"),
        ("activation_rate", r"activation rate|activation"),
        ("checkout_conversion_rate", r"checkout conversion"),
        ("dau", r"dau|active users"),
        ("registered_users", r"registrations?|signup|new users"),
        ("mrr", r"mrr|revenue"),
        ("sessions", r"sessions"),
        ("cancellations", r"cancellations|churn"),
    ]
    dimension_patterns = [
        ("channel", r"channel"),
        ("device", r"device|android|ios|web"),
        ("country", r"country"),
        ("plan", r"plan|tier"),
        ("segment", r"segment|cohort"),
    ]
    metric = next((key for key, pattern in metric_patterns if re.search(pattern, question.lower())), None)
    dimension = next(
        (key for key, pattern in dimension_patterns if re.search(pattern, question.lower())), None
    )
    if metric and dimension:
        sql = _metric_dimension_sql(metric, dimension, start, end)
        if sql:
            return {
                "question": question,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "template": f"{metric}_by_{dimension}",
                "sql": sql,
                "title": f"{metric.replace('_', ' ').title()} by {dimension}",
                "chart": {"type": "bar", "x": "dimension_value", "y": "value"},
                "provider": "deterministic-template",
                "model": "template-v1",
                "explanation": (
                    "This SQL was produced by a reviewed deterministic metric/dimension template. "
                    "It is validated and executed read-only."
                ),
            }
    return None


def _metric_dimension_sql(metric: str, dimension: str, start: date, end: date) -> str | None:
    dim_col = {
        "channel": "acquisition_channel",
        "device": "device_type",
        "country": "country",
        "plan": "subscription_type",
        "segment": "segment",
    }[dimension]
    if metric in {"activation_rate", "purchase_conversion_rate", "mrr"}:
        outcome = "is_activated" if metric == "activation_rate" else "is_purchased"
        if metric == "mrr":
            value = "ROUND(SUM(um.mrr), 2)"
        else:
            value = (
                f"ROUND(AVG(CASE WHEN um.{outcome} THEN 1.0 ELSE 0.0 END), 4)"
            )
        if dimension == "segment":
            return (
                f"SELECT COALESCE(s.segment, 'unknown') AS dimension_value, {value} AS value "
                "FROM analytics.user_metrics um "
                "LEFT JOIN analytics.user_segments s ON um.user_id = s.user_id "
                f"WHERE um.registration_date BETWEEN {_range(start, end)} "
                "GROUP BY 1 ORDER BY value DESC"
            )
        return (
            f"SELECT COALESCE(u.{dim_col}, 'unknown') AS dimension_value, {value} AS value "
            "FROM analytics.user_metrics um JOIN analytics.users u ON um.user_id = u.user_id "
            f"WHERE um.registration_date BETWEEN {_range(start, end)} "
            "GROUP BY 1 ORDER BY value DESC"
        )
    if metric == "dau":
        return (
            f"SELECT COALESCE(u.{dim_col}, 'unknown') AS dimension_value, "
            "COUNT(DISTINCT e.user_id) AS value FROM analytics.events e "
            "JOIN analytics.users u ON e.user_id = u.user_id "
            f"WHERE e.event_date BETWEEN {_range(start, end)} "
            "GROUP BY 1 ORDER BY value DESC"
        )
    if metric == "registered_users":
        if dimension == "segment":
            return (
                "SELECT COALESCE(s.segment, 'unknown') AS dimension_value, COUNT(*) AS value "
                "FROM analytics.users u LEFT JOIN analytics.user_segments s ON u.user_id = s.user_id "
                f"WHERE u.registration_date BETWEEN {_range(start, end)} "
                "GROUP BY 1 ORDER BY value DESC"
            )
        return (
            f"SELECT COALESCE({dim_col}, 'unknown') AS dimension_value, COUNT(*) AS value "
            f"FROM analytics.users WHERE registration_date BETWEEN {_range(start, end)} "
            "GROUP BY 1 ORDER BY value DESC"
        )
    if metric == "sessions":
        return (
            f"SELECT COALESCE(u.{dim_col}, 'unknown') AS dimension_value, COUNT(*) AS value "
            "FROM analytics.sessions s JOIN analytics.users u ON s.user_id = u.user_id "
            f"WHERE CAST(s.session_start AS DATE) BETWEEN {_range(start, end)} "
            "GROUP BY 1 ORDER BY value DESC"
        )
    if metric == "cancellations":
        return (
            f"SELECT COALESCE(u.{dim_col}, 'unknown') AS dimension_value, COUNT(*) AS value "
            "FROM analytics.subscriptions s JOIN analytics.users u ON s.user_id = u.user_id "
            f"WHERE s.cancelled_date BETWEEN {_range(start, end)} "
            "GROUP BY 1 ORDER BY value DESC"
        )
    if metric == "checkout_conversion_rate":
        return None
    return None
