"""Product metric read models used by the UI and the Copilot tools."""

from __future__ import annotations

import contextlib
from datetime import date

import pandas as pd

from app.analytics.retention import get_retention
from app.core.config import get_settings
from app.db.duck import query_df, query_rows


def _clean_records(rows: list[dict]) -> list[dict]:
    """Replace pandas/NumPy missing sentinels with JSON-safe ``None`` values."""
    for row in rows:
        for key, value in row.items():
            if value is None:
                continue
            try:
                missing = pd.isna(value)
            except (TypeError, ValueError):
                missing = False
            if isinstance(missing, bool) and missing:
                row[key] = None
    return rows


DIMENSION_COLUMNS = {
    "channel": "acquisition_channel",
    "device": "device_type",
    "country": "country",
    "plan": "subscription_type",
    "segment": "segment",
}

METRIC_COLUMNS = {
    "dau": "dau",
    "wau": "wau",
    "mau": "mau",
    "registrations": "registered_users",
    "registered_users": "registered_users",
    "activations": "activated_users",
    "activated_users": "activated_users",
    "purchases": "purchases",
    "purchasing_users": "purchasing_users",
    "checkouts": "checkouts",
    "sessions": "sessions",
    "events": "events",
    "mrr": "mrr",
    "cancellations": "cancellations",
    "checkout_conversion_rate": "checkout_conversion_rate",
    "purchase_conversion_rate": "purchase_conversion_rate",
    "activation_rate": "activation_rate",
    "dau_mau_ratio": "dau_mau_ratio",
    "avg_session_duration_seconds": "avg_session_duration_seconds",
}


def _date_range(start: date, end: date) -> tuple[str, str]:
    return start.isoformat(), end.isoformat()


def _resample(df: pd.DataFrame, granularity: str) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["metric_date"] = pd.to_datetime(df["metric_date"])
    if granularity == "week":
        df["period"] = df["metric_date"] - pd.to_timedelta(df["metric_date"].dt.weekday, unit="D")
    elif granularity == "month":
        df["period"] = df["metric_date"].dt.to_period("M").dt.to_timestamp()
    else:
        df["period"] = df["metric_date"]
    numeric = [c for c in df.columns if c not in {"metric_date", "period"}]
    sums = {
        c: "sum"
        for c in numeric
        if c
        in {
            "registered_users",
            "activated_users",
            "purchasing_users",
            "cohort_activated_users",
            "cohort_purchasing_users",
            "checkouts",
            "checkout_conversions",
            "purchases",
            "sessions",
            "events",
            "cancellations",
        }
    }
    means = {
        c: "mean"
        for c in numeric
        if c in {"avg_session_duration_seconds", "dau", "wau", "mau", "dau_mau_ratio", "mrr"}
    }
    # Generic metric-series columns (e.g. a single `value` or a rate) are
    # averaged over the period; counts above are summed.
    for column in numeric:
        if column not in sums and column not in means:
            means[column] = "mean"
    aggregations = {**sums, **means}
    if aggregations:
        grouped = df.groupby("period").agg(aggregations).reset_index()
    else:
        grouped = df.groupby("period").size().reset_index(name="rows")
    grouped["metric_date"] = grouped["period"].dt.date.astype(str)
    # Recompute ratios from summed numerators/denominators where possible.
    if {"checkout_conversions", "checkouts"}.issubset(grouped.columns):
        grouped["checkout_conversion_rate"] = (
            grouped["checkout_conversions"] / grouped["checkouts"].replace(0, float("nan"))
        ).fillna(0).round(4)
    if {"cohort_activated_users", "registered_users"}.issubset(grouped.columns):
        grouped["activation_rate"] = (
            grouped["cohort_activated_users"] / grouped["registered_users"].replace(0, float("nan"))
        ).fillna(0).round(4)
    if {"cohort_purchasing_users", "registered_users"}.issubset(grouped.columns):
        grouped["purchase_conversion_rate"] = (
            grouped["cohort_purchasing_users"] / grouped["registered_users"].replace(0, float("nan"))
        ).fillna(0).round(4)
    return grouped.drop(columns=["period"])


