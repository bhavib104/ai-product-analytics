from __future__ import annotations

from datetime import date

from app.analytics.anomalies import _robust_z, _severity
from app.analytics.funnel import analyze_funnel
from app.analytics.retention import get_retention
from app.db.duck import query_rows

STAGES = [
    {"key": "registration", "label": "User Registration", "event_name": "user_registered"},
    {"key": "activation", "label": "Account Activated", "event_name": "account_activated"},
    {"key": "feature", "label": "First Feature Used", "event_name": "feature_used"},
    {"key": "plan", "label": "Plan Selected", "event_name": "subscription_selected"},
    {"key": "purchase", "label": "Purchase", "event_name": "purchase_completed"},
]


def test_robust_z_and_severity() -> None:
    z, median, mad = _robust_z(100, [20, 21, 19, 20, 22, 20, 21, 19])
    assert z > 4
    assert median == 20
    assert mad > 0
    assert _severity(z) in {"high", "critical"}
    assert _severity(0) == "low"
    assert _severity(-6.1) == "critical"


def test_default_funnel_is_ordered_and_monotonic() -> None:
    result = analyze_funnel(
        STAGES,
        date(2026, 5, 4),
        date(2026, 10, 30),
        window_days=14,
        compare_period=True,
    )
    assert result["funnel_id"] == "custom"
    assert len(result["stages"]) == 5
    assert result["cohort_users"] > 0
    users = [stage["users"] for stage in result["stages"]]
    assert users == sorted(users, reverse=True)
    assert result["stages"][0]["users"] == result["cohort_users"]
    for stage in result["stages"]:
        assert 0 <= stage["from_start_conversion"] <= 1
        assert 0 <= stage["step_conversion"] <= 1
        assert 0 <= stage["dropoff_rate"] <= 1
    assert result["comparison"] is not None
    assert len(result["comparison"]["stages"]) == 5
    assert result["chart"]["type"] == "funnel"


def test_funnel_dimension_breakdown_splits_cohort() -> None:
    result = analyze_funnel(
        STAGES,
        date(2026, 8, 1),
        date(2026, 9, 30),
        window_days=14,
        group_by="device",
    )
    assert result["group_by"] == "device"
    assert len(result["groups"]) >= 2
    assert sum(group["cohort_users"] for group in result["groups"]) == result["cohort_users"]


def test_retention_summary_is_bounded_and_complete() -> None:
    result = get_retention("daily", date(2026, 5, 4), date(2026, 10, 30))
    assert result["cohort_type"] == "daily"
    assert result["summary"]["d1"] is not None
    assert result["summary"]["d7"] is not None
    for key in ("d1", "d7", "d14", "d30"):
        summary = result["summary"][key]
        if summary:
            assert 0 <= summary["rate"] <= 1
            assert summary["retained"] <= summary["cohort_users"]
    assert len(result["curve"]) > 0
    assert result["cohorts"]


def test_retention_by_dimension_returns_groups() -> None:
    result = get_retention(
        "weekly",
        date(2026, 5, 4),
        date(2026, 10, 30),
        group_by="channel",
    )
    assert result["by_dimension"]
    assert all(group["periods"] for group in result["by_dimension"])


def test_seeded_anomalies_are_detected_once_each() -> None:
    rows = query_rows(
        "SELECT metric_key, period_start, granularity, observed_value, baseline_value, "
        "robust_z, severity FROM analytics.anomaly_events ORDER BY period_start"
    )
    keys = {row["metric_key"] for row in rows}
    assert keys == {"checkout_conversion_rate", "registrations", "cancellations"}
    by_metric = {row["metric_key"]: row for row in rows}
    assert str(by_metric["checkout_conversion_rate"]["period_start"]).startswith("2026-08-10")
    assert by_metric["checkout_conversion_rate"]["observed_value"] == 0.0
    assert str(by_metric["registrations"]["period_start"]).startswith("2026-09-15")
    assert by_metric["registrations"]["observed_value"] > by_metric["registrations"]["baseline_value"]
    assert str(by_metric["cancellations"]["period_start"]).startswith("2026-10-05")
    assert all(abs(row["robust_z"]) >= 4 for row in rows)
