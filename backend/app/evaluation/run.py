"""Reproducible Copilot and Text-to-SQL evaluation.

Expected values are recomputed independently from the raw synthetic CSVs using
pandas, not read from the analytical marts that the product serves.  The script
runs the real orchestrator and SQL pipeline, then reports only measured checks.
Run from ``backend/``:

    python -m app.evaluation.run
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from app.ai.orchestrator import Orchestrator
from app.core.config import get_settings
from app.text_to_sql.generator import resolve_dates
from app.text_to_sql.pipeline import answer_question
from app.text_to_sql.validator import validate_sql

# ---------------------------------------------------------------------------
# Independent raw-data reference
# ---------------------------------------------------------------------------


def _as_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.date


def _as_utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", utc=True)


def _to_date(value) -> date | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _p_value(successes_a: int, n_a: int, successes_b: int, n_b: int) -> float | None:
    if not n_a or not n_b:
        return None
    table = [
        [successes_a, n_a - successes_a],
        [successes_b, n_b - successes_b],
    ]
    if min(expected for row in table for expected in row) < 0:
        return None
    expected = scipy_stats.chi2_contingency(table, correction=False)[3]
    if expected.min() < 5:
        return float(scipy_stats.fisher_exact(table)[1])
    return float(scipy_stats.chi2_contingency(table, correction=False)[1])


@dataclass
class RawReference:
    """Cleaned raw reference tables and independently derived metrics."""

    start: date
    end: date
    users: pd.DataFrame = field(init=False)
    events: pd.DataFrame = field(init=False)
    sessions: pd.DataFrame = field(init=False)
    subscriptions: pd.DataFrame = field(init=False)
    assignments: pd.DataFrame = field(init=False)
    features: pd.DataFrame = field(init=False)

    def __post_init__(self) -> None:
        settings = get_settings()
        raw = Path(settings.data_dir) / "raw"
        self.users = self._clean_users(pd.read_csv(raw / "users.csv", dtype=str))
        self.events = self._clean_events(pd.read_csv(raw / "events.csv", dtype=str))
        self.sessions = self._clean_sessions(pd.read_csv(raw / "sessions.csv", dtype=str))
        self.subscriptions = self._clean_subscriptions(
            pd.read_csv(raw / "subscriptions.csv", dtype=str)
        )
        self.assignments = self._clean_assignments(
            pd.read_csv(raw / "experiment_assignments.csv", dtype=str)
        )
        self.features = pd.read_csv(raw / "features.csv", dtype=str)
        self._active_dates = (
            self.events.groupby("user_id")["event_date"].apply(set).to_dict()
        )

    # -- cleaning mirrors the documented validation contract ----------------
    def _clean_users(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        for col in ["user_id", "registration_date", "country", "device_type", "acquisition_channel"]:
            df[col] = df[col].astype(str).str.strip()
        df["registration_date"] = _as_date(df["registration_date"])
        df = df[df["user_id"].ne("") & df["registration_date"].notna()]
        df = df[~df["user_id"].duplicated(keep="first")]
        for col, fill in {
            "country": "unknown",
            "device_type": "unknown",
            "acquisition_channel": "unknown",
            "subscription_type": "free",
            "user_status": "unknown",
        }.items():
            df[col] = df[col].replace("", fill).fillna(fill)
        return df.reset_index(drop=True)

    def _clean_events(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["event_timestamp"] = _as_utc(df["event_timestamp"])
        df = df[
            df["event_id"].astype(str).str.strip().ne("")
            & df["user_id"].astype(str).str.strip().ne("")
            & df["event_name"].astype(str).str.strip().ne("")
            & df["event_timestamp"].notna()
        ]
        df = df[
            (df["event_timestamp"].dt.date >= self.start - timedelta(days=1))
            & (df["event_timestamp"].dt.date <= self.end + timedelta(days=1))
        ]
        df = df.merge(
            self.users[["user_id", "registration_date"]], on="user_id", how="inner"
        )
        df = df[df["event_timestamp"].dt.date >= df["registration_date"]]
        df = df[~df["event_id"].duplicated(keep="first")].copy()
        df["device"] = df["device"].replace("", "unknown").fillna("unknown")
        df["event_date"] = df["event_timestamp"].dt.date
        parsed = df["properties"].map(
            lambda value: json.loads(value) if isinstance(value, str) and value else {}
        )
        df["feature_key"] = [
            value.get("feature_key") if isinstance(value, dict) else None for value in parsed
        ]
        return df.reset_index(drop=True)

    def _clean_sessions(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["start_time"] = _as_utc(df["start_time"])
        df["end_time"] = _as_utc(df["end_time"])
        df = df[
            df["session_id"].astype(str).str.strip().ne("")
            & df["user_id"].astype(str).str.strip().ne("")
            & df["start_time"].notna()
        ]
        df = df[~df["session_id"].duplicated(keep="first")]
        df = df[df["user_id"].isin(self.users["user_id"])].copy()
        df["duration_seconds"] = pd.to_numeric(df["duration_seconds"], errors="coerce").fillna(0)
        df.loc[df["duration_seconds"] <= 0, "duration_seconds"] = 0
        df["session_date"] = df["start_time"].dt.date
        return df.reset_index(drop=True)

    def _clean_subscriptions(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["start_date"] = _as_date(df["start_date"])
        df["renewal_date"] = _as_date(df["renewal_date"])
        df["cancelled_date"] = _as_date(df["cancelled_date"])
        df = df[
            df["subscription_id"].astype(str).str.strip().ne("")
            & df["user_id"].astype(str).str.strip().ne("")
            & df["plan"].astype(str).str.strip().ne("")
            & df["start_date"].notna()
        ]
        df = df[~df["subscription_id"].duplicated(keep="first")]
        df = df[df["user_id"].isin(self.users["user_id"])].copy()
        df["mrr"] = (pd.to_numeric(df["mrr_cents"], errors="coerce").fillna(0) / 100).round(2)
        df["total_revenue"] = (
            pd.to_numeric(df["total_revenue_cents"], errors="coerce").fillna(0) / 100
        ).round(2)
        return df.reset_index(drop=True)

    def _clean_assignments(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["assigned_at"] = _as_utc(df["assigned_at"])
        df = df[
            df["assignment_id"].astype(str).str.strip().ne("")
            & df["experiment_id"].astype(str).str.strip().ne("")
            & df["user_id"].astype(str).str.strip().ne("")
            & df["assigned_at"].notna()
            & df["variant"].isin(["control", "treatment"])
        ]
        df = df[~df["assignment_id"].duplicated(keep="first")]
        df = df[~df.duplicated(["experiment_id", "user_id"], keep="first")]
        df = df[df["user_id"].isin(self.users["user_id"])].copy()
        return df.reset_index(drop=True)

    # -- independently computed metrics ------------------------------------
    def overview(self) -> dict:
        last_event = self.events.groupby("user_id")["event_date"].max()
        active_cutoff = self.end - timedelta(days=30)
        active = int((last_event >= active_cutoff).sum())
        purchased = int(self.events.loc[self.events["event_name"] == "purchase_completed", "user_id"].nunique())
        activated = int(self.events.loc[self.events["event_name"] == "account_activated", "user_id"].nunique())
        active_subs = self.subscriptions[
            (self.subscriptions["start_date"] <= self.end)
            & (
                self.subscriptions["cancelled_date"].isna()
                | (self.subscriptions["cancelled_date"] > self.end)
            )
        ]
        mrr = float(active_subs["mrr"].sum())
        return {
            "total_users": int(len(self.users)),
            "active_users_30d": active,
            "purchasers": purchased,
            "activated": activated,
            "mrr": round(mrr, 2),
            "purchase_conversion_rate": round(purchased / len(self.users), 6),
            "activation_rate": round(activated / len(self.users), 6),
            "retention_d7": self.retention_d7(),
        }

    def registration_on(self, day: date) -> int:
        return int((self.users["registration_date"] == day).sum())

    def retention_d7(self) -> float:
        retained = 0
        cohort = 0
        for row in self.users.itertuples():
            target = row.registration_date + timedelta(days=7)
            if target > self.end:
                continue
            cohort += 1
            retained += target in self._active_dates.get(row.user_id, set())
        return round(retained / cohort, 6) if cohort else 0.0

    def retention_d7_by_channel(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for row in self.users.itertuples():
            target = row.registration_date + timedelta(days=7)
            bucket = out.setdefault(row.acquisition_channel, {"cohort_users": 0, "retained": 0})
            bucket["cohort_users"] += 1
            if target in self._active_dates.get(row.user_id, set()):
                bucket["retained"] += 1
        for bucket in out.values():
            bucket["rate"] = round(bucket["retained"] / bucket["cohort_users"], 6) if bucket["cohort_users"] else 0.0
        return out

    def retention_by_channel_in_range(self, start: date, end: date) -> dict[str, float]:
        out: dict[str, dict] = {}
        subset = self.users[
            (self.users["registration_date"] >= start) & (self.users["registration_date"] <= end)
        ]
        for row in subset.itertuples():
            target = row.registration_date + timedelta(days=7)
            bucket = out.setdefault(row.acquisition_channel, {"cohort_users": 0, "retained": 0})
            bucket["cohort_users"] += 1
            if target in self._active_dates.get(row.user_id, set()):
                bucket["retained"] += 1
        return {
            key: round(value["retained"] / value["cohort_users"], 6)
            for key, value in out.items()
            if value["cohort_users"]
        }

    def _checkout_by_dimension(self, start: date, end: date, column: str) -> dict[str, dict]:
        checkouts = self.events[
            (self.events["event_name"] == "checkout_started")
            & (self.events["event_date"] >= start)
            & (self.events["event_date"] <= end)
        ]
        if column == "device_type":
            checkouts = checkouts.merge(
                self.users[["user_id", "device_type"]], on="user_id", how="left"
            ).copy()
            checkouts["dimension_value"] = checkouts["device_type"].fillna("unknown")
        else:
            checkouts = checkouts.copy()
            checkouts["dimension_value"] = checkouts["device"]
        purchases = self.events[self.events["event_name"] == "purchase_completed"]
        purchase_times: dict[str, list[pd.Timestamp]] = {}
        for row in purchases.itertuples():
            purchase_times.setdefault(row.user_id, []).append(row.event_timestamp)
        for values in purchase_times.values():
            values.sort()
        out: dict[str, dict] = {}
        for row in checkouts.itertuples():
            bucket = out.setdefault(row.dimension_value, {"checkouts": 0, "conversions": 0})
            bucket["checkouts"] += 1
            values = purchase_times.get(row.user_id, [])
            if values:
                start_ts = row.event_timestamp
                end_ts = start_ts + pd.Timedelta(days=7)
                idx = np.searchsorted(values, start_ts)
                if idx < len(values) and values[idx] <= end_ts:
                    bucket["conversions"] += 1
        for bucket in out.values():
            bucket["conversion_rate"] = round(
                bucket["conversions"] / bucket["checkouts"], 4
            ) if bucket["checkouts"] else 0.0
        return out

    def checkout_by_device(self, start: date, end: date) -> dict[str, dict]:
        """Copilot dimension breakdown groups by the user's device_type."""
        return self._checkout_by_dimension(start, end, "device_type")

    def checkout_by_event_device(self, start: date, end: date) -> dict[str, dict]:
        """The reviewed SQL template groups checkout events by event.device."""
        return self._checkout_by_dimension(start, end, "device")

    def experiment_rates(self, metric: str, window_days: int) -> dict:
        event_name = "account_activated" if metric == "activation_7d" else "purchase_completed"
        assignments = self.assignments[self.assignments["experiment_id"] == "exp_onboarding_checklist_v1"]
        events = self.events[self.events["event_name"] == event_name]
        by_user = events.groupby("user_id")["event_timestamp"].apply(list).to_dict()
        result: dict[str, dict] = {}
        for row in assignments.itertuples():
            bucket = result.setdefault(row.variant, {"successes": 0, "sample_size": 0})
            bucket["sample_size"] += 1
            end_ts = row.assigned_at + pd.Timedelta(days=window_days)
            if any(row.assigned_at <= ts <= end_ts for ts in by_user.get(row.user_id, [])):
                bucket["successes"] += 1
        for bucket in result.values():
            bucket["rate"] = round(bucket["successes"] / bucket["sample_size"], 6)
        result["p_value"] = _p_value(
            result["control"]["successes"],
            result["control"]["sample_size"],
            result["treatment"]["successes"],
            result["treatment"]["sample_size"],
        )
        return result

    def rule_segment_counts(self) -> dict[str, int]:
        cutoff = self.end - timedelta(days=30)
        last_event = self.events.groupby("user_id")["event_date"].max()
        sessions_30d = (
            self.events[self.events["event_date"] > cutoff]
            .groupby("user_id")["session_id"]
            .nunique()
        )
        active_subs = self.subscriptions[self.subscriptions["status"] == "active"]
        mrr = active_subs.groupby("user_id")["mrr"].sum()
        revenue = self.subscriptions.groupby("user_id")["total_revenue"].sum()
        counts: dict[str, int] = {}
        for row in self.users.itertuples():
            uid = row.user_id
            last = last_event.get(uid)
            recency = (self.end - last).days if last is not None else 9999
            tenure = (self.end - row.registration_date).days
            sessions = int(sessions_30d.get(uid, 0))
            user_mrr = float(mrr.get(uid, 0.0))
            lifetime = float(revenue.get(uid, 0.0))
            if user_mrr >= 50 and sessions >= 8 and recency <= 14:
                segment = "champions"
            elif sessions >= 10 and recency <= 7:
                segment = "power_users"
            elif tenure <= 30 and sessions >= 3:
                segment = "new_engaged"
            elif tenure > 30 and 14 <= recency <= 45 and lifetime > 0:
                segment = "at_risk"
            elif recency > 45:
                segment = "dormant"
            elif recency <= 14 and user_mrr == 0:
                segment = "active_free"
            elif recency <= 45 and sessions <= 2:
                segment = "low_engagement"
            else:
                segment = "other"
            counts[segment] = counts.get(segment, 0) + 1
        return counts

    def feature_adoption(self, start: date, end: date) -> dict:
        events = self.events[
            (self.events["event_date"] >= start)
            & (self.events["event_date"] <= end)
            & (self.events["event_name"] == "feature_used")
            & self.events["feature_key"].notna()
        ]
        daily_users = (
            events.groupby(["event_date", "feature_key"])["user_id"].nunique().reset_index(name="users")
        )
        dau = self.events[
            (self.events["event_date"] >= start) & (self.events["event_date"] <= end)
        ].groupby("event_date")["user_id"].nunique()
        daily_users["adoption_rate"] = daily_users.apply(
            lambda row: row["users"] / dau.get(row["event_date"], 1), axis=1
        )
        grouped = daily_users.groupby("feature_key").agg(
            users=("users", "sum"), avg_adoption_rate=("adoption_rate", "mean")
        )
        names = self.features.set_index("feature_key")["feature_name"].to_dict()
        rows = [
            {
                "feature_key": key,
                "feature_name": names.get(key, key),
                "users": int(value.users),
                "avg_adoption_rate": round(float(value.avg_adoption_rate), 4),
            }
            for key, value in grouped.iterrows()
        ]
        rows.sort(key=lambda row: row["users"], reverse=True)
        return {"rows": rows, "top": rows[0] if rows else None}

    def registrations_by_channel(self, start: date, end: date) -> dict[str, int]:
        subset = self.users[
            (self.users["registration_date"] >= start) & (self.users["registration_date"] <= end)
        ]
        return subset.groupby("acquisition_channel").size().astype(int).to_dict()

    def cancellations_by_plan(self, start: date, end: date) -> dict[str, dict]:
        subset = self.subscriptions[
            self.subscriptions["cancelled_date"].notna()
            & (self.subscriptions["cancelled_date"] >= start)
            & (self.subscriptions["cancelled_date"] <= end)
        ]
        grouped = subset.groupby("plan").agg(cancellations=("plan", "size"), lost_mrr=("mrr", "sum"))
        return {
            plan: {
                "cancellations": int(row.cancellations),
                "lost_mrr": round(float(row.lost_mrr), 2),
            }
            for plan, row in grouped.iterrows()
        }


