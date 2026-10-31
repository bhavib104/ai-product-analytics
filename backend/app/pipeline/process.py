"""Raw ingestion, validation, cleaning and analytical mart construction.

The pipeline is deliberately single-writer: it rebuilds the DuckDB schemas
from the raw CSV layer, then derives every mart the API reads.  API requests
never write to DuckDB.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from app.analytics import stats
from app.analytics.anomalies import detect_anomalies
from app.analytics.definitions import METRIC_DEFINITIONS
from app.core.config import Settings, get_settings
from app.db import app_db
from app.db.duck import connect_readwrite
from app.pipeline.generate import SyntheticGenerator

logger = logging.getLogger(__name__)

RAW_TABLES = [
    "users",
    "events",
    "sessions",
    "subscriptions",
    "experiments",
    "experiment_assignments",
    "products",
    "features",
    "acquisition_channels",
]
SCHEMAS = ["raw", "staging", "analytics", "quarantine"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _read_raw(raw_dir: Path, name: str) -> pd.DataFrame:
    path = raw_dir / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing raw file: {path}")
    return pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False)


def _write_table(conn, df: pd.DataFrame, schema: str, table: str) -> None:
    df = df.reset_index(drop=True).copy()
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].where(pd.notna(df[col]), None)
    tmp = f"_tmp_{schema}_{table}_{uuid.uuid4().hex[:8]}"
    conn.register(tmp, df)
    try:
        conn.execute(f'CREATE OR REPLACE TABLE "{schema}"."{table}" AS SELECT * FROM "{tmp}"')
    finally:
        conn.unregister(tmp)


def _write_quarantine(raw_dir: Path, name: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    path = raw_dir.parent / "quarantine" / f"{name}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _parse_utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce").dt.tz_localize(None)


def _issue(issues: list[dict], table: str, issue_type: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    issues.append(
        {
            "table_name": table,
            "issue_type": issue_type,
            "row_count": int(len(df)),
            "sample": df.head(3).to_dict(orient="records"),
        }
    )


def _clean_users(raw: pd.DataFrame, issues: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = raw.copy()
    for col in ["user_id", "registration_date", "country", "device_type", "acquisition_channel"]:
        if col not in df:
            df[col] = ""
        df[col] = df[col].astype(str).str.strip()
    df["registration_date"] = pd.to_datetime(df["registration_date"], errors="coerce").dt.date
    invalid = df[df["user_id"].eq("") | df["registration_date"].isna()].copy()
    invalid["rejection_reason"] = "missing or invalid user_id/registration_date"
    _issue(issues, "users", "invalid_required_fields", invalid)
    df = df.drop(invalid.index)

    dup = df[df.duplicated("user_id", keep="first")].copy()
    dup["rejection_reason"] = "duplicate user_id"
    _issue(issues, "users", "duplicate_user_id", dup)
    df = df.drop(dup.index)

    for col, fill in {
        "country": "unknown",
        "device_type": "unknown",
        "acquisition_channel": "unknown",
        "subscription_type": "free",
        "user_status": "unknown",
    }.items():
        if col not in df:
            df[col] = fill
        df[col] = df[col].replace("", fill).fillna(fill)
    df = df[df["user_id"].ne("")]
    return df, pd.concat([invalid, dup], ignore_index=True)


def _clean_events(
    raw: pd.DataFrame, users: pd.DataFrame, issues: list[dict], start: date, end: date
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = raw.copy()
    for col in ["event_id", "user_id", "event_name", "event_timestamp", "session_id", "device", "properties"]:
        if col not in df:
            df[col] = ""
        df[col] = df[col].astype(str)
    df["event_timestamp"] = _parse_utc(df["event_timestamp"])
    invalid = df[
        df["event_id"].str.strip().eq("")
        | df["user_id"].str.strip().eq("")
        | df["event_name"].str.strip().eq("")
        | df["event_timestamp"].isna()
    ].copy()
    invalid["rejection_reason"] = "missing or invalid required event fields"
    _issue(issues, "events", "invalid_required_fields", invalid)
    df = df.drop(invalid.index)

    out_of_range = df[
        (df["event_timestamp"].dt.date < start - timedelta(days=1))
        | (df["event_timestamp"].dt.date > end + timedelta(days=1))
    ].copy()
    out_of_range["rejection_reason"] = "event timestamp outside data window"
    _issue(issues, "events", "timestamp_out_of_range", out_of_range)
    df = df.drop(out_of_range.index)

    valid_users = users[["user_id", "registration_date"]].copy()
    df = df.merge(valid_users, on="user_id", how="left", indicator=True)
    orphan = df[df["_merge"] == "left_only"].copy()
    orphan["rejection_reason"] = "orphan user_id"
    _issue(issues, "events", "orphan_user_id", orphan)
    df = df[df["_merge"] == "both"].drop(columns=["_merge"])

    pre = df[df["event_timestamp"].dt.date < df["registration_date"]].copy()
    pre["rejection_reason"] = "event precedes user registration"
    _issue(issues, "events", "event_before_registration", pre)
    df = df.drop(pre.index)

    dup = df[df.duplicated("event_id", keep="first")].copy()
    dup["rejection_reason"] = "duplicate event_id"
    _issue(issues, "events", "duplicate_event_id", dup)
    df = df.drop(dup.index)

    df["device"] = df["device"].replace("", "unknown").fillna("unknown")
    df["event_date"] = df["event_timestamp"].dt.date
    df["session_id"] = df["session_id"].replace("", None)

    def parse_props(value: str) -> tuple[str | None, str | None]:
        try:
            parsed = json.loads(value) if value else {}
            if not isinstance(parsed, dict):
                return None, None
            feature = parsed.get("feature_key")
            plan = parsed.get("plan")
            return (str(feature) if feature else None, str(plan) if plan else None)
        except (ValueError, TypeError):
            return None, None

    parsed = df["properties"].map(parse_props)
    df["feature_key"] = [p[0] for p in parsed]
    df["plan"] = [p[1] for p in parsed]
    clean = df[
        [
            "event_id",
            "user_id",
            "event_name",
            "event_timestamp",
            "event_date",
            "session_id",
            "device",
            "feature_key",
            "plan",
        ]
    ].copy()
    rejected = pd.concat([invalid, out_of_range, orphan, pre, dup], ignore_index=True)
    return clean, rejected


def _clean_sessions(raw: pd.DataFrame, users: pd.DataFrame, issues: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = raw.copy()
    for col in ["session_id", "user_id", "start_time", "end_time", "duration_seconds", "event_count", "device"]:
        if col not in df:
            df[col] = ""
        df[col] = df[col].astype(str)
    df["start_time"] = _parse_utc(df["start_time"])
    df["end_time"] = _parse_utc(df["end_time"])
    invalid = df[
        df["session_id"].str.strip().eq("")
        | df["user_id"].str.strip().eq("")
        | df["start_time"].isna()
    ].copy()
    invalid["rejection_reason"] = "missing or invalid session fields"
    _issue(issues, "sessions", "invalid_required_fields", invalid)
    df = df.drop(invalid.index)
    dup = df[df.duplicated("session_id", keep="first")].copy()
    dup["rejection_reason"] = "duplicate session_id"
    _issue(issues, "sessions", "duplicate_session_id", dup)
    df = df.drop(dup.index)
    orphan = df[~df["user_id"].isin(users["user_id"])].copy()
    orphan["rejection_reason"] = "orphan user_id"
    _issue(issues, "sessions", "orphan_user_id", orphan)
    df = df.drop(orphan.index)
    df["duration_seconds"] = pd.to_numeric(df["duration_seconds"], errors="coerce").fillna(0)
    negative = df[df["duration_seconds"] <= 0].copy()
    negative["rejection_reason"] = "non-positive duration"
    _issue(issues, "sessions", "invalid_duration", negative)
    df.loc[df["duration_seconds"] <= 0, "duration_seconds"] = 0
    df["event_count"] = pd.to_numeric(df["event_count"], errors="coerce").fillna(0).astype(int)
    df["device"] = df["device"].replace("", "unknown").fillna("unknown")
    clean = df[["session_id", "user_id", "start_time", "end_time", "duration_seconds", "event_count", "device"]]
    return clean, pd.concat([invalid, dup, orphan, negative], ignore_index=True)


def _clean_subscriptions(
    raw: pd.DataFrame, users: pd.DataFrame, issues: list[dict]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = raw.copy()
    for col in [
        "subscription_id", "user_id", "plan", "billing_cycle", "start_date",
        "renewal_date", "status", "mrr_cents", "total_revenue_cents", "cancelled_date",
    ]:
        if col not in df:
            df[col] = ""
        df[col] = df[col].astype(str)
    df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce").dt.date
    df["renewal_date"] = pd.to_datetime(df["renewal_date"], errors="coerce").dt.date
    df["cancelled_date"] = pd.to_datetime(df["cancelled_date"], errors="coerce").dt.date
    invalid = df[
        df["subscription_id"].str.strip().eq("")
        | df["user_id"].str.strip().eq("")
        | df["plan"].str.strip().eq("")
        | df["start_date"].isna()
    ].copy()
    invalid["rejection_reason"] = "missing or invalid subscription fields"
    _issue(issues, "subscriptions", "invalid_required_fields", invalid)
    df = df.drop(invalid.index)
    dup = df[df.duplicated("subscription_id", keep="first")].copy()
    dup["rejection_reason"] = "duplicate subscription_id"
    _issue(issues, "subscriptions", "duplicate_subscription_id", dup)
    df = df.drop(dup.index)
    orphan = df[~df["user_id"].isin(users["user_id"])].copy()
    orphan["rejection_reason"] = "orphan user_id"
    _issue(issues, "subscriptions", "orphan_user_id", orphan)
    df = df.drop(orphan.index)
    bad_renewal = df[df["renewal_date"].notna() & (df["renewal_date"] < df["start_date"])].copy()
    bad_renewal["rejection_reason"] = "renewal before start"
    _issue(issues, "subscriptions", "renewal_before_start", bad_renewal)
    df.loc[df["renewal_date"].notna() & (df["renewal_date"] < df["start_date"]), "renewal_date"] = df["start_date"]
    df["status"] = df["status"].replace("", "unknown").fillna("unknown")
    df["mrr_cents"] = pd.to_numeric(df["mrr_cents"], errors="coerce").fillna(0)
    df["total_revenue_cents"] = pd.to_numeric(df["total_revenue_cents"], errors="coerce").fillna(0)
    df["mrr"] = (df["mrr_cents"] / 100.0).round(2)
    df["total_revenue"] = (df["total_revenue_cents"] / 100.0).round(2)
    df["cancelled_date"] = df["cancelled_date"].where(df["cancelled_date"].notna(), None)
    clean = df[
        [
            "subscription_id", "user_id", "plan", "billing_cycle", "start_date",
            "renewal_date", "status", "mrr", "total_revenue", "cancelled_date",
        ]
    ]
    return clean, pd.concat([invalid, dup, orphan, bad_renewal], ignore_index=True)


def _clean_assignments(
    raw: pd.DataFrame, users: pd.DataFrame, issues: list[dict]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = raw.copy()
    for col in ["assignment_id", "experiment_id", "user_id", "variant", "assigned_at"]:
        if col not in df:
            df[col] = ""
        df[col] = df[col].astype(str)
    df["assigned_at"] = _parse_utc(df["assigned_at"])
    invalid = df[
        df["assignment_id"].str.strip().eq("")
        | df["experiment_id"].str.strip().eq("")
        | df["user_id"].str.strip().eq("")
        | df["assigned_at"].isna()
        | ~df["variant"].isin(["control", "treatment"])
    ].copy()
    invalid["rejection_reason"] = "missing/invalid assignment fields or variant"
    _issue(issues, "experiment_assignments", "invalid_required_fields", invalid)
    df = df.drop(invalid.index)
    dup = df[df.duplicated("assignment_id", keep="first")].copy()
    dup["rejection_reason"] = "duplicate assignment_id"
    _issue(issues, "experiment_assignments", "duplicate_assignment_id", dup)
    df = df.drop(dup.index)
    dup_user = df[df.duplicated(["experiment_id", "user_id"], keep="first")].copy()
    dup_user["rejection_reason"] = "user assigned twice to same experiment"
    _issue(issues, "experiment_assignments", "duplicate_user_assignment", dup_user)
    df = df.drop(dup_user.index)
    orphan = df[~df["user_id"].isin(users["user_id"])].copy()
    orphan["rejection_reason"] = "orphan user_id"
    _issue(issues, "experiment_assignments", "orphan_user_id", orphan)
    df = df.drop(orphan.index)
    clean = df[["assignment_id", "experiment_id", "user_id", "variant", "assigned_at"]]
    return clean, pd.concat([invalid, dup, dup_user, orphan], ignore_index=True)


def _clean_dimension(raw: pd.DataFrame, key: str) -> pd.DataFrame:
    df = raw.copy()
    if key not in df:
        df[key] = ""
    df[key] = df[key].astype(str).str.strip()
    return df[df[key].ne("")].drop_duplicates(key, keep="first")


# ---------------------------------------------------------------------------
# Marts
# ---------------------------------------------------------------------------
def _build_user_metrics(conn, data_end: date) -> None:
    end = data_end.isoformat()
    conn.execute(
        f"""
        CREATE OR REPLACE TABLE analytics.user_metrics AS
        WITH ev AS (
            SELECT
                user_id,
                MIN(event_timestamp) AS first_event_at,
                MAX(event_timestamp) AS last_event_at,
                COUNT(DISTINCT event_date) AS active_days,
                COUNT(DISTINCT session_id) AS sessions_total,
                COUNT(*) AS events_total,
                COUNT(DISTINCT CASE WHEN event_date > DATE '{end}' - INTERVAL 30 DAY
                    THEN session_id END) AS sessions_30d,
                COUNT(CASE WHEN event_date > DATE '{end}' - INTERVAL 30 DAY THEN 1 END) AS events_30d,
                COUNT(DISTINCT CASE WHEN event_date > DATE '{end}' - INTERVAL 30 DAY
                    THEN feature_key END) AS feature_breadth_30d,
                MIN(CASE WHEN event_name = 'account_activated' THEN event_timestamp END) AS activation_date,
                MIN(CASE WHEN event_name = 'feature_used' THEN event_timestamp END) AS first_feature_date,
                MIN(CASE WHEN event_name = 'purchase_completed' THEN event_timestamp END) AS first_purchase_date
            FROM staging.events
            GROUP BY user_id
        ),
        sub AS (
            SELECT
                user_id,
                SUM(CASE WHEN status = 'active' THEN mrr ELSE 0 END) AS mrr,
                SUM(total_revenue) AS lifetime_revenue,
                BOOL_OR(status = 'active') AS active_subscription
            FROM staging.subscriptions
            GROUP BY user_id
        )
        SELECT
            u.user_id,
            u.registration_date,
            ev.first_event_at,
            ev.last_event_at,
            ev.activation_date,
            ev.first_feature_date,
            ev.first_purchase_date,
            COALESCE(ev.active_days, 0) AS active_days,
            COALESCE(ev.sessions_total, 0) AS sessions_total,
            COALESCE(ev.events_total, 0) AS events_total,
            COALESCE(ev.sessions_30d, 0) AS sessions_30d,
            COALESCE(ev.events_30d, 0) AS events_30d,
            COALESCE(ev.feature_breadth_30d, 0) AS feature_breadth_30d,
            ROUND(COALESCE(sub.lifetime_revenue, 0), 2) AS lifetime_revenue,
            ROUND(COALESCE(sub.mrr, 0), 2) AS mrr,
            COALESCE(sub.active_subscription, FALSE) AS active_subscription,
            COALESCE(DATE_DIFF('day', CAST(ev.last_event_at AS DATE), DATE '{end}'), 9999) AS recency_days,
            DATE_DIFF('day', u.registration_date, DATE '{end}') AS tenure_days,
            (ev.activation_date IS NOT NULL) AS is_activated,
            (ev.first_purchase_date IS NOT NULL) AS is_purchased
        FROM staging.users u
        LEFT JOIN ev ON u.user_id = ev.user_id
        LEFT JOIN sub ON u.user_id = sub.user_id
        """
    )


def _build_daily_metrics(conn, settings: Settings) -> None:
    start, end = settings.data_start_date, settings.data_end_date
    users = conn.execute("SELECT * FROM analytics.users").fetch_df()
    events = conn.execute(
        "SELECT user_id, event_name, event_timestamp, event_date, session_id, feature_key "
        "FROM analytics.events"
    ).fetch_df()
    sessions = conn.execute(
        "SELECT user_id, session_start, duration_seconds FROM analytics.sessions"
    ).fetch_df()
    subs = conn.execute(
        "SELECT user_id, plan, mrr, start_date, cancelled_date, status FROM analytics.subscriptions"
    ).fetch_df()

    for df, cols in [
        (users, ["registration_date"]),
        (events, ["event_date"]),
        (subs, ["start_date", "cancelled_date"]),
    ]:
        for col in cols:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    sessions["session_date"] = pd.to_datetime(sessions["session_start"], errors="coerce").dt.date
    events["event_timestamp"] = pd.to_datetime(events["event_timestamp"], errors="coerce")

    dates = pd.date_range(start, end, freq="D").date
    frame = pd.DataFrame({"metric_date": dates})

    def merge_count(metric: str, series: pd.Series) -> None:
        nonlocal frame
        frame = frame.merge(
            series.rename(metric).rename_axis("metric_date").reset_index(),
            on="metric_date",
            how="left",
        )

    merge_count("registered_users", users.groupby("registration_date").size())
    merge_count(
        "activated_users",
        events[events["event_name"] == "account_activated"].groupby("event_date")["user_id"].nunique(),
    )
    merge_count(
        "purchasing_users",
        events[events["event_name"] == "purchase_completed"].groupby("event_date")["user_id"].nunique(),
    )
    merge_count("dau", events.groupby("event_date")["user_id"].nunique())
    merge_count("events", events.groupby("event_date").size())
    merge_count("sessions", sessions.groupby("session_date").size())

    # Cohort-based activation and purchase conversion (avoids rates above 100%).
    first_activation = (
        events[events["event_name"] == "account_activated"]
        .groupby("user_id")["event_timestamp"].min()
    )
    first_purchase = (
        events[events["event_name"] == "purchase_completed"]
        .groupby("user_id")["event_timestamp"].min()
    )
    cohort = users[["user_id", "registration_date"]].copy()
    cohort["activation_ts"] = cohort["user_id"].map(first_activation)
    cohort["purchase_ts"] = cohort["user_id"].map(first_purchase)
    reg_ts = pd.to_datetime(cohort["registration_date"])
    cohort["cohort_activated_users"] = (
        cohort["activation_ts"].notna()
        & (cohort["activation_ts"] <= reg_ts + pd.Timedelta(days=7))
    ).astype(int)
    cohort["cohort_purchasing_users"] = (
        cohort["purchase_ts"].notna()
        & (cohort["purchase_ts"] <= reg_ts + pd.Timedelta(days=30))
    ).astype(int)
    cohort_daily = cohort.groupby("registration_date")[
        ["cohort_activated_users", "cohort_purchasing_users"]
    ].sum()
    merge_count("cohort_activated_users", cohort_daily["cohort_activated_users"])
    merge_count("cohort_purchasing_users", cohort_daily["cohort_purchasing_users"])

    # Checkout-cohort conversion: purchases within 7 days of a checkout.
    checkout_events = events[events["event_name"] == "checkout_started"][
        ["user_id", "event_timestamp", "event_date"]
    ].copy()
    purchase_events = events[events["event_name"] == "purchase_completed"][
        ["user_id", "event_timestamp"]
    ].copy()
    purchases_by_user = purchase_events.groupby("user_id")["event_timestamp"].apply(list).to_dict()

    def converted(row) -> bool:
        for ts in purchases_by_user.get(row["user_id"], []):
            if row["event_timestamp"] <= ts <= row["event_timestamp"] + pd.Timedelta(days=7):
                return True
        return False

    checkout_events["converted"] = checkout_events.apply(converted, axis=1)
    checkout_daily = checkout_events.groupby("event_date").agg(
        checkouts=("user_id", "size"), checkout_conversions=("converted", "sum")
    )
    merge_count("checkouts", checkout_daily["checkouts"])
    merge_count("checkout_conversions", checkout_daily["checkout_conversions"])

    merge_count(
        "purchases",
        events[events["event_name"] == "purchase_completed"].groupby("event_date").size(),
    )
    merge_count(
        "cancellations",
        subs.dropna(subset=["cancelled_date"]).groupby("cancelled_date").size(),
    )
    avg_duration = sessions.groupby("session_date")["duration_seconds"].mean()
    merge_count("avg_session_duration_seconds", avg_duration)

    # Daily feature adoption.
    feature_events = events[events["event_name"] == "feature_used"].dropna(subset=["feature_key"])
    feature_daily = (
        feature_events.groupby(["event_date", "feature_key"])["user_id"]
        .nunique()
        .reset_index(name="users")
    )
    features = conn.execute("SELECT feature_key, feature_name FROM analytics.features").fetch_df()
    feature_daily = feature_daily.merge(features, on="feature_key", how="left")
    feature_daily["feature_name"] = feature_daily["feature_name"].fillna(feature_daily["feature_key"])
    dau_map = frame.set_index("metric_date")["dau"]
    feature_daily["adoption_rate"] = feature_daily.apply(
        lambda r: (r["users"] / dau_map.get(r["event_date"], 0)) if dau_map.get(r["event_date"], 0) else 0.0,
        axis=1,
    )
    _write_table(conn, feature_daily.rename(columns={"event_date": "metric_date"}), "analytics", "feature_adoption_daily")

    feature_users = feature_events.groupby("event_date")["user_id"].nunique()
    merge_count("feature_users", feature_users)

    frame = frame.fillna(0)
    for col in [
        "registered_users", "activated_users", "purchasing_users", "dau", "events",
        "sessions", "checkouts", "checkout_conversions", "purchases", "cancellations",
        "feature_users", "cohort_activated_users", "cohort_purchasing_users",
    ]:
        frame[col] = frame[col].astype(int)
    frame["avg_session_duration_seconds"] = frame["avg_session_duration_seconds"].round(2)

    # Rolling WAU/MAU and DAU/MAU.
    frame = frame.set_index("metric_date")
    frame["wau"] = frame["dau"].rolling(7, min_periods=1).apply(lambda s: s.max()).astype(int)
    # Rolling distinct users cannot be recovered from daily DAU sums; compute exactly.
    active_by_date = events.groupby("event_date")["user_id"].apply(set)
    wau, mau = [], []
    for d in frame.index:
        w7 = set().union(*[active_by_date.get(d - timedelta(days=i), set()) for i in range(7)])
        w30 = set().union(*[active_by_date.get(d - timedelta(days=i), set()) for i in range(30)])
        wau.append(len(w7))
        mau.append(len(w30))
    frame["wau"] = wau
    frame["mau"] = mau
    frame["dau_mau_ratio"] = (frame["dau"] / frame["mau"].replace(0, np.nan)).fillna(0).round(4)
    frame["activation_rate"] = (
        frame["cohort_activated_users"] / frame["registered_users"].replace(0, np.nan)
    ).fillna(0).round(4)
    frame["purchase_conversion_rate"] = (
        frame["cohort_purchasing_users"] / frame["registered_users"].replace(0, np.nan)
    ).fillna(0).round(4)
    frame["checkout_conversion_rate"] = (
        frame["checkout_conversions"] / frame["checkouts"].replace(0, np.nan)
    ).fillna(0).round(4)
    frame["feature_adoption_rate"] = (
        frame["feature_users"] / frame["dau"].replace(0, np.nan)
    ).fillna(0).round(4)

    # MRR snapshot by date.
    mrr = []
    for d in frame.index:
        total = 0.0
        for _, sub in subs.iterrows():
            if pd.isna(sub["start_date"]) or sub["start_date"] > d:
                continue
            if pd.notna(sub["cancelled_date"]) and sub["cancelled_date"] <= d:
                continue
            total += float(sub["mrr"] or 0)
        mrr.append(round(total, 2))
    frame["mrr"] = mrr

    frame = frame.reset_index()
    frame = frame.drop(columns=["feature_users"])
    _write_table(conn, frame, "analytics", "daily_metrics")


def _build_weekly_metrics(conn) -> None:
    daily = conn.execute("SELECT * FROM analytics.daily_metrics").fetch_df()
    daily["metric_date"] = pd.to_datetime(daily["metric_date"])
    daily["week_start"] = daily["metric_date"] - pd.to_timedelta(daily["metric_date"].dt.weekday, unit="D")
    daily["week_start"] = daily["week_start"].dt.date
    grouped = daily.groupby("week_start").agg(
        registered_users=("registered_users", "sum"),
        activated_users=("activated_users", "sum"),
        purchasing_users=("purchasing_users", "sum"),
        cohort_activated_users=("cohort_activated_users", "sum"),
        cohort_purchasing_users=("cohort_purchasing_users", "sum"),
        checkouts=("checkouts", "sum"),
        checkout_conversions=("checkout_conversions", "sum"),
        purchases=("purchases", "sum"),
        sessions=("sessions", "sum"),
        events=("events", "sum"),
        cancellations=("cancellations", "sum"),
        dau_avg=("dau", "mean"),
        mau_avg=("mau", "mean"),
        mrr_end=("mrr", "last"),
    ).reset_index()
    grouped["checkout_conversion_rate"] = (
        grouped["checkout_conversions"] / grouped["checkouts"].replace(0, np.nan)
    ).fillna(0).round(4)
    grouped["purchase_conversion_rate"] = (
        grouped["cohort_purchasing_users"] / grouped["registered_users"].replace(0, np.nan)
    ).fillna(0).round(4)
    grouped["activation_rate"] = (
        grouped["cohort_activated_users"] / grouped["registered_users"].replace(0, np.nan)
    ).fillna(0).round(4)
    grouped["dau_avg"] = grouped["dau_avg"].round(1)
    grouped["mau_avg"] = grouped["mau_avg"].round(1)
    _write_table(conn, grouped, "analytics", "weekly_metrics")


def _build_user_segments(conn, settings: Settings) -> None:
    df = conn.execute("SELECT * FROM analytics.user_metrics").fetch_df()
    df = df.fillna({"mrr": 0, "lifetime_revenue": 0, "recency_days": 9999})
    df["mrr"] = df["mrr"].astype(float)
    df["lifetime_revenue"] = df["lifetime_revenue"].astype(float)
    df["recency_days"] = df["recency_days"].astype(int)
    df["sessions_30d"] = df["sessions_30d"].astype(int)
    df["events_30d"] = df["events_30d"].astype(int)
    df["feature_breadth_30d"] = df["feature_breadth_30d"].astype(int)
    df["tenure_days"] = df["tenure_days"].astype(int)

    def rule(row) -> str:
        if row["mrr"] >= 50 and row["sessions_30d"] >= 8 and row["recency_days"] <= 14:
            return "champions"
        if row["sessions_30d"] >= 10 and row["recency_days"] <= 7:
            return "power_users"
        if row["tenure_days"] <= 30 and row["sessions_30d"] >= 3:
            return "new_engaged"
        if row["tenure_days"] > 30 and 14 <= row["recency_days"] <= 45 and row["lifetime_revenue"] > 0:
            return "at_risk"
        if row["recency_days"] > 45:
            return "dormant"
        if row["recency_days"] <= 14 and row["mrr"] == 0:
            return "active_free"
        if row["recency_days"] <= 45 and row["sessions_30d"] <= 2:
            return "low_engagement"
        return "other"

    df["segment"] = df.apply(rule, axis=1)
    df["cluster_id"] = -1
    df["cluster_label"] = "Not clustered"
    if len(df) >= 50:
        feature_cols = ["sessions_30d", "events_30d", "feature_breadth_30d", "mrr", "lifetime_revenue", "recency_days"]
        matrix = df[feature_cols].copy()
        for col in ["sessions_30d", "events_30d", "mrr", "lifetime_revenue"]:
            matrix[col] = np.log1p(matrix[col].clip(lower=0))
        scaled = StandardScaler().fit_transform(matrix)
        k = min(4, max(2, len(df) // 100))
        model = KMeans(n_clusters=k, random_state=settings.data_seed, n_init=10)
        labels = model.fit_predict(scaled)
        df["cluster_id"] = labels
        centres = pd.DataFrame(model.cluster_centers_, columns=feature_cols)
        centres["score"] = (
            centres["sessions_30d"] + centres["events_30d"] + centres["feature_breadth_30d"]
            - centres["recency_days"]
        )
        ordered = centres.sort_values("score", ascending=False).index.tolist()
        names = ["High engagement", "Steady engagement", "Low engagement", "Dormant"]
        mapping = {cluster: names[i] if i < len(names) else f"Cluster {cluster}" for i, cluster in enumerate(ordered)}
        df["cluster_label"] = df["cluster_id"].map(mapping)
    df["computed_at"] = datetime.now(UTC).replace(tzinfo=None)
    out = df[
        [
            "user_id", "segment", "cluster_id", "cluster_label", "recency_days",
            "sessions_30d", "events_30d", "feature_breadth_30d", "mrr",
            "lifetime_revenue", "computed_at",
        ]
    ].copy()
    out["cluster_id"] = out["cluster_id"].astype("Int64")
    _write_table(conn, out, "analytics", "user_segments")


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def _build_cohorts(conn, settings: Settings) -> None:
    users = conn.execute("SELECT user_id, registration_date FROM analytics.users").fetch_df()
    events = conn.execute("SELECT user_id, event_date FROM analytics.events").fetch_df()
    users["registration_date"] = pd.to_datetime(users["registration_date"]).dt.date
    events["event_date"] = pd.to_datetime(events["event_date"]).dt.date
    active = events.groupby("user_id")["event_date"].apply(set).to_dict()
    user_rows = users.to_dict(orient="records")
    end = settings.data_end_date

    rows: list[dict] = []
    # Daily cohorts.
    by_day: dict[date, list[str]] = {}
    for u in user_rows:
        by_day.setdefault(u["registration_date"], []).append(u["user_id"])
    for cohort_date, members in sorted(by_day.items()):
        for n in range(0, 31):
            target = cohort_date + timedelta(days=n)
            retained = sum(1 for uid in members if target in active.get(uid, set()))
            rows.append(
                {
                    "cohort_type": "daily",
                    "cohort_date": cohort_date,
                    "period_index": n,
                    "cohort_size": len(members),
                    "retained_users": retained,
                    "retention_rate": round(retained / len(members), 6) if members else 0,
                    "is_complete": target <= end,
                }
            )
    # Weekly cohorts.
    by_week: dict[date, list[str]] = {}
    for u in user_rows:
        monday = u["registration_date"] - timedelta(days=u["registration_date"].weekday())
        by_week.setdefault(monday, []).append(u["user_id"])
    for cohort_week, members in sorted(by_week.items()):
        for n in range(0, 9):
            target = cohort_week + timedelta(days=7 * n)
            retained = sum(
                1 for uid in members
                if any(target + timedelta(days=i) in active.get(uid, set()) for i in range(7))
            )
            rows.append(
                {
                    "cohort_type": "weekly",
                    "cohort_date": cohort_week,
                    "period_index": n,
                    "cohort_size": len(members),
                    "retained_users": retained,
                    "retention_rate": round(retained / len(members), 6) if members else 0,
                    "is_complete": target + timedelta(days=6) <= end,
                }
            )
    # Monthly cohorts.
    by_month: dict[date, list[str]] = {}
    for u in user_rows:
        first = u["registration_date"].replace(day=1)
        by_month.setdefault(first, []).append(u["user_id"])
    for cohort_month, members in sorted(by_month.items()):
        for n in range(0, 7):
            target = _add_months(cohort_month, n)
            month_end = _add_months(target, 1) - timedelta(days=1)
            retained = sum(
                1 for uid in members
                if any(target + timedelta(days=i) in active.get(uid, set()) for i in range((month_end - target).days + 1))
            )
            rows.append(
                {
                    "cohort_type": "monthly",
                    "cohort_date": cohort_month,
                    "period_index": n,
                    "cohort_size": len(members),
                    "retained_users": retained,
                    "retention_rate": round(retained / len(members), 6) if members else 0,
                    "is_complete": month_end <= end,
                }
            )
    _write_table(conn, pd.DataFrame(rows), "analytics", "cohort_retention")

    # Day-N retention by dimension.
    users_full = conn.execute(
        "SELECT u.user_id, u.registration_date, u.acquisition_channel, u.device_type, u.country, "
        "u.subscription_type, s.segment FROM analytics.users u "
        "LEFT JOIN analytics.user_segments s ON u.user_id = s.user_id"
    ).fetch_df()
    users_full["registration_date"] = pd.to_datetime(users_full["registration_date"]).dt.date
    dims = {
        "channel": "acquisition_channel",
        "device": "device_type",
        "country": "country",
        "plan": "subscription_type",
        "segment": "segment",
    }
    dim_rows: list[dict] = []
    for dim_type, col in dims.items():
        for (cohort_date, value), group in users_full.groupby(["registration_date", col], dropna=False):
            value = str(value) if value is not None else "unknown"
            members = group["user_id"].tolist()
            for period in (1, 7, 14, 30):
                target = cohort_date + timedelta(days=period)
                retained = sum(1 for uid in members if target in active.get(uid, set()))
                dim_rows.append(
                    {
                        "cohort_date": cohort_date,
                        "period_days": period,
                        "dimension_type": dim_type,
                        "dimension_value": value,
                        "cohort_size": len(members),
                        "retained_users": retained,
                        "retention_rate": round(retained / len(members), 6) if members else 0,
                    }
                )
    _write_table(conn, pd.DataFrame(dim_rows), "analytics", "retention_by_dimension")


def _build_experiments(conn) -> None:
    experiments = conn.execute("SELECT * FROM analytics.experiments").fetch_df()
    assignments = conn.execute("SELECT * FROM analytics.experiment_assignments").fetch_df()
    events = conn.execute(
        "SELECT user_id, event_name, event_timestamp FROM analytics.events"
    ).fetch_df()
    assignments["assigned_at"] = pd.to_datetime(assignments["assigned_at"])
    events["event_timestamp"] = pd.to_datetime(events["event_timestamp"])
    rows: list[dict] = []
    for _, experiment in experiments.iterrows():
        exp_id = experiment["experiment_id"]
        exp_assign = assignments[assignments["experiment_id"] == exp_id]
        if exp_assign.empty:
            continue
        for metric_key, event_name, window_days in [
            ("activation_7d", "account_activated", 7),
            ("purchase_14d", "purchase_completed", 14),
        ]:
            metric_events = events[events["event_name"] == event_name]
            merged = exp_assign.merge(metric_events, on="user_id", how="left")
            merged["in_window"] = (
                merged["event_timestamp"].notna()
                & (merged["event_timestamp"] >= merged["assigned_at"])
                & (merged["event_timestamp"] <= merged["assigned_at"] + pd.Timedelta(days=window_days))
            )
            successes = merged.groupby("variant")["in_window"].sum().to_dict()
            sizes = exp_assign.groupby("variant").size().to_dict()
            control_s = int(successes.get("control", 0))
            treat_s = int(successes.get("treatment", 0))
            control_n = int(sizes.get("control", 0))
            treat_n = int(sizes.get("treatment", 0))
            result = stats.two_proportion_test(control_s, control_n, treat_s, treat_n)
            for variant in ("control", "treatment"):
                s = control_s if variant == "control" else treat_s
                n = control_n if variant == "control" else treat_n
                rows.append(
                    {
                        "experiment_id": exp_id,
                        "metric_key": metric_key,
                        "variant": variant,
                        "successes": s,
                        "sample_size": n,
                        "rate": round(s / n, 6) if n else 0,
                        "absolute_lift": result["absolute_lift"] if variant == "treatment" else None,
                        "relative_lift": result["relative_lift"] if variant == "treatment" else None,
                        "ci_low": result["ci_low"] if variant == "treatment" else None,
                        "ci_high": result["ci_high"] if variant == "treatment" else None,
                        "p_value": result["p_value"] if variant == "treatment" else None,
                        "significant": bool(result.get("significant")) if variant == "treatment" else None,
                        "effect_size_json": json.dumps(result),
                        "computed_at": datetime.now(UTC).replace(tzinfo=None),
                    }
                )
    _write_table(conn, pd.DataFrame(rows), "analytics", "experiment_results")


def _build_metric_definitions(conn) -> None:
    rows = []
    for m in METRIC_DEFINITIONS:
        rows.append(
            {
                "metric_key": m["key"],
                "name": m["name"],
                "description": m["description"],
                "formula": m["formula"],
                "grain": m["grain"],
                "window": m["window"],
                "dimensions": json.dumps(m["dimensions"]),
                "version": "1.0",
            }
        )
    _write_table(conn, pd.DataFrame(rows), "analytics", "metric_definitions")


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------
def process(settings: Settings | None = None, run_id: str | None = None) -> dict:
    settings = settings or get_settings()
    settings.ensure_dirs()
    raw_dir = Path(settings.data_dir) / "raw"
    run_id = run_id or f"run_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:6]}"
    issues: list[dict] = []

    app_db.init_app_db()
    app_db.seed_funnel_definitions()
    app_db.start_ingestion_run(run_id, "synthetic_csv")

    raw_frames = {name: _read_raw(raw_dir, name) for name in RAW_TABLES}
    rows_read = int(sum(len(df) for df in raw_frames.values()))

    users, users_rej = _clean_users(raw_frames["users"], issues)
    events, events_rej = _clean_events(
        raw_frames["events"], users, issues, settings.data_start_date, settings.data_end_date
    )
    sessions, sessions_rej = _clean_sessions(raw_frames["sessions"], users, issues)
    subscriptions, subs_rej = _clean_subscriptions(raw_frames["subscriptions"], users, issues)
    assignments, assign_rej = _clean_assignments(
        raw_frames["experiment_assignments"], users, issues
    )
    features = _clean_dimension(raw_frames["features"], "feature_key")
    products = _clean_dimension(raw_frames["products"], "product_id")
    channels = _clean_dimension(raw_frames["acquisition_channels"], "channel_key")
    experiments = _clean_dimension(raw_frames["experiments"], "experiment_id")

    rejected = {
        "users": users_rej,
        "events": events_rej,
        "sessions": sessions_rej,
        "subscriptions": subs_rej,
        "experiment_assignments": assign_rej,
    }
    for name, df in rejected.items():
        _write_quarantine(raw_dir, name, df)

    clean_frames = {
        "users": users,
        "events": events,
        "sessions": sessions,
        "subscriptions": subscriptions,
        "experiment_assignments": assignments,
        "features": features,
        "products": products,
        "acquisition_channels": channels,
        "experiments": experiments,
    }

    conn = connect_readwrite()
    try:
        for schema in SCHEMAS:
            conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        for name, df in raw_frames.items():
            _write_table(conn, df, "raw", name)
        for name, df in clean_frames.items():
            _write_table(conn, df, "staging", name)
        for name, df in rejected.items():
            if not df.empty:
                _write_table(conn, df, "quarantine", name)

        for name in ["users", "events", "subscriptions", "experiments", "experiment_assignments", "features", "products", "acquisition_channels"]:
            conn.execute(
                f'CREATE OR REPLACE TABLE analytics."{name}" AS SELECT * FROM staging."{name}"'
            )
        conn.execute(
            """
            CREATE OR REPLACE TABLE analytics.sessions AS
            SELECT
                session_id,
                user_id,
                MIN(event_timestamp) AS session_start,
                MAX(event_timestamp) AS session_end,
                DATE_DIFF('second', MIN(event_timestamp), MAX(event_timestamp)) AS duration_seconds,
                COUNT(*) AS event_count,
                ANY_VALUE(device) AS device
            FROM staging.events
            WHERE session_id IS NOT NULL
            GROUP BY session_id, user_id
            """
        )
        _build_user_metrics(conn, settings.data_end_date)
        _build_daily_metrics(conn, settings)
        _build_weekly_metrics(conn)
        _build_user_segments(conn, settings)
        _build_cohorts(conn, settings)
        _build_experiments(conn)
        _build_metric_definitions(conn)

        daily = conn.execute("SELECT * FROM analytics.daily_metrics").fetch_df()
        weekly = conn.execute("SELECT * FROM analytics.weekly_metrics").fetch_df()
        anomalies = detect_anomalies(daily, weekly, settings.data_end_date)
        _write_table(conn, pd.DataFrame(anomalies), "analytics", "anomaly_events")

        manifest_path = Path(settings.data_dir) / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        summary = {
            "run_id": run_id,
            "rows_read": rows_read,
            "rows_valid": int(sum(len(df) for df in clean_frames.values())),
            "rows_rejected": int(sum(len(df) for df in rejected.values())),
            "tables": {},
            "issues": issues,
            "manifest": manifest,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        for table in [
            "users", "events", "sessions", "subscriptions", "experiment_assignments",
            "daily_metrics", "weekly_metrics", "feature_adoption_daily", "user_metrics",
            "cohort_retention", "retention_by_dimension", "user_segments", "experiment_results",
            "anomaly_events", "metric_definitions",
        ]:
            summary["tables"][table] = int(
                conn.execute(f'SELECT COUNT(*) FROM analytics."{table}"').fetchone()[0]
            )
        _write_table(
            conn,
            pd.DataFrame([{"manifest_json": json.dumps(summary, default=str), "created_at": datetime.now(UTC).replace(tzinfo=None)}]),
            "analytics",
            "pipeline_manifest",
        )
        conn.execute("CHECKPOINT")
    finally:
        conn.close()

    for issue in issues:
        app_db.insert_quality_issue(
            run_id, issue["table_name"], issue["issue_type"], issue["row_count"], issue["sample"]
        )
    app_db.finish_ingestion_run(run_id, "SUCCESS", summary)
    app_db.insert_audit("INGESTION_COMPLETED", summary)
    logger.info("Pipeline completed: %s", summary["tables"])
    return summary


def run_pipeline(settings: Settings | None = None, force_generate: bool = False) -> dict:
    settings = settings or get_settings()
    settings.ensure_dirs()
    raw_dir = Path(settings.data_dir) / "raw"
    if force_generate or not all((raw_dir / f"{name}.csv").exists() for name in RAW_TABLES):
        logger.info("Generating synthetic dataset...")
        SyntheticGenerator(settings).generate()
    return process(settings)


def rebuild_all(settings: Settings | None = None) -> dict:
    return run_pipeline(settings, force_generate=True)