def engagement_series(
    start_date: date, end_date: date, granularity: str = "day", group_by: str | None = None
) -> dict:
    start, end = _date_range(start_date, end_date)
    if group_by and group_by in DIMENSION_COLUMNS:
        col = DIMENSION_COLUMNS[group_by]
        if group_by == "segment":
            sql = """
                SELECT e.event_date AS metric_date, COALESCE(s.segment, 'unknown') AS group_value,
                       COUNT(DISTINCT e.user_id) AS dau
                FROM analytics.events e
                JOIN analytics.users u ON e.user_id = u.user_id
                LEFT JOIN analytics.user_segments s ON e.user_id = s.user_id
                WHERE e.event_date BETWEEN ? AND ?
                GROUP BY 1,2 ORDER BY 1,2
            """
        else:
            sql = f"""
                SELECT e.event_date AS metric_date, COALESCE(u.{col}, 'unknown') AS group_value,
                       COUNT(DISTINCT e.user_id) AS dau
                FROM analytics.events e
                JOIN analytics.users u ON e.user_id = u.user_id
                WHERE e.event_date BETWEEN ? AND ?
                GROUP BY 1,2 ORDER BY 1,2
            """
        df = query_df(sql, [start, end])
        if df.empty:
            return {"groups": [], "group_by": group_by, "granularity": granularity}
        df["metric_date"] = pd.to_datetime(df["metric_date"])
        if granularity == "week":
            df["period"] = (df["metric_date"] - pd.to_timedelta(df["metric_date"].dt.weekday, unit="D")).dt.date
        elif granularity == "month":
            df["period"] = df["metric_date"].dt.to_period("M").dt.to_timestamp().dt.date
        else:
            df["period"] = df["metric_date"].dt.date
        grouped = df.groupby(["period", "group_value"])["dau"].mean().reset_index()
        groups = []
        for value, group in grouped.groupby("group_value"):
            groups.append(
                {
                    "name": str(value),
                    "points": [
                        {"date": str(row.period), "dau": round(float(row.dau), 1)}
                        for row in group.sort_values("period").itertuples()
                    ],
                }
            )
        return {"groups": groups, "group_by": group_by, "granularity": granularity}

    df = query_df(
        "SELECT * FROM analytics.daily_metrics WHERE metric_date BETWEEN ? AND ? ORDER BY metric_date",
        [start, end],
    )
    df = _resample(df, granularity)
    columns = [
        "metric_date", "dau", "wau", "mau", "dau_mau_ratio", "sessions", "events",
        "avg_session_duration_seconds", "registered_users", "activated_users",
        "purchasing_users", "cohort_activated_users", "cohort_purchasing_users",
        "checkouts", "checkout_conversions", "checkout_conversion_rate",
        "purchase_conversion_rate", "activation_rate", "mrr", "cancellations",
    ]
    columns = [c for c in columns if c in df.columns]
    return {
        "series": df[columns].fillna(0).to_dict(orient="records"),
        "granularity": granularity,
        "group_by": None,
    }


def feature_adoption(
    start_date: date, end_date: date, feature: str | None = None, limit: int = 12
) -> dict:
    start, end = _date_range(start_date, end_date)
    params: list = [start, end]
    where = "metric_date BETWEEN ? AND ?"
    if feature:
        where += " AND feature_key = ?"
        params.append(feature)
    df = query_df(
        f"SELECT * FROM analytics.feature_adoption_daily WHERE {where} ORDER BY metric_date, feature_key",
        params,
    )
    if df.empty:
        return {"features": [], "series": [], "feature": feature}
    summary = (
        df.groupby(["feature_key", "feature_name"])
        .agg(users=("users", "sum"), avg_adoption_rate=("adoption_rate", "mean"), days=("metric_date", "nunique"))
        .reset_index()
        .sort_values("users", ascending=False)
        .head(limit)
    )
    features = [
        {
            "feature_key": row.feature_key,
            "feature_name": row.feature_name,
            "users": int(row.users),
            "avg_adoption_rate": round(float(row.avg_adoption_rate), 6),
            "days": int(row.days),
        }
        for row in summary.itertuples()
    ]
    series = []
    if feature:
        for row in df.sort_values("metric_date").itertuples():
            series.append(
                {
                    "date": str(row.metric_date),
                    "users": int(row.users),
                    "adoption_rate": round(float(row.adoption_rate), 6),
                }
            )
    else:
        pivot = df.pivot_table(
            index="metric_date", columns="feature_name", values="adoption_rate", aggfunc="mean"
        ).fillna(0)
        for d, row in pivot.iterrows():
            series.append({"date": str(d), **{k: round(float(v), 6) for k, v in row.items()}})
    return {"features": features, "series": series, "feature": feature}