# ---------------------------------------------------------------------------
# Evaluation cases
# ---------------------------------------------------------------------------


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


def _close(actual: float | None, expected: float | None, tolerance: float = 1e-4) -> bool:
    if actual is None or expected is None:
        return False
    return math.isclose(float(actual), float(expected), rel_tol=tolerance, abs_tol=tolerance)


def _tool_data(tool_calls: list[dict], tool: str) -> dict:
    return next((call for call in tool_calls if call["tool"] == tool and call["status"] == "success"), {})


def _data_payload(plan: list[tuple[str, dict]], orchestrator: Orchestrator) -> dict[str, dict]:
    payload: dict[str, dict] = {}
    for name, args in plan:
        result = orchestrator.registry.execute(name, args)
        if result.status == "success":
            payload[name] = result.data
    return payload


@dataclass
class Case:
    case_id: str
    kind: str
    question: str
    required_tools: list[str]
    verifier: Callable[[dict, RawReference], list[Check]]


def _copilot_cases() -> list[Case]:
    return [
        Case(
            "overview_health",
            "copilot",
            "What is the overall product health and KPI summary?",
            ["get_overview"],
            lambda payload, ref: _overview_checks(payload, ref),
        ),
        Case(
            "total_users",
            "copilot",
            "How many total users do we have?",
            ["get_overview"],
            lambda payload, ref: [
                Check(
                    "total users",
                    payload["get_overview"]["kpis"]["total_users"] == ref.overview()["total_users"],
                    f"{payload['get_overview']['kpis']['total_users']} vs {ref.overview()['total_users']}",
                )
            ],
        ),
        Case(
            "registration_sep15",
            "copilot",
            "How many users registered on September 15, 2026?",
            ["get_metric_series"],
            lambda payload, ref: _registration_checks(payload, ref),
        ),
        Case(
            "checkout_outage",
            "copilot",
            "Why did checkout conversion drop in August? Which device was worst?",
            ["get_anomalies", "get_dimension_breakdown"],
            lambda payload, ref: _checkout_outage_checks(payload, ref),
        ),
        Case(
            "checkout_by_device",
            "copilot",
            "What is checkout conversion by device in August?",
            ["get_dimension_breakdown"],
            lambda payload, ref: _checkout_device_checks(payload, ref, date(2026, 8, 1), date(2026, 8, 31)),
        ),
        Case(
            "experiment_activation",
            "copilot",
            "How did the onboarding checklist experiment perform?",
            ["get_experiment"],
            lambda payload, ref: _experiment_checks(payload, ref, "activation_7d", 7),
        ),
        Case(
            "experiment_purchase",
            "copilot",
            "Did the onboarding checklist experiment improve purchase conversion?",
            ["get_experiment"],
            lambda payload, ref: _experiment_checks(payload, ref, "purchase_14d", 14),
        ),
        Case(
            "srm",
            "copilot",
            "Was the onboarding checklist experiment assignment balanced?",
            ["get_experiment"],
            lambda payload, ref: _srm_checks(payload, ref),
        ),
        Case(
            "retention_channel",
            "copilot",
            "Which acquisition channel has the weakest D7 retention?",
            ["get_retention"],
            lambda payload, ref: _retention_channel_checks(payload, ref),
        ),
        Case(
            "retention_device",
            "copilot",
            "What is weekly retention by device?",
            ["get_retention"],
            lambda payload, ref: [
                Check(
                    "weekly device groups",
                    bool(payload["get_retention"].get("by_dimension")),
                    f"{len(payload['get_retention'].get('by_dimension', []))} groups",
                )
            ],
        ),
        Case(
            "segments",
            "copilot",
            "How many users are in each rule-based segment?",
            ["get_segments"],
            lambda payload, ref: _segment_checks(payload, ref),
        ),
        Case(
            "anomalies",
            "copilot",
            "What anomalies were detected since July?",
            ["get_anomalies"],
            lambda payload, ref: _anomaly_checks(payload, ref),
        ),
        Case(
            "features",
            "copilot",
            "Which features have the highest adoption since August?",
            ["get_feature_adoption"],
            lambda payload, ref: _feature_checks(payload, ref),
        ),
        Case(
            "forecast_scope",
            "copilot",
            "What will revenue be next quarter?",
            ["get_metric_series"],
            lambda payload, ref: [
                Check(
                    "scope limitation stated",
                    "does not forecast" in payload["answer"].lower(),
                    payload["answer"][:120],
                )
            ],
        ),
    ]


