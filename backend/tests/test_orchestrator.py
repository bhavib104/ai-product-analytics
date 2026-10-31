from __future__ import annotations

from datetime import date

from app.ai.orchestrator import Orchestrator
from app.ai.providers import DeterministicProvider
from app.text_to_sql.generator import resolve_dates


def test_deterministic_provider_is_the_default(settings) -> None:
    orchestrator = Orchestrator()
    assert isinstance(orchestrator.provider, DeterministicProvider)


def test_orchestrator_uses_typed_tools_and_returns_evidence() -> None:
    result = Orchestrator().answer("What were the biggest anomalies?")
    assert result["interaction_id"].startswith("int_")
    assert result["answer"]
    assert result["tool_calls"]
    assert {call["tool"] for call in result["tool_calls"]} >= {"get_anomalies"}
    assert all(call["status"] == "success" for call in result["tool_calls"])
    assert result["evidence"]["facts"]
    assert result["fallback"] is False
    assert result["provider"] == "deterministic"
    assert result["citations"]


def test_orchestrator_explains_checkout_drop_with_funnel_and_anomalies() -> None:
    result = Orchestrator().answer("Why did checkout conversion drop?")
    tools = {call["tool"] for call in result["tool_calls"]}
    assert {"get_funnel", "get_anomalies"}.issubset(tools)
    assert "checkout_conversion_rate" in result["answer"]


def test_explicit_day_uses_daily_granularity() -> None:
    start, end = resolve_dates("How many users registered on September 15, 2026?")
    assert (start, end) == (date(2026, 9, 15), date(2026, 9, 15))
    plan = Orchestrator()._plan(
        "How many users registered on September 15, 2026?", start, end, 6
    )
    metric_plan = next(args for name, args in plan if name == "get_metric_series")
    assert metric_plan["granularity"] == "day"


def test_forecast_question_states_scope_limit() -> None:
    result = Orchestrator().answer("What will revenue be next quarter?")
    assert "does not forecast" in result["answer"].lower()
    assert any("does not forecast" in caveat.lower() for caveat in result["caveats"])


def test_narrative_validation_rejects_fabricated_numbers_and_causal_claims() -> None:
    orchestrator = Orchestrator()
    evidence = {"numbers": [12.5, 42.0], "facts": ["observed 12.5"]}
    valid = {
        "summary": "Observed 12.5 versus 42.0 in the evidence.",
        "sections": [],
        "citations": ["get_anomalies"],
    }
    assert orchestrator._validate_narrative(valid, evidence, {"get_anomalies"}) is None

    fabricated = {
        "summary": "Observed 99.9 in the evidence.",
        "sections": [],
        "citations": ["get_anomalies"],
    }
    error = orchestrator._validate_narrative(fabricated, evidence, {"get_anomalies"})
    assert error and "unsupported number" in error

    causal = {
        "summary": "Checkout fell because of the payment provider.",
        "sections": [],
        "citations": ["get_anomalies"],
    }
    assert orchestrator._validate_narrative(causal, evidence, {"get_anomalies"}) == "strong causal language"

    uncited = {"summary": "Observed 12.5.", "sections": [], "citations": ["invented_tool"]}
    assert orchestrator._validate_narrative(uncited, evidence, {"get_anomalies"}) == "invalid citations"