def session_metrics(
    start_date: date, end_date: date, granularity: str = "day", group_by: str | None = None
) -> dict:
    start, end = _date_range(start_date, end_date)
    if group_by and group_by in DIMENSION_COLUMNS:
        col = DIMENSION_COLUMNS[group_by]
        if group_by == "segment":
            sql = """
                SELECT CAST(s.session_start AS DATE) AS metric_date,
                       COALESCE(seg.segment, 'unknown') AS group_value,
                       COUNT(*) AS sessions, AVG(s.duration_seconds) AS avg_duration
                FROM analytics.sessions s
                JOIN analytics.users u ON s.user_id = u.user_id
                LEFT JOIN analytics.user_segments seg ON s.user_id = seg.user_id
                WHERE CAST(s.session_start AS DATE) BETWEEN ? AND ?
                GROUP BY 1,2 ORDER BY 1,2
            """
        else:
            sql = f"""
                SELECT CAST(s.session_start AS DATE) AS metric_date,
                       COALESCE(u.{col}, 'unknown') AS group_value,
                       COUNT(*) AS sessions, AVG(s.duration_seconds) AS avg_duration
                FROM analytics.sessions s
                JOIN analytics.users u ON s.user_id = u.user_id
                WHERE CAST(s.session_start AS DATE) BETWEEN ? AND ?
                GROUP BY 1,2 ORDER BY 1,2
            """
        df = query_df(sql, [start, end])
        if df.empty:
            return {"groups": [], "group_by": group_by}
        df["metric_date"] = pd.to_datetime(df["metric_date"])
        if granularity == "week":
            df["period"] = (df["metric_date"] - pd.to_timedelta(df["metric_date"].dt.weekday, unit="D")).dt.date
        elif granularity == "month":
            df["period"] = df["metric_date"].dt.to_period("M").dt.to_timestamp().dt.date
        else:
            df["period"] = df["metric_date"].dt.date
        grouped = df.groupby(["period", "group_value"]).agg(
            sessions=("sessions", "sum"), avg_duration=("avg_duration", "mean")
        ).reset_index()
        groups = []
        for value, group in grouped.groupby("group_value"):
            groups.append(
                {
                    "name": str(value),
                    "points": [
                        {
                            "date": str(row.period),
                            "sessions": int(row.sessions),
                            "avg_duration": round(float(row.avg_duration), 1),
                        }
                        for row in group.sort_values("period").itertuples()
                    ],
                }
            )
        return {"groups": groups, "group_by": group_by}
    df = query_df(
        "SELECT metric_date, sessions, dau, avg_session_duration_seconds FROM analytics.daily_metrics "
        "WHERE metric_date BETWEEN ? AND ? ORDER BY metric_date",
        [start, end],
    )
    df = _resample(df, granularity)
    if not df.empty:
        df["sessions_per_active_user"] = (
            df["sessions"] / df["dau"].replace(0, float("nan"))
        ).fillna(0).round(3)
    return {"series": df.fillna(0).to_dict(orient="records"), "group_by": None}


def metric_series(
    metric: str, start_date: date, end_date: date, granularity: str = "day"
) -> dict:
    start, end = _date_range(start_date, end_date)
    if metric in {"retention_d1", "retention_d7", "retention_d14", "retention_d30"}:
        period = int(metric.replace("retention_d", ""))
        data = get_retention("daily", start_date, end_date)
        points = []
        for cohort in data["cohorts"]:
            value = cohort["values"].get(str(period))
            if value:
                points.append({"date": cohort["cohort_date"], "value": value["rate"], "complete": value["complete"]})
        return {"metric": metric, "points": points, "unit": "ratio"}
    col = METRIC_COLUMNS.get(metric)
    if not col:
        raise ValueError(f"Unsupported metric: {metric}")
    df = query_df(
        f"SELECT metric_date, {col} AS value FROM analytics.daily_metrics "
        "WHERE metric_date BETWEEN ? AND ? ORDER BY metric_date",
        [start, end],
    )
    df = _resample(df, granularity)
    points = [
        {"date": str(row.metric_date), "value": round(float(row.value), 6)}
        for row in df.itertuples()
    ]
    return {"metric": metric, "points": points, "unit": "ratio" if "rate" in metric else "count"}