def _sql_cases() -> list[Case]:
    return [
        Case(
            "sql_registrations_by_channel",
            "sql",
            "How many registrations were there by channel since July?",
            [],
            lambda payload, ref: _sql_registration_checks(payload, ref),
        ),
        Case(
            "sql_experiment_results",
            "sql",
            "Show experiment results",
            [],
            lambda payload, ref: _sql_experiment_checks(payload, ref),
        ),
        Case(
            "sql_checkout_by_device",
            "sql",
            "What was checkout conversion by device in August?",
            [],
            lambda payload, ref: _sql_checkout_checks(payload, ref),
        ),
        Case(
            "sql_paid_social_retention",
            "sql",
            "Show paid-social retention since August",
            [],
            lambda payload, ref: _sql_retention_checks(payload, ref),
        ),
        Case(
            "sql_cancellations_by_plan",
            "sql",
            "Show cancellations by plan in October",
            [],
            lambda payload, ref: _sql_cancellation_checks(payload, ref),
        ),
        Case(
            "sql_feature_adoption",
            "sql",
            "What are the feature adoption numbers since August?",
            [],
            lambda payload, ref: _sql_feature_checks(payload, ref),
        ),
    ]


def _overview_checks(payload: dict, ref: RawReference) -> list[Check]:
    expected = ref.overview()
    kpis = payload["get_overview"]["kpis"]
    return [
        Check("total users", kpis["total_users"] == expected["total_users"], str(kpis["total_users"])),
        Check("active 30d", kpis["active_users_30d"] == expected["active_users_30d"], str(kpis["active_users_30d"])),
        Check("MRR", _close(kpis["mrr"], expected["mrr"], 0.01), f"{kpis['mrr']} vs {expected['mrr']}"),
        Check(
            "purchase conversion",
            _close(kpis["purchase_conversion_rate"], expected["purchase_conversion_rate"]),
            f"{kpis['purchase_conversion_rate']} vs {expected['purchase_conversion_rate']}",
        ),
        Check("D7 retention", _close(kpis["retention_d7"], expected["retention_d7"]), f"{kpis['retention_d7']} vs {expected['retention_d7']}"),
        Check("answer contains total users", "5000 total users" in payload["answer"], "5000 total users"),
    ]


