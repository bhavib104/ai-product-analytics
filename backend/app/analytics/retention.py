"""Cohort retention read models."""

from __future__ import annotations

from datetime import date

import pandas as pd

from app.db.duck import query_df

DIMENSION_MAP = {
    "channel": "channel",
    "device": "device",
    "country": "country",
    "plan": "plan",
    "segment": "segment",
}


def get_retention(
    cohort_type: str = "daily",
    start_date: date | None = None,
    end_date: date | None = None,
    group_by: str | None = None,
    periods: list[int] | None = None,
) -> dict:
    cohort_type = cohort_type if cohort_type in {"daily", "weekly", "monthly"} else "daily"
    where = ["cohort_type = ?"]
    params: list = [cohort_type]
    if start_date:
        where.append("cohort_date >= ?")
        params.append(start_date.isoformat())
    if end_date:
        where.append("cohort_date <= ?")
        params.append(end_date.isoformat())
    df = query_df(
        "SELECT * FROM analytics.cohort_retention WHERE " + " AND ".join(where) + " ORDER BY cohort_date, period_index",
        params,
    )
    if df.empty:
        return {
            "cohort_type": cohort_type,
            "periods": periods or [],
            "cohorts": [],
            "summary": {},
            "by_dimension": [],
            "curve": [],
            "methodology": "Classic day-N retention on the registration cohort.",
        }
    df["cohort_date"] = pd.to_datetime(df["cohort_date"]).dt.date
    if periods:
        df = df[df["period_index"].isin(periods)]
    period_values = sorted(df["period_index"].unique().tolist())
    cohorts = []
    for cohort_date, group in df.groupby("cohort_date"):
        values = {
            str(int(row.period_index)): {
                "rate": round(float(row.retention_rate), 6),
                "retained": int(row.retained_users),
                "complete": bool(row.is_complete),
            }
            for row in group.itertuples()
        }
        cohorts.append(
            {
                "cohort_date": cohort_date.isoformat(),
                "cohort_size": int(group["cohort_size"].iloc[0]),
                "values": values,
            }
        )

    complete = df[df["is_complete"]]
    summary = {}
    for p in (1, 7, 14, 30):
        subset = complete[complete["period_index"] == p]
        if subset.empty:
            summary[f"d{p}"] = None
            continue
        total = int(subset["cohort_size"].sum())
        retained = int(subset["retained_users"].sum())
        summary[f"d{p}"] = {
            "rate": round(retained / total, 6) if total else 0.0,
            "retained": retained,
            "cohort_users": total,
            "cohorts": int(len(subset)),
        }

    curve = []
    for p in period_values:
        subset = complete[complete["period_index"] == p]
        total = int(subset["cohort_size"].sum())
        retained = int(subset["retained_users"].sum())
        curve.append(
            {
                "period": int(p),
                "rate": round(retained / total, 6) if total else 0.0,
                "cohort_users": total,
            }
        )

    by_dimension = []
    if group_by and group_by in DIMENSION_MAP:
        dim_df = query_df(
            "SELECT * FROM analytics.retention_by_dimension WHERE dimension_type = ? "
            "AND cohort_date >= ? AND cohort_date <= ? ORDER BY dimension_value, cohort_date, period_days",
            [
                DIMENSION_MAP[group_by],
                (start_date.isoformat() if start_date else "1900-01-01"),
                (end_date.isoformat() if end_date else "2999-12-31"),
            ],
        )
        if not dim_df.empty:
            dim_df["cohort_date"] = pd.to_datetime(dim_df["cohort_date"]).dt.date
            for value, group in dim_df.groupby("dimension_value"):
                periods_out = []
                for p, pgroup in group.groupby("period_days"):
                    total = int(pgroup["cohort_size"].sum())
                    retained = int(pgroup["retained_users"].sum())
                    periods_out.append(
                        {
                            "period_days": int(p),
                            "rate": round(retained / total, 6) if total else 0.0,
                            "retained": retained,
                            "cohort_users": total,
                            "cohorts": int(len(pgroup)),
                        }
                    )
                by_dimension.append({"value": value, "periods": sorted(periods_out, key=lambda x: x["period_days"])})
            by_dimension.sort(key=lambda x: x["value"])

    return {
        "cohort_type": cohort_type,
        "periods": [int(p) for p in period_values],
        "cohorts": cohorts,
        "summary": summary,
        "by_dimension": by_dimension,
        "curve": curve,
        "group_by": group_by,
        "methodology": (
            "Classic day-N retention: cohort users are counted as retained when they have at least "
            "one event on registration date + N. Weekly/monthly brackets count any activity in the "
            "target week/month. Incomplete future periods are flagged."
        ),
    }