def dimension_breakdown(
    metric: str, start_date: date, end_date: date, dimension: str = "channel", limit: int = 20
) -> dict:
    start, end = _date_range(start_date, end_date)
    if dimension not in DIMENSION_COLUMNS:
        raise ValueError(f"Unsupported dimension: {dimension}")
    col = DIMENSION_COLUMNS[dimension]
    if metric == "checkout_conversion_rate":
        if dimension == "segment":
            segment_col = "COALESCE(s.segment, 'unknown')"
            join = "LEFT JOIN analytics.user_segments s ON e.user_id = s.user_id"
        else:
            segment_col = f"COALESCE(u.{col}, 'unknown')"
            join = "JOIN analytics.users u ON e.user_id = u.user_id"
        sql = f"""
            SELECT {segment_col} AS dimension_value,
                   COUNT(*) AS checkouts,
                   SUM(CASE WHEN p.user_id IS NOT NULL THEN 1 ELSE 0 END) AS conversions,
                   ROUND(SUM(CASE WHEN p.user_id IS NOT NULL THEN 1 ELSE 0 END) * 1.0
                         / NULLIF(COUNT(*), 0), 6) AS value
            FROM analytics.events e
            {join}
            LEFT JOIN analytics.events p ON e.user_id = p.user_id
              AND p.event_name = 'purchase_completed'
              AND p.event_timestamp >= e.event_timestamp
              AND p.event_timestamp <= e.event_timestamp + INTERVAL 7 DAY
            WHERE e.event_name = 'checkout_started'
              AND e.event_date BETWEEN ? AND ?
            GROUP BY 1 ORDER BY value DESC LIMIT ?
        """
        df = query_df(sql, [start, end, limit])
        return {
            "metric": metric,
            "dimension": dimension,
            "rows": [
                {
                    "dimension_value": str(r.dimension_value),
                    "checkouts": int(r.checkouts),
                    "conversions": int(r.conversions),
                    "value": round(float(r.value), 6),
                }
                for r in df.itertuples()
            ],
        }
    if metric in {"purchase_conversion_rate", "activation_rate"}:
        outcome = "is_purchased" if metric == "purchase_conversion_rate" else "is_activated"
        if dimension == "segment":
            sql = f"""
                SELECT COALESCE(s.segment, 'unknown') AS dimension_value,
                       COUNT(*) AS users, SUM(CASE WHEN um.{outcome} THEN 1 ELSE 0 END) AS successes,
                       ROUND(AVG(CASE WHEN um.{outcome} THEN 1.0 ELSE 0.0 END), 6) AS value
                FROM analytics.user_metrics um
                LEFT JOIN analytics.user_segments s ON um.user_id = s.user_id
                WHERE um.registration_date BETWEEN ? AND ?
                GROUP BY 1 ORDER BY value DESC LIMIT ?
            """
        else:
            sql = f"""
                SELECT COALESCE(u.{col}, 'unknown') AS dimension_value,
                       COUNT(*) AS users, SUM(CASE WHEN um.{outcome} THEN 1 ELSE 0 END) AS successes,
                       ROUND(AVG(CASE WHEN um.{outcome} THEN 1.0 ELSE 0.0 END), 6) AS value
                FROM analytics.user_metrics um
                JOIN analytics.users u ON um.user_id = u.user_id
                WHERE um.registration_date BETWEEN ? AND ?
                GROUP BY 1 ORDER BY value DESC LIMIT ?
            """
        df = query_df(sql, [start, end, limit])
        return {
            "metric": metric,
            "dimension": dimension,
            "rows": [
                {
                    "dimension_value": str(r.dimension_value),
                    "users": int(r.users),
                    "successes": int(r.successes),
                    "value": round(float(r.value), 6),
                }
                for r in df.itertuples()
            ],
        }
    if metric in {"dau", "events", "sessions"}:
        if metric == "dau":
            sql = f"""
                SELECT COALESCE(u.{col}, 'unknown') AS dimension_value,
                       COUNT(DISTINCT e.user_id) AS value
                FROM analytics.events e JOIN analytics.users u ON e.user_id = u.user_id
                WHERE e.event_date BETWEEN ? AND ?
                GROUP BY 1 ORDER BY value DESC LIMIT ?
            """
        elif metric == "events":
            sql = f"""
                SELECT COALESCE(u.{col}, 'unknown') AS dimension_value, COUNT(*) AS value
                FROM analytics.events e JOIN analytics.users u ON e.user_id = u.user_id
                WHERE e.event_date BETWEEN ? AND ?
                GROUP BY 1 ORDER BY value DESC LIMIT ?
            """
        else:
            sql = f"""
                SELECT COALESCE(u.{col}, 'unknown') AS dimension_value, COUNT(*) AS value
                FROM analytics.sessions s JOIN analytics.users u ON s.user_id = u.user_id
                WHERE CAST(s.session_start AS DATE) BETWEEN ? AND ?
                GROUP BY 1 ORDER BY value DESC LIMIT ?
            """
        df = query_df(sql, [start, end, limit])
        return {
            "metric": metric,
            "dimension": dimension,
            "rows": [
                {"dimension_value": str(r.dimension_value), "value": float(r.value)}
                for r in df.itertuples()
            ],
        }
    if metric == "mrr":
        if dimension == "segment":
            sql = """
                SELECT COALESCE(s.segment, 'unknown') AS dimension_value, ROUND(SUM(um.mrr), 2) AS value
                FROM analytics.user_metrics um LEFT JOIN analytics.user_segments s ON um.user_id = s.user_id
                GROUP BY 1 ORDER BY value DESC LIMIT ?
            """
        else:
            sql = f"""
                SELECT COALESCE(u.{col}, 'unknown') AS dimension_value, ROUND(SUM(um.mrr), 2) AS value
                FROM analytics.user_metrics um JOIN analytics.users u ON um.user_id = u.user_id
                GROUP BY 1 ORDER BY value DESC LIMIT ?
            """
        df = query_df(sql, [limit])
        return {
            "metric": metric,
            "dimension": dimension,
            "rows": [
                {"dimension_value": str(r.dimension_value), "value": float(r.value)}
                for r in df.itertuples()
            ],
        }
    raise ValueError(f"Unsupported metric/dimension combination: {metric}/{dimension}")