def _registration_checks(payload: dict, ref: RawReference) -> list[Check]:
    expected = ref.registration_on(date(2026, 9, 15))
    points = payload["get_metric_series"].get("points", [])
    point = next((p for p in points if str(p["date"]).startswith("2026-09-15")), None)
    return [
        Check("daily point returned", point is not None, f"{len(points)} points"),
        Check("registration count", point is not None and int(point["value"]) == expected, f"{point} vs {expected}"),
        Check("answer contains count", str(expected) in payload["answer"], str(expected)),
    ]


def _checkout_outage_checks(payload: dict, ref: RawReference) -> list[Check]:
    rows = payload["get_anomalies"].get("anomalies", [])
    checkout = next((row for row in rows if row["metric_key"] == "checkout_conversion_rate"), None)
    by_device = payload["get_dimension_breakdown"].get("rows", [])
    expected = ref.checkout_by_device(date(2026, 8, 1), date(2026, 8, 31))
    lowest = min(expected, key=lambda key: expected[key]["conversion_rate"]) if expected else None
    return [
        Check("outage anomaly present", checkout is not None, str(checkout)),
        Check("observed conversion is zero", checkout is not None and float(checkout["observed_value"]) == 0.0, str(checkout)),
        Check("device breakdown returned", bool(by_device), f"{len(by_device)} devices"),
        Check("lowest device matches raw", bool(by_device) and by_device[-1]["dimension_value"] == lowest, f"{by_device[-1] if by_device else None} vs {lowest}"),
        Check("answer names checkout metric", "checkout_conversion_rate" in payload["answer"], "checkout_conversion_rate"),
    ]


