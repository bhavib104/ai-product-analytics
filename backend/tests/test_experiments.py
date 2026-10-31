from __future__ import annotations

from app.analytics import experiments


def test_experiment_list_has_results_and_assignments() -> None:
    rows = experiments.list_experiments()
    assert len(rows) >= 1
    experiment = rows[0]
    assert experiment["experiment_id"] == "exp_onboarding_checklist_v1"
    assert {r["variant"] for r in experiment["assignment_counts"]} == {"control", "treatment"}
    assert experiment["results"]


def test_experiment_analysis_is_statistically_verified() -> None:
    result = experiments.analyze_experiment("exp_onboarding_checklist_v1")
    assert result is not None
    assert result["experiment"]["experiment_id"] == "exp_onboarding_checklist_v1"
    assert result["assignment"]["srm"]["interpretation"]
    assert result["assignment"]["srm"]["p_value"] is not None
    assert result["assignment"]["total"] > 0

    metrics = {metric["metric_key"]: metric for metric in result["metrics"]}
    assert {"activation_7d", "purchase_14d"}.issubset(metrics)

    activation = metrics["activation_7d"]
    assert activation["variants"]["treatment"]["rate"] > activation["variants"]["control"]["rate"]
    assert activation["p_value"] is not None and activation["p_value"] < 0.01
    assert activation["significant"] is True
    assert activation["ci_low"] < activation["absolute_lift"] < activation["ci_high"]

    purchase = metrics["purchase_14d"]
    assert purchase["p_value"] is not None and purchase["p_value"] < 0.05
    assert purchase["variants"]["treatment"]["rate"] > purchase["variants"]["control"]["rate"]

    assert result["power"]["required_per_variant_for_observed_effect"] > 0
    assert 0 <= result["power"]["achieved_power_activation"] <= 1


def test_unknown_experiment_returns_none() -> None:
    assert experiments.analyze_experiment("exp_does_not_exist") is None