def overview() -> dict:
    settings = get_settings()
    as_of = settings.data_end_date.isoformat()
    latest = query_rows("SELECT * FROM analytics.daily_metrics ORDER BY metric_date DESC LIMIT 1")
    latest = latest[0] if latest else {}
    totals = query_rows(
        "SELECT COUNT(*) AS total_users, "
        f"SUM(CASE WHEN last_event_at >= DATE '{as_of}' - INTERVAL 30 DAY THEN 1 ELSE 0 END) "
        "AS active_30d, "
        "SUM(CASE WHEN is_purchased THEN 1 ELSE 0 END) AS purchasers, "
        "SUM(CASE WHEN is_activated THEN 1 ELSE 0 END) AS activated "
        "FROM analytics.user_metrics"
    )[0]
    retention = get_retention("daily")
    segments = query_rows(
        "SELECT segment, COUNT(*) AS users FROM analytics.user_segments GROUP BY 1 ORDER BY users DESC"
    )
    channels = query_rows(
        "SELECT u.acquisition_channel AS channel, COUNT(*) AS users, "
        "SUM(CASE WHEN um.is_purchased THEN 1 ELSE 0 END) AS purchasers "
        "FROM analytics.users u JOIN analytics.user_metrics um ON u.user_id = um.user_id "
        "GROUP BY 1 ORDER BY users DESC"
    )
    trend = query_rows(
        "SELECT metric_date, dau, wau, mau, dau_mau_ratio, registered_users, "
        "cohort_purchasing_users, purchase_conversion_rate, mrr, sessions, events "
        "FROM analytics.daily_metrics ORDER BY metric_date DESC LIMIT 30"
    )
    trend.reverse()
    anomalies = query_rows(
        "SELECT * FROM analytics.anomaly_events ORDER BY period_start DESC, severity LIMIT 6"
    )
    experiment = query_rows(
        "SELECT * FROM analytics.experiment_results WHERE variant = 'treatment' ORDER BY metric_key"
    )
    total = totals["total_users"] or 1
    return {
        "as_of": latest.get("metric_date"),
        "kpis": {
            "total_users": int(totals["total_users"] or 0),
            "active_users_30d": int(totals["active_30d"] or 0),
            "dau": int(latest.get("dau", 0)),
            "wau": int(latest.get("wau", 0)),
            "mau": int(latest.get("mau", 0)),
            "dau_mau_ratio": float(latest.get("dau_mau_ratio", 0)),
            "mrr": float(latest.get("mrr", 0)),
            "activation_rate": round(float(totals["activated"] or 0) / total, 6),
            "purchase_conversion_rate": round(float(totals["purchasers"] or 0) / total, 6),
            "retention_d7": (retention["summary"].get("d7") or {}).get("rate"),
        },
        "trend": trend,
        "channels": channels,
        "segments": segments,
        "anomalies": anomalies,
        "experiment": experiment,
        "methodology": {
            "activation_rate": "Users with an activation event / all users.",
            "purchase_conversion_rate": "Users with a purchase event / all users.",
            "retention_d7": "Weighted day-7 retention across complete registration cohorts.",
        },
    }