def _checkout_device_checks(payload: dict, ref: RawReference, start: date, end: date) -> list[Check]:
    expected = ref.checkout_by_device(start, end)
    rows = payload["get_dimension_breakdown"].get("rows", [])
    actual = {row["dimension_value"]: row["value"] for row in rows}
    checks = [Check("all devices returned", set(actual) == set(expected), f"{sorted(actual)} vs {sorted(expected)}")]
    for device in sorted(expected):
        checks.append(
            Check(
                f"{device} conversion",
                _close(actual.get(device), expected[device]["conversion_rate"], 1e-3),
                f"{actual.get(device)} vs {expected[device]['conversion_rate']}",
            )
        )
    return checks


def _experiment_checks(payload: dict, ref: RawReference, metric_key: str, window: int) -> list[Check]:
    expected = ref.experiment_rates(metric_key, window)
    data = payload["get_experiment"]
    metric = next((row for row in data["metrics"] if row["metric_key"] == metric_key), None)
    checks = [Check("metric present", metric is not None, metric_key)]
    if metric:
        for variant in ("control", "treatment"):
            checks.append(
                Check(
                    f"{variant} rate",
                    _close(metric["variants"][variant]["rate"], expected[variant]["rate"]),
                    f"{metric['variants'][variant]['rate']} vs {expected[variant]['rate']}",
                )
            )
        checks.append(
            Check(
                "p-value",
                _close(metric.get("p_value"), expected["p_value"], 1e-6),
                f"{metric.get('p_value')} vs {expected['p_value']}",
            )
        )
    return checks


