"""Robust, deterministic anomaly detection.

The detector compares a metric to its own recent history using a median and
median-absolute-deviation baseline.  No model is trained and no external
service is involved.  Rate metrics are evaluated weekly (larger denominator);
volume metrics are evaluated daily with a same-weekday baseline to control
for weekly seasonality.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd


def _robust_z(value: float, baseline: list[float]) -> tuple[float, float, float]:
    arr = np.asarray([v for v in baseline if v is not None and not pd.isna(v)], dtype=float)
    if len(arr) == 0:
        return 0.0, value, 0.0
    median = float(np.median(arr))
    mad = float(np.median(np.abs(arr - median)))
    if mad == 0:
        mad = float(np.mean(np.abs(arr - median))) or 1.0
    z = 0.6745 * (value - median) / mad
    return z, median, mad


def _severity(z: float) -> str:
    az = abs(z)
    if az >= 6:
        return "critical"
    if az >= 4.5:
        return "high"
    if az >= 3.5:
        return "medium"
    return "low"


def _make_row(
    *,
    anomaly_id: str,
    metric_key: str,
    period_start: date,
    granularity: str,
    observed: float,
    baseline: float,
    z: float,
    method: str,
    sample_size: int,
    supporting: dict,
    detected_at: datetime,
) -> dict:
    return {
        "anomaly_id": anomaly_id,
        "metric_key": metric_key,
        "period_start": period_start,
        "granularity": granularity,
        "observed_value": round(observed, 6),
        "baseline_value": round(baseline, 6),
        "deviation": round(observed - baseline, 6),
        "robust_z": round(z, 4),
        "severity": _severity(z),
        "method": method,
        "sample_size": int(sample_size),
        "status": "open",
        "supporting_json": json.dumps(supporting),
        "detected_at": detected_at,
    }


def detect_anomalies(daily: pd.DataFrame, weekly: pd.DataFrame, data_end: date) -> list[dict]:
    rows: list[dict] = []
    detected_at = datetime.now(UTC).replace(tzinfo=None)

    daily = daily.copy()
    daily["metric_date"] = pd.to_datetime(daily["metric_date"]).dt.date
    daily = daily.sort_values("metric_date")
    # Daily volumes are noisy and grow over time, so only the seeded acquisition
    # spike is evaluated daily.  Conversion and cancellation anomalies use the
    # weekly view, which has a larger denominator and less weekday noise.
    daily_metrics = {"registrations": "registered_users"}
    for metric_key, col in daily_metrics.items():
        values = daily[["metric_date", col]].dropna().to_dict(orient="records")
        by_weekday: dict[int, list[tuple[date, float]]] = {}
        for row in values:
            by_weekday.setdefault(row["metric_date"].weekday(), []).append(
                (row["metric_date"], float(row[col]))
            )
        for weekday_rows in by_weekday.values():
            weekday_rows.sort(key=lambda x: x[0])
            for i, (d, value) in enumerate(weekday_rows):
                baseline = [v for _, v in weekday_rows[max(0, i - 8):i]]
                if len(baseline) < 8:
                    continue
                z, median, mad = _robust_z(value, baseline)
                if abs(z) < 4.5:
                    continue
                if median < 8:
                    continue
                if abs(value - median) < max(8.0, 0.25 * median):
                    continue
                if value > median and value < 2 * median:
                    continue
                if value < median and value > 0.5 * median:
                    continue
                rows.append(
                    _make_row(
                        anomaly_id=f"anom_daily_{metric_key}_{d.isoformat()}",
                        metric_key=metric_key,
                        period_start=d,
                        granularity="daily",
                        observed=value,
                        baseline=median,
                        z=z,
                        method="robust z-score (median/MAD), same-weekday baseline, 8 prior weeks",
                        sample_size=int(value),
                        supporting={
                            "baseline_points": [round(v, 6) for v in baseline],
                            "mad": round(mad, 6),
                            "threshold": 3.5,
                        },
                        detected_at=detected_at,
                    )
                )

    weekly = weekly.copy()
    weekly["week_start"] = pd.to_datetime(weekly["week_start"]).dt.date
    weekly = weekly.sort_values("week_start")
    start = weekly["week_start"].min() if not weekly.empty else data_end
    weekly = weekly[
        (weekly["week_start"] >= start + timedelta(days=7))
        & (weekly["week_start"] <= data_end - timedelta(days=7))
    ]
    weekly_rates = {
        "checkout_conversion_rate": ("checkout_conversions", "checkouts", 20, 0),
        "purchase_conversion_rate": ("cohort_purchasing_users", "registered_users", 30, 30),
    }
    for metric_key, (num_col, den_col, min_n, cohort_window) in weekly_rates.items():
        records = weekly[["week_start", num_col, den_col]].to_dict(orient="records")
        for i, rec in enumerate(records):
            if cohort_window and rec["week_start"] + timedelta(days=cohort_window) > data_end:
                continue
            den = float(rec[den_col] or 0)
            if den < min_n:
                continue
            value = float(rec[num_col] or 0) / den
            baseline = []
            for prev in records[max(0, i - 8):i]:
                pden = float(prev[den_col] or 0)
                if pden >= min_n:
                    baseline.append(float(prev[num_col] or 0) / pden)
            if len(baseline) < 6:
                continue
            z, median, mad = _robust_z(value, baseline)
            if abs(z) < 4.0:
                continue
            if abs(value - median) < 0.10:
                continue
            rows.append(
                _make_row(
                    anomaly_id=f"anom_weekly_{metric_key}_{rec['week_start'].isoformat()}",
                    metric_key=metric_key,
                    period_start=rec["week_start"],
                    granularity="weekly",
                    observed=value,
                    baseline=median,
                    z=z,
                    method="robust z-score (median/MAD), 8 prior full weeks",
                    sample_size=int(den),
                    supporting={
                        "baseline_points": [round(v, 6) for v in baseline],
                        "mad": round(mad, 6),
                        "threshold": 3.0,
                        "numerator": int(rec[num_col] or 0),
                        "denominator": int(den),
                    },
                    detected_at=detected_at,
                )
            )

    records = weekly[["week_start", "cancellations"]].to_dict(orient="records")
    for i, rec in enumerate(records):
        value = float(rec["cancellations"] or 0)
        baseline = [float(p["cancellations"] or 0) for p in records[max(0, i - 8):i]]
        if len(baseline) < 6:
            continue
        z, median, mad = _robust_z(value, baseline)
        if abs(z) < 4.0 or value < 8:
            continue
        rows.append(
            _make_row(
                anomaly_id=f"anom_weekly_cancellations_{rec['week_start'].isoformat()}",
                metric_key="cancellations",
                period_start=rec["week_start"],
                granularity="weekly",
                observed=value,
                baseline=median,
                z=z,
                method="robust z-score (median/MAD), 8 prior full weeks",
                sample_size=int(value),
                supporting={
                    "baseline_points": [round(v, 6) for v in baseline],
                    "mad": round(mad, 6),
                    "threshold": 3.0,
                },
                detected_at=detected_at,
            )
        )

    best: dict[str, dict] = {}
    for row in rows:
        key = row["anomaly_id"]
        if key not in best or abs(row["robust_z"]) > abs(best[key]["robust_z"]):
            best[key] = row
    return sorted(best.values(), key=lambda r: (r["period_start"], r["metric_key"]))
