"""Experiment read models and integrity checks."""

from __future__ import annotations

import json

from app.analytics import stats
from app.db.duck import query_rows


def list_experiments() -> list[dict]:
    experiments = query_rows("SELECT * FROM analytics.experiments ORDER BY start_date DESC")
    for experiment in experiments:
        experiment["results"] = query_rows(
            "SELECT * FROM analytics.experiment_results WHERE experiment_id = ? "
            "ORDER BY metric_key, variant",
            [experiment["experiment_id"]],
        )
        experiment["assignment_counts"] = query_rows(
            "SELECT variant, COUNT(*) AS users FROM analytics.experiment_assignments "
            "WHERE experiment_id = ? GROUP BY 1 ORDER BY 1",
            [experiment["experiment_id"]],
        )
    return experiments


def analyze_experiment(experiment_id: str) -> dict | None:
    rows = query_rows(
        "SELECT * FROM analytics.experiments WHERE experiment_id = ?", [experiment_id]
    )
    if not rows:
        return None
    experiment = rows[0]
    assignments = query_rows(
        "SELECT variant, COUNT(*) AS users FROM analytics.experiment_assignments "
        "WHERE experiment_id = ? GROUP BY 1 ORDER BY 1",
        [experiment_id],
    )
    counts = {row["variant"]: int(row["users"]) for row in assignments}
    control_n = counts.get("control", 0)
    treatment_n = counts.get("treatment", 0)
    srm = stats.chi_square([[control_n, treatment_n]])
    srm["expected_per_variant"] = (control_n + treatment_n) / 2
    srm["observed_control"] = control_n
    srm["observed_treatment"] = treatment_n
    srm["interpretation"] = (
        "Assignment counts are consistent with a 50/50 split."
        if srm.get("p_value") is not None and srm["p_value"] >= 0.05
        else "Assignment counts differ from a 50/50 split; investigate assignment integrity "
        "before trusting outcome comparisons."
    )

    results = query_rows(
        "SELECT * FROM analytics.experiment_results WHERE experiment_id = ? "
        "ORDER BY metric_key, variant",
        [experiment_id],
    )
    metrics: dict[str, dict] = {}
    for row in results:
        metric = metrics.setdefault(
            row["metric_key"],
            {"metric_key": row["metric_key"], "variants": {}, "statistics": None},
        )
        metric["variants"][row["variant"]] = {
            "successes": int(row["successes"]),
            "sample_size": int(row["sample_size"]),
            "rate": float(row["rate"]),
        }
        if row["variant"] == "treatment" and row.get("effect_size_json"):
            try:
                metric["statistics"] = json.loads(row["effect_size_json"])
            except (TypeError, ValueError):
                metric["statistics"] = None
        if row["variant"] == "treatment":
            metric["p_value"] = row.get("p_value")
            metric["significant"] = row.get("significant")
            metric["absolute_lift"] = row.get("absolute_lift")
            metric["relative_lift"] = row.get("relative_lift")
            metric["ci_low"] = row.get("ci_low")
            metric["ci_high"] = row.get("ci_high")

    control_rate = (
        metrics.get("activation_7d", {}).get("variants", {}).get("control", {}).get("rate", 0)
    )
    treatment_rate = (
        metrics.get("activation_7d", {}).get("variants", {}).get("treatment", {}).get("rate", 0)
    )
    power = (
        stats.achieved_power(control_rate, treatment_rate, control_n, treatment_n)
        if control_n and treatment_n
        else 0.0
    )
    required = stats.required_sample_size(control_rate, treatment_rate) if control_rate else 0

    return {
        "experiment": experiment,
        "assignment": {
            "counts": assignments,
            "total": control_n + treatment_n,
            "srm": srm,
        },
        "metrics": list(metrics.values()),
        "power": {
            "achieved_power_activation": round(power, 6),
            "required_per_variant_for_observed_effect": required,
            "alpha": 0.05,
            "note": "Post-hoc power is descriptive only; it is not a substitute for a pre-registered design.",
        },
        "guardrails": [
            "Random assignment and 50/50 SRM check.",
            "Binary outcomes use a two-proportion z-test; Fisher exact when expected counts < 5.",
            "Confidence intervals use the Newcombe method.",
            "Statistical significance does not prove causality or business importance.",
        ],
    }