def _srm_checks(payload: dict, ref: RawReference) -> list[Check]:
    expected = ref.experiment_rates("activation_7d", 7)
    assignment = payload["get_experiment"]["assignment"]
    counts = {row["variant"]: int(row["users"]) for row in assignment["counts"]}
    return [
        Check("control count", counts.get("control") == expected["control"]["sample_size"], str(counts.get("control"))),
        Check("treatment count", counts.get("treatment") == expected["treatment"]["sample_size"], str(counts.get("treatment"))),
        Check("SRM interpretation", "consistent" in assignment["srm"]["interpretation"].lower(), assignment["srm"]["interpretation"]),
    ]


def _retention_channel_checks(payload: dict, ref: RawReference) -> list[Check]:
    start, end = resolve_dates(payload["question"])
    expected = ref.retention_by_channel_in_range(start, end)
    weakest = min(expected, key=lambda key: expected[key])
    groups = payload["get_retention"].get("by_dimension", [])
    actual = {}
    for group in groups:
        period = next((p for p in group["periods"] if p["period_days"] == 7), None)
        if period:
            actual[group["value"]] = period["rate"]
    return [
        Check("channel groups returned", set(actual) == set(expected), f"{sorted(actual)} vs {sorted(expected)}"),
        Check("weakest channel matches raw", min(actual, key=actual.get) == weakest if actual else False, f"{min(actual, key=actual.get) if actual else None} vs {weakest}"),
        Check("answer names weakest channel", weakest in payload["answer"], weakest),
    ]


def _segment_checks(payload: dict, ref: RawReference) -> list[Check]:
    expected = ref.rule_segment_counts()
    actual = {row["name"]: int(row["users"]) for row in payload["get_segments"]["segments"]["rule_segments"]}
    checks = [Check("segment set", set(actual) == set(expected), f"{sorted(actual)} vs {sorted(expected)}")]
    for segment in sorted(expected):
        checks.append(Check(f"{segment} users", actual.get(segment) == expected[segment], f"{actual.get(segment)} vs {expected[segment]}"))
    return checks


def _anomaly_checks(payload: dict, ref: RawReference) -> list[Check]:
    rows = payload["get_anomalies"].get("anomalies", [])
    by_metric = {row["metric_key"]: row for row in rows}
    expected_reg = ref.registration_on(date(2026, 9, 15))
    return [
        Check("three anomalies", len(rows) == 3, str(len(rows))),
        Check("checkout anomaly", "checkout_conversion_rate" in by_metric, str(by_metric.get("checkout_conversion_rate"))),
        Check("registration anomaly", by_metric.get("registrations", {}).get("observed_value") == expected_reg, str(by_metric.get("registrations"))),
        Check("cancellation anomaly", by_metric.get("cancellations", {}).get("observed_value") == 16.0, str(by_metric.get("cancellations"))),
    ]


def _feature_checks(payload: dict, ref: RawReference) -> list[Check]:
    expected = ref.feature_adoption(date(2026, 8, 1), date(2026, 10, 30))
    actual = payload["get_feature_adoption"].get("features", [])
    top = actual[0] if actual else None
    return [
        Check("features returned", bool(actual), f"{len(actual)} features"),
        Check("top feature", top is not None and top["feature_name"] == expected["top"]["feature_name"], f"{top} vs {expected['top']}"),
        Check("top feature user-days", top is not None and int(top["users"]) == expected["top"]["users"], f"{top['users'] if top else None} vs {expected['top']['users']}"),
    ]


def _sql_registration_checks(payload: dict, ref: RawReference) -> list[Check]:
    start, end = resolve_dates(payload["question"])
    expected = ref.registrations_by_channel(start, end)
    actual = {row["channel"]: int(row["users"]) for row in payload["rows"]}
    return [
        Check("SQL status", payload["status"] == "success", payload["status"]),
        Check("template", payload["template"] == "registrations_by_channel", str(payload["template"])),
        Check("channel counts", actual == expected, f"{actual} vs {expected}"),
    ]


