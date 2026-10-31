"""Ordered funnel analysis with bounded per-user windows."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd

from app.db.duck import query_df

GROUP_COLUMNS = {
    "channel": "acquisition_channel",
    "device": "device_type",
    "country": "country",
    "plan": "subscription_type",
    "segment": "segment",
}


def _load_events(stage_names: list[str], start: date, end: date, window_days: int) -> pd.DataFrame:
    placeholders = ",".join(["?"] * len(stage_names))
    sql = f"""
        SELECT e.user_id, e.event_name, e.event_timestamp, e.event_date,
               u.acquisition_channel, u.device_type, u.country, u.subscription_type,
               COALESCE(s.segment, 'unknown') AS segment
        FROM analytics.events e
        JOIN analytics.users u ON e.user_id = u.user_id
        LEFT JOIN analytics.user_segments s ON e.user_id = s.user_id
        WHERE e.event_name IN ({placeholders})
          AND e.event_date BETWEEN ? AND ?
    """
    params = [*stage_names, start.isoformat(), (end + timedelta(days=window_days)).isoformat()]
    df = query_df(sql, params)
    df["event_timestamp"] = pd.to_datetime(df["event_timestamp"])
    df["event_date"] = pd.to_datetime(df["event_date"]).dt.date
    return df


def _compute(
    events: pd.DataFrame,
    stages: list[dict],
    start: date,
    end: date,
    window_days: int,
    group_by: str | None,
) -> tuple[dict, list[dict]]:
    if events.empty:
        return (
            {
                "stages": [
                    {
                        **stage,
                        "users": 0,
                        "step_conversion": 0.0,
                        "from_start_conversion": 0.0,
                        "dropoff_users": 0,
                        "dropoff_rate": 0.0,
                    }
                    for stage in stages
                ],
                "cohort_users": 0,
            },
            [],
        )

    group_col = GROUP_COLUMNS.get(group_by, group_by) if group_by else None
    if group_col and group_col not in events.columns:
        group_col = None
    groups = events[group_col].fillna("unknown").astype(str).unique().tolist() if group_col else ["All users"]

    def run(subset: pd.DataFrame) -> dict:
        stage_names = [s["event_name"] for s in stages]
        first_name = stage_names[0]
        by_user: dict[str, list[tuple[str, pd.Timestamp]]] = {}
        for row in subset.itertuples(index=False):
            by_user.setdefault(row.user_id, []).append((row.event_name, row.event_timestamp))
        reached = [0] * len(stages)
        cohort = 0
        for user_events in by_user.values():
            user_events.sort(key=lambda x: x[1])
            first_candidates = [ts for name, ts in user_events if name == first_name and start <= ts.date() <= end]
            if not first_candidates:
                continue
            cohort += 1
            current = min(first_candidates)
            reached[0] += 1
            deadline = current + pd.Timedelta(days=window_days)
            for idx in range(1, len(stages)):
                name = stage_names[idx]
                candidates = [ts for n, ts in user_events if n == name and ts >= current and ts <= deadline]
                if not candidates:
                    break
                current = min(candidates)
                reached[idx] += 1
        out_stages = []
        for idx, stage in enumerate(stages):
            users = reached[idx]
            prev = reached[idx - 1] if idx > 0 else cohort
            out_stages.append(
                {
                    **stage,
                    "users": users,
                    "step_conversion": round(users / prev, 6) if prev else 0.0,
                    "from_start_conversion": round(users / cohort, 6) if cohort else 0.0,
                    "dropoff_users": max(0, prev - users),
                    "dropoff_rate": round(max(0, prev - users) / prev, 6) if prev else 0.0,
                }
            )
        return {"stages": out_stages, "cohort_users": cohort}

    overall = run(events)
    group_results = []
    if group_col:
        for group in sorted(groups):
            subset = events[events[group_col].fillna("unknown").astype(str) == group]
            result = run(subset)
            group_results.append({"group": group, **result})
    return overall, group_results


def analyze_funnel(
    stages: list[dict],
    start_date: date,
    end_date: date,
    window_days: int = 14,
    group_by: str | None = None,
    compare_period: bool = False,
    funnel_id: str = "custom",
    name: str = "Custom funnel",
) -> dict:
    stage_names = [s["event_name"] for s in stages]
    events = _load_events(stage_names, start_date, end_date, window_days)
    overall, groups = _compute(events, stages, start_date, end_date, window_days, group_by)

    comparison = None
    if compare_period:
        length = (end_date - start_date).days + 1
        prev_end = start_date - timedelta(days=1)
        prev_start = prev_end - timedelta(days=length - 1)
        prev_events = _load_events(stage_names, prev_start, prev_end, window_days)
        prev_overall, _ = _compute(prev_events, stages, prev_start, prev_end, window_days, None)
        deltas = []
        for current, previous in zip(overall["stages"], prev_overall["stages"], strict=False):
            deltas.append(
                {
                    "key": current["key"],
                    "current_users": current["users"],
                    "previous_users": previous["users"],
                    "users_delta": current["users"] - previous["users"],
                    "conversion_delta": round(
                        current["from_start_conversion"] - previous["from_start_conversion"], 6
                    ),
                }
            )
        comparison = {
            "period_start": prev_start.isoformat(),
            "period_end": prev_end.isoformat(),
            "stages": deltas,
        }

    chart = {
        "type": "funnel",
        "data": [
            {"label": s["label"], "users": s["users"], "conversion": s["from_start_conversion"]}
            for s in overall["stages"]
        ],
    }
    return {
        "funnel_id": funnel_id,
        "name": name,
        "stages": overall["stages"],
        "cohort_users": overall["cohort_users"],
        "groups": groups,
        "group_by": group_by,
        "comparison": comparison,
        "window_days": window_days,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "chart": chart,
        "methodology": (
            "Ordered funnel: each user enters on their first stage-1 event in the period; "
            "subsequent stages must occur at or after the previous stage and within the window. "
            "This is not an unordered 'did event' count."
        ),
        "generated_at": datetime.now(UTC).isoformat(),
    }