def list_users(
    limit: int = 50, offset: int = 0, search: str | None = None, segment: str | None = None
) -> dict:
    where = []
    params: list = []
    if search:
        where.append("(u.user_id ILIKE ? OR u.country ILIKE ? OR u.acquisition_channel ILIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])
    if segment:
        where.append("s.segment = ?")
        params.append(segment)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = query_rows(
        "SELECT COUNT(*) AS n FROM analytics.users u LEFT JOIN analytics.user_segments s ON u.user_id = s.user_id"
        + clause,
        params,
    )[0]["n"]
    rows = query_rows(
        "SELECT u.*, um.last_event_at, um.sessions_30d, um.events_30d, um.mrr, "
        "um.lifetime_revenue, um.recency_days, um.is_activated, um.is_purchased, "
        "s.segment, s.cluster_label "
        "FROM analytics.users u "
        "LEFT JOIN analytics.user_metrics um ON u.user_id = um.user_id "
        "LEFT JOIN analytics.user_segments s ON u.user_id = s.user_id"
        + clause
        + " ORDER BY u.user_id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return {"total": int(total), "limit": limit, "offset": offset, "rows": _clean_records(rows)}


def get_user_detail(user_id: str) -> dict | None:
    rows = query_rows(
        "SELECT u.*, um.*, s.segment, s.cluster_label FROM analytics.users u "
        "LEFT JOIN analytics.user_metrics um ON u.user_id = um.user_id "
        "LEFT JOIN analytics.user_segments s ON u.user_id = s.user_id WHERE u.user_id = ?",
        [user_id],
    )
    if not rows:
        return None
    events = query_rows(
        "SELECT event_id, event_name, event_timestamp, session_id, device, feature_key, plan "
        "FROM analytics.events WHERE user_id = ? ORDER BY event_timestamp DESC LIMIT 50",
        [user_id],
    )
    subs = query_rows("SELECT * FROM analytics.subscriptions WHERE user_id = ?", [user_id])
    return {
        "user": _clean_records(rows)[0],
        "recent_events": _clean_records(events),
        "subscriptions": _clean_records(subs),
    }


def list_events(
    limit: int = 50,
    offset: int = 0,
    user_id: str | None = None,
    event_name: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    where = []
    params: list = []
    if user_id:
        where.append("user_id = ?")
        params.append(user_id)
    if event_name:
        where.append("event_name = ?")
        params.append(event_name)
    if start_date:
        where.append("event_date >= ?")
        params.append(start_date.isoformat())
    if end_date:
        where.append("event_date <= ?")
        params.append(end_date.isoformat())
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = query_rows("SELECT COUNT(*) AS n FROM analytics.events" + clause, params)[0]["n"]
    rows = query_rows(
        "SELECT * FROM analytics.events" + clause + " ORDER BY event_timestamp DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return {"total": int(total), "limit": limit, "offset": offset, "rows": _clean_records(rows)}


def list_subscriptions(limit: int = 50, offset: int = 0, status: str | None = None) -> dict:
    where = []
    params: list = []
    if status:
        where.append("status = ?")
        params.append(status)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = query_rows("SELECT COUNT(*) AS n FROM analytics.subscriptions" + clause, params)[0]["n"]
    rows = query_rows(
        "SELECT * FROM analytics.subscriptions" + clause + " ORDER BY start_date DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return {"total": int(total), "limit": limit, "offset": offset, "rows": _clean_records(rows)}


def list_sessions(limit: int = 50, offset: int = 0, user_id: str | None = None) -> dict:
    where = []
    params: list = []
    if user_id:
        where.append("user_id = ?")
        params.append(user_id)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = query_rows("SELECT COUNT(*) AS n FROM analytics.sessions" + clause, params)[0]["n"]
    rows = query_rows(
        "SELECT * FROM analytics.sessions" + clause + " ORDER BY session_start DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return {"total": int(total), "limit": limit, "offset": offset, "rows": _clean_records(rows)}


def metric_definitions() -> list[dict]:
    rows = query_rows("SELECT * FROM analytics.metric_definitions ORDER BY metric_key")
    for row in rows:
        if isinstance(row.get("dimensions"), str):
            import json

            with contextlib.suppress(ValueError):
                row["dimensions"] = json.loads(row["dimensions"])
    return rows


def latest_anomalies(limit: int = 10) -> list[dict]:
    return query_rows(
        "SELECT * FROM analytics.anomaly_events ORDER BY period_start DESC LIMIT ?", [limit]
    )