def _sql_experiment_checks(payload: dict, ref: RawReference) -> list[Check]:
    expected_activation = ref.experiment_rates("activation_7d", 7)
    expected_purchase = ref.experiment_rates("purchase_14d", 14)
    rows = payload["rows"]
    checks = [Check("four result rows", len(rows) == 4, str(len(rows)))]
    for row in rows:
        expected = expected_activation if row["metric_key"] == "activation_7d" else expected_purchase
        checks.append(
            Check(
                f"{row['metric_key']} {row['variant']} rate",
                _close(row["rate"], expected[row["variant"]]["rate"]),
                f"{row['rate']} vs {expected[row['variant']]['rate']}",
            )
        )
    return checks


def _sql_checkout_checks(payload: dict, ref: RawReference) -> list[Check]:
    start, end = resolve_dates(payload["question"])
    expected = ref.checkout_by_event_device(start, end)
    actual = {row["device"]: row["conversion_rate"] for row in payload["rows"]}
    checks = [Check("device set", set(actual) == set(expected), f"{sorted(actual)} vs {sorted(expected)}")]
    for device in sorted(expected):
        checks.append(Check(f"{device} rate", _close(actual.get(device), expected[device]["conversion_rate"], 1e-3), f"{actual.get(device)} vs {expected[device]['conversion_rate']}"))
    return checks


def _sql_retention_checks(payload: dict, ref: RawReference) -> list[Check]:
    start, end = resolve_dates(payload["question"])
    expected = ref.retention_by_channel_in_range(start, end).get("paid_social")
    rows = [row for row in payload["rows"] if row["period_days"] == 7]
    total = sum(int(row.get("cohort_users", row.get("cohort_size", 0))) for row in rows)
    retained = sum(int(row["retained_users"]) for row in rows)
    actual = round(retained / total, 4) if total else None
    return [
        Check("D7 rows returned", bool(rows), f"{len(rows)} rows"),
        Check("D7 weighted rate", _close(actual, expected, 1e-3), f"{actual} vs {expected}"),
    ]


def _sql_cancellation_checks(payload: dict, ref: RawReference) -> list[Check]:
    start, end = resolve_dates(payload["question"])
    expected = ref.cancellations_by_plan(start, end)
    actual = {
        row["plan"]: {"cancellations": int(row["cancellations"]), "lost_mrr": round(float(row["lost_mrr"]), 2)}
        for row in payload["rows"]
    }
    return [
        Check("plan set", set(actual) == set(expected), f"{sorted(actual)} vs {sorted(expected)}"),
        Check("cancellation counts", actual == expected, f"{actual} vs {expected}"),
    ]


def _sql_feature_checks(payload: dict, ref: RawReference) -> list[Check]:
    start, end = resolve_dates(payload["question"])
    expected = ref.feature_adoption(start, end)
    actual_top = payload["rows"][0] if payload["rows"] else None
    return [
        Check("top feature", actual_top is not None and actual_top["feature_name"] == expected["top"]["feature_name"], f"{actual_top} vs {expected['top']}"),
        Check("top feature user-days", actual_top is not None and int(actual_top["users"]) == expected["top"]["users"], f"{actual_top['users'] if actual_top else None} vs {expected['top']['users']}"),
    ]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _run_copilot(case: Case, orchestrator: Orchestrator, ref: RawReference) -> dict:
    started = time.perf_counter()
    result = orchestrator.answer(case.question)
    latency = int((time.perf_counter() - started) * 1000)
    start, end = resolve_dates(case.question)
    plan = orchestrator._plan(case.question, start, end, get_settings().ai_max_tool_calls)
    data = _data_payload(plan, orchestrator)
    payload = {
        "answer": result["answer"],
        "question": case.question,
        "tool_calls": result["tool_calls"],
        "data": data,
        **data,
    }
    checks: list[Check] = []
    tool_names = {call["tool"] for call in result["tool_calls"]}
    for required in case.required_tools:
        checks.append(Check(f"tool {required}", required in tool_names, str(sorted(tool_names))))
    checks.append(
        Check(
            "all tool calls successful",
            all(call["status"] == "success" for call in result["tool_calls"]),
            str([(call["tool"], call["status"]) for call in result["tool_calls"]]),
        )
    )
    checks.append(Check("citations present", bool(result["citations"]), str(result["citations"])))
    checks.extend(case.verifier(payload, ref))
    return {
        "case_id": case.case_id,
        "kind": case.kind,
        "question": case.question,
        "latency_ms": latency,
        "tool_calls": len(result["tool_calls"]),
        "tool_successes": sum(1 for call in result["tool_calls"] if call["status"] == "success"),
        "citations": result["citations"],
        "passed": all(check.passed for check in checks),
        "checks": [check.__dict__ for check in checks],
    }


def _run_sql(case: Case, ref: RawReference) -> dict:
    started = time.perf_counter()
    payload = answer_question(case.question)
    latency = int((time.perf_counter() - started) * 1000)
    checks: list[Check] = [
        Check("status", payload["status"] == "success", payload["status"]),
        Check("SQL generated", bool(payload.get("sql")), str(payload.get("sql"))[:120]),
        Check("SQL validated", bool(payload.get("validation", {}).get("valid")), str(payload.get("validation"))),
    ]
    checks.extend(case.verifier({**payload, "question": case.question}, ref))
    return {
        "case_id": case.case_id,
        "kind": case.kind,
        "question": case.question,
        "latency_ms": latency,
        "tool_calls": 0,
        "tool_successes": 0,
        "citations": [],
        "passed": all(check.passed for check in checks),
        "checks": [check.__dict__ for check in checks],
    }


def _sql_safety() -> dict:
    unsafe = [
        "DROP TABLE analytics.events",
        "DELETE FROM analytics.events",
        "UPDATE analytics.events SET event_name = 'x'",
        "PRAGMA database_list",
        "ATTACH 'other.db' AS other",
        "SELECT * FROM analytics.events; SELECT * FROM analytics.users",
        "SELECT * FROM raw.events",
        "SELECT * FROM read_csv_auto('secrets.csv')",
        "SELECT * FROM information_schema.tables",
        "WITH RECURSIVE x AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM x) SELECT * FROM x",
        "SELECT 1 INTO copied",
        "SELECT * FROM analytics.events e JOIN analytics.users u ON e.user_id = u.user_id "
        "JOIN analytics.sessions s ON s.user_id = u.user_id "
        "JOIN analytics.subscriptions x ON x.user_id = u.user_id "
        "JOIN analytics.experiments y ON y.experiment_id = x.user_id",
    ]
    safe = [
        "SELECT user_id, event_name FROM analytics.events LIMIT 10",
        "SELECT acquisition_channel, COUNT(*) AS users FROM analytics.users GROUP BY 1",
        "SELECT AVG(checkout_conversion_rate) AS rate FROM analytics.daily_metrics",
        "WITH daily AS (SELECT metric_date, registered_users FROM analytics.daily_metrics) "
        "SELECT SUM(registered_users) FROM daily",
    ]
    unsafe_results = [validate_sql(sql).valid is False for sql in unsafe]
    safe_results = [validate_sql(sql).valid is True for sql in safe]
    total = len(unsafe_results) + len(safe_results)
    passed = sum(unsafe_results) + sum(safe_results)
    return {
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total, 4) if total else None,
        "unsafe_rejected": f"{sum(unsafe_results)}/{len(unsafe)}",
        "safe_accepted": f"{sum(safe_results)}/{len(safe)}",
    }


def run(output: Path | None = None) -> dict:
    settings = get_settings()
    ref = RawReference(settings.data_start_date, settings.data_end_date)
    orchestrator = Orchestrator()
    cases = [*_copilot_cases(), *_sql_cases()]
    results = []
    for case in cases:
        results.append(
            _run_copilot(case, orchestrator, ref)
            if case.kind == "copilot"
            else _run_sql(case, ref)
        )

    copilot = [row for row in results if row["kind"] == "copilot"]
    sql = [row for row in results if row["kind"] == "sql"]
    latencies = sorted(row["latency_ms"] for row in results)
    tool_calls = sum(row["tool_calls"] for row in copilot)
    tool_successes = sum(row["tool_successes"] for row in copilot)
    summary = {
        "cases": len(results),
        "passed": sum(1 for row in results if row["passed"]),
        "accuracy": round(sum(1 for row in results if row["passed"]) / len(results), 4),
        "copilot_cases": len(copilot),
        "copilot_passed": sum(1 for row in copilot if row["passed"]),
        "copilot_accuracy": round(sum(1 for row in copilot if row["passed"]) / len(copilot), 4),
        "sql_cases": len(sql),
        "sql_passed": sum(1 for row in sql if row["passed"]),
        "sql_accuracy": round(sum(1 for row in sql if row["passed"]) / len(sql), 4),
        "tool_calls": tool_calls,
        "tool_success_rate": round(tool_successes / tool_calls, 4) if tool_calls else None,
        "citation_coverage": round(
            sum(1 for row in copilot if row["citations"]) / len(copilot), 4
        ),
        "median_latency_ms": statistics.median(latencies),
        "p95_latency_ms": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))],
        "sql_safety": _sql_safety(),
    }
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": {
            "seed": settings.data_seed,
            "start": settings.data_start_date.isoformat(),
            "end": settings.data_end_date.isoformat(),
        },
        "reference_counts": {
            "users": int(len(ref.users)),
            "events": int(len(ref.events)),
            "sessions": int(len(ref.sessions)),
            "subscriptions": int(len(ref.subscriptions)),
            "assignments": int(len(ref.assignments)),
        },
        "summary": summary,
        "cases": results,
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Copilot/Text-to-SQL evaluation")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation/results.json"),
        help="Where to write the JSON report",
    )
    args = parser.parse_args()
    report = run(args.output)
    print(json.dumps(report["summary"], indent=2))
    print(f"report written to {args.output}")


if __name__ == "__main__":
    main()
