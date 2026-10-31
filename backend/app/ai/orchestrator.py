"""Single-orchestrator, evidence-bound Copilot.

The orchestrator plans a bounded sequence of typed read-only tools, executes
them, then either (a) composes a deterministic answer from the tool evidence or
(b) asks an optional external LLM to narrate the evidence.  LLM output is
validated against the evidence; unsupported numbers or strong causal claims
trigger the deterministic fallback.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import date

from app.ai.providers import DeterministicProvider, get_provider, parse_json_response
from app.ai.tools import ToolRegistry, ToolResult
from app.core.config import get_settings
from app.db import app_db
from app.text_to_sql.generator import resolve_dates

PROMPT_VERSION = "copilot-v1"
CAUSAL_PATTERNS = re.compile(
    r"\b(caused by|causes|caused|because of|due to|drove|drives|led to|leads to|"
    r"proves|proven|guarantees|definitely|as a result of)\b",
    re.IGNORECASE,
)
FORECAST_PATTERNS = re.compile(
    r"\b(forecast|predict|prediction|projection|projected|next quarter|next month|"
    r"will .* (be|grow|decline|increase|decrease))\b",
    re.IGNORECASE,
)
SCOPE_NOTE = (
    "Scope limitation: this MVP reports historical and current metrics from the synthetic "
    "dataset. It does not forecast future revenue, users or conversion, and the evidence "
    "below should not be read as a prediction."
)


def _scope_note(question: str) -> str | None:
    return SCOPE_NOTE if FORECAST_PATTERNS.search(question) else None


def _detect_dimension(q: str) -> str | None:
    if re.search(r"\b(android|ios|web|device)\b", q):
        return "device"
    if "channel" in q or "paid social" in q or "organic" in q:
        return "channel"
    if "country" in q:
        return "country"
    if "plan" in q or "tier" in q:
        return "plan"
    if "segment" in q or "cluster" in q:
        return "segment"
    return None


def _detect_metric(q: str) -> str | None:
    patterns = [
        ("checkout_conversion_rate", r"checkout conversion|checkout completion"),
        ("purchase_conversion_rate", r"purchase conversion|conversion rate|paying conversion"),
        ("activation_rate", r"activation rate|activation"),
        ("mrr", r"\bmrr\b|revenue"),
        ("cancellations", r"cancellation|churn"),
        ("dau", r"\bdau\b|active users|engagement"),
        ("registered_users", r"registrations?|registered|signup|new users"),
        ("sessions", r"session"),
        ("retention_d7", r"retention"),
    ]
    for metric, pattern in patterns:
        if re.search(pattern, q):
            return metric
    return None


class Orchestrator:
    def __init__(self) -> None:
        self.registry = ToolRegistry()
        self.provider = get_provider()

    def answer(self, question: str, conversation_id: str | None = None) -> dict:
        settings = get_settings()
        started = time.perf_counter()
        interaction_id = f"int_{uuid.uuid4().hex[:12]}"
        conversation_id = conversation_id or f"conv_{uuid.uuid4().hex[:12]}"
        app_db.ensure_conversation(conversation_id, question[:80])
        start, end = resolve_dates(question)
        plan = self._plan(question, start, end, settings.ai_max_tool_calls)

        results: list[ToolResult] = []
        for name, args in plan:
            results.append(self.registry.execute(name, args, interaction_id))

        evidence = self._evidence(results)
        fallback_reason = None
        provider_name = self.provider.name
        model = self.provider.model
        prompt_tokens = completion_tokens = None
        cost = None
        sql = next(
            (
                r.data.get("sql")
                for r in results
                if r.tool == "run_sql" and isinstance(r.data, dict) and r.data.get("sql")
            ),
            None,
        )

        narrative = None
        if not isinstance(self.provider, DeterministicProvider) and results:
            narrative = self._llm_narrative(question, results, evidence)
            if narrative:
                provider_name = self.provider.name
                model = self.provider.model
                prompt_tokens = narrative.get("prompt_tokens")
                completion_tokens = narrative.get("completion_tokens")
                cost = narrative.get("estimated_cost_usd")
            else:
                fallback_reason = "External LLM unavailable or its output failed evidence validation."
        deterministic = self._deterministic(question, results, fallback_reason)
        if narrative:
            deterministic.update(
                {
                    "answer": narrative["answer"],
                    "sections": narrative["sections"],
                    "caveats": narrative["caveats"],
                    "follow_ups": narrative["follow_ups"],
                    "citations": narrative["citations"],
                    "fallback": False,
                }
            )

        scope_note = _scope_note(question)
        if scope_note:
            deterministic["answer"] = f"{scope_note}\n\n{deterministic['answer']}"
            deterministic["caveats"] = [scope_note, *deterministic.get("caveats", [])]

        latency_ms = int((time.perf_counter() - started) * 1000)
        app_db.insert_ai_interaction(
            {
                "id": interaction_id,
                "conversation_id": conversation_id,
                "question": question,
                "answer": deterministic["answer"],
                "sections": deterministic["sections"],
                "evidence": {
                    "tools": [r.tool for r in results],
                    "facts": evidence["facts"],
                    "numbers": evidence["numbers"][:200],
                },
                "sql": sql,
                "provider": provider_name,
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "latency_ms": latency_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "estimated_cost_usd": cost,
            }
        )
        app_db.insert_audit(
            "COPILOT_ANSWERED",
            {
                "interaction_id": interaction_id,
                "tools": [r.tool for r in results],
                "fallback": deterministic["fallback"],
            },
        )
        return {
            "interaction_id": interaction_id,
            "conversation_id": conversation_id,
            "question": question,
            "answer": deterministic["answer"],
            "sections": deterministic["sections"],
            "caveats": deterministic["caveats"],
            "follow_ups": deterministic["follow_ups"],
            "citations": deterministic["citations"],
            "tool_calls": [
                {
                    "tool": r.tool,
                    "arguments": r.arguments,
                    "status": r.status,
                    "duration_ms": r.duration_ms,
                    "summary": r.summary,
                    "error": r.error,
                }
                for r in results
            ],
            "evidence": evidence,
            "sql": sql,
            "provider": provider_name,
            "model": model,
            "fallback": deterministic["fallback"],
            "fallback_reason": deterministic.get("fallback_reason"),
            "latency_ms": latency_ms,
            "prompt_version": PROMPT_VERSION,
        }

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------
    def _plan(self, question: str, start: date, end: date, limit: int) -> list[tuple[str, dict]]:
        q = question.lower()
        dates = {"start_date": start.isoformat(), "end_date": end.isoformat()}
        dimension = _detect_dimension(q)
        metric = _detect_metric(q)
        plan: list[tuple[str, dict]] = []

        def add(name: str, args: dict) -> None:
            if len(plan) >= limit:
                return
            key = (name, json.dumps(args, sort_keys=True, default=str))
            if key not in [(n, json.dumps(a, sort_keys=True, default=str)) for n, a in plan]:
                plan.append((name, args))

        if re.search(r"\b(funnel|activation funnel|drop.?off|conversion)\b", q) and not re.search(
            r"checkout conversion|purchase conversion", q
        ):
            add(
                "get_funnel",
                {
                    **dates,
                    "funnel_id": "default",
                    "group_by": dimension,
                    "compare_period": True,
                },
            )
        if re.search(r"\bretention|cohort\b", q):
            cohort_type = "weekly" if "weekly" in q else "monthly" if "monthly" in q else "daily"
            add("get_retention", {**dates, "cohort_type": cohort_type, "group_by": dimension})
        if re.search(r"\bexperiment|a/b|ab test|variant|srm\b", q):
            match = re.search(r"exp_[a-z0-9_]+", q)
            add("get_experiment", {"experiment_id": match.group(0)} if match else {})
        if re.search(r"\bsegment|cluster|champions|at.?risk|dormant\b", q):
            add("get_segments", {"metric": metric if metric and metric.startswith("retention") else "retention_d7"})
        if re.search(r"\banomal|spike|drop|incident|unusual|outlier\b", q):
            add("get_anomalies", dates)
        if re.search(r"\bfeature|adoption|usage\b", q):
            add("get_feature_adoption", dates)
        if re.search(r"\bsession|duration|frequency\b", q):
            add("get_sessions", {**dates, "group_by": dimension})
        if metric and metric not in {"retention_d7"} and not re.search(
            r"\bfunnel|drop.?off\b", q
        ):
            granularity = "day" if start == end or "daily" in q else "week"
            add("get_metric_series", {**dates, "metric": metric, "granularity": granularity})
        if metric and dimension and metric != "retention_d7":
            add("get_dimension_breakdown", {**dates, "metric": metric, "dimension": dimension})
        if re.search(r"\b(overview|summary|how are we|health|kpi|dashboard)\b", q):
            add("get_overview", {})
        if re.search(r"\bwhy\b", q) and re.search(r"checkout|purchase|drop|conversion", q):
            add("get_funnel", {**dates, "funnel_id": "default", "group_by": "device", "compare_period": True})
            add("get_anomalies", dates)
        if not plan:
            add("get_overview", {})
            add("get_anomalies", dates)
        if len(plan) == 1 and plan[0][0] == "get_overview":
            add("get_anomalies", dates)
        return plan[:limit]

    # ------------------------------------------------------------------
    # Evidence and deterministic narration
    # ------------------------------------------------------------------
    def _evidence(self, results: list[ToolResult]) -> dict:
        numbers: list[float] = []
        facts: list[str] = []
        for result in results:
            if result.status != "success":
                facts.append(f"{result.tool} failed: {result.error}")
                continue
            for value in result.evidence.get("numbers", []):
                if value not in numbers:
                    numbers.append(float(value))
            facts.extend(result.evidence.get("facts", []))
        return {"numbers": numbers, "facts": facts}

    def _deterministic(
        self, question: str, results: list[ToolResult], fallback_reason: str | None
    ) -> dict:
        sections: list[dict] = []
        citations: list[str] = []
        for result in results:
            if result.status != "success":
                sections.append(
                    {
                        "title": f"{result.tool} unavailable",
                        "body": result.error or "The tool did not return evidence.",
                    }
                )
                continue
            citations.append(result.tool)
            bullets = self._bullets(result)
            sections.append(
                {
                    "title": result.tool.replace("_", " ").title(),
                    "body": result.summary,
                    "bullets": bullets,
                }
            )
        successful = [r for r in results if r.status == "success"]
        if successful:
            summary = " ".join(r.summary for r in successful[:3])
        else:
            summary = "No analytical tool returned usable evidence for this question."
        answer = summary + "\n\n" + "\n\n".join(
            f"**{section['title']}**\n{section['body']}"
            + ("\n" + "\n".join(f"- {b}" for b in section.get("bullets", [])) if section.get("bullets") else "")
            for section in sections
        )
        caveats = [
            "All figures are computed deterministically from the synthetic dataset; none are generated by a language model.",
            "This is observational product data. Associations and funnel differences are not proof of causation.",
            "Retention uses exact day-N activity; incomplete future cohorts are excluded from weighted summaries.",
            "Experiment results are randomized but should be checked for assignment integrity (SRM) and practical significance.",
        ]
        follow_ups = self._follow_ups(question, results)
        return {
            "answer": answer,
            "sections": sections,
            "caveats": caveats,
            "follow_ups": follow_ups,
            "citations": citations,
            "fallback": bool(fallback_reason),
            "fallback_reason": fallback_reason,
        }

    def _bullets(self, result: ToolResult) -> list[str]:
        data = result.data or {}
        bullets: list[str] = []
        if result.tool == "get_overview":
            k = data.get("kpis", {})
            bullets.extend(
                [
                    f"Total users: {k.get('total_users')}",
                    f"Active users (30d): {k.get('active_users_30d')}",
                    f"MRR: ${k.get('mrr', 0):,.2f}",
                    f"Purchase conversion: {k.get('purchase_conversion_rate', 0):.2%}",
                    f"D7 retention: {(k.get('retention_d7') or 0):.2%}",
                ]
            )
            anomalies = data.get("anomalies", [])
            if anomalies:
                top = anomalies[0]
                bullets.append(
                    f"Latest anomaly: {top.get('metric_key')} on {top.get('period_start')} "
                    f"({top.get('severity')}, robust z={top.get('robust_z')})"
                )
        elif result.tool == "get_anomalies":
            for row in data.get("anomalies", [])[:5]:
                bullets.append(
                    f"{row.get('metric_key')} on {row.get('period_start')}: observed "
                    f"{row.get('observed_value')} vs baseline {row.get('baseline_value')} "
                    f"(z={row.get('robust_z')}, {row.get('severity')})"
                )
        elif result.tool == "get_funnel":
            for stage in data.get("stages", []):
                bullets.append(
                    f"{stage.get('label')}: {stage.get('users')} users, "
                    f"{stage.get('from_start_conversion', 0):.2%} from start, "
                    f"drop-off {stage.get('dropoff_rate', 0):.2%}"
                )
            for group in data.get("groups", [])[:8]:
                final = group.get("stages", [])[-1] if group.get("stages") else {}
                bullets.append(
                    f"Group {group.get('group')}: {group.get('cohort_users')} entrants, "
                    f"{final.get('from_start_conversion', 0):.2%} reach the final stage"
                )
        elif result.tool == "get_retention":
            summary = data.get("summary", {})
            for key in ("d1", "d7", "d14", "d30"):
                value = summary.get(key)
                if value:
                    bullets.append(
                        f"{key.upper()}: {value.get('rate', 0):.2%} "
                        f"({value.get('retained')}/{value.get('cohort_users')})"
                    )
            for group in data.get("by_dimension", [])[:8]:
                d7 = next(
                    (p for p in group.get("periods", []) if p.get("period_days") == 7),
                    None,
                )
                if d7:
                    bullets.append(
                        f"{group.get('value')} D7: {d7.get('rate', 0):.2%} "
                        f"({d7.get('retained')}/{d7.get('cohort_users')})"
                    )
        elif result.tool == "get_experiment":
            for metric in data.get("metrics", []):
                stats = metric.get("statistics") or {}
                bullets.append(
                    f"{metric.get('metric_key')}: control {stats.get('rate_control', 0):.2%} vs "
                    f"treatment {stats.get('rate_treatment', 0):.2%}; p={stats.get('p_value')}; "
                    f"95% CI [{stats.get('ci_low')}, {stats.get('ci_high')}]"
                )
            srm = data.get("assignment", {}).get("srm", {})
            bullets.append(f"SRM p-value: {srm.get('p_value')}")
        elif result.tool == "get_segments":
            for row in data.get("segments", {}).get("rule_segments", [])[:5]:
                bullets.append(
                    f"{row.get('name')}: {row.get('users')} users ({row.get('share', 0):.2%}), "
                    f"avg MRR ${row.get('avg_mrr', 0):,.2f}"
                )
        elif result.tool == "get_dimension_breakdown":
            for row in data.get("rows", [])[:6]:
                bullets.append(f"{row.get('dimension_value')}: {row.get('value')}")
        elif result.tool == "get_metric_series":
            points = data.get("points", [])
            if points:
                bullets.append(f"First: {points[0]}")
                bullets.append(f"Last: {points[-1]}")
        elif result.tool == "get_feature_adoption":
            for row in data.get("features", [])[:6]:
                bullets.append(
                    f"{row.get('feature_name')}: {row.get('users')} user-days, "
                    f"avg adoption {row.get('avg_adoption_rate', 0):.2%}"
                )
        elif result.tool == "run_sql":
            bullets.append(f"Rows returned: {data.get('row_count')}")
            for row in data.get("rows", [])[:3]:
                bullets.append(str(row))
        return bullets

    def _follow_ups(self, question: str, results: list[ToolResult]) -> list[str]:
        names = {r.tool for r in results}
        follow = []
        if "get_funnel" in names:
            follow.append("Break the funnel down by device and compare it with the prior period.")
        if "get_retention" in names:
            follow.append("Which acquisition channel has the weakest D7 retention?")
        if "get_experiment" in names:
            follow.append("Check the experiment for sample-ratio mismatch and practical significance.")
        if "get_anomalies" in names:
            follow.append("Which segments or devices drove the latest anomaly?")
        follow.append("Show the daily trend for the most important metric in this answer.")
        return follow[:4]

    # ------------------------------------------------------------------
    # Optional LLM narration
    # ------------------------------------------------------------------
    def _llm_narrative(self, question: str, results: list[ToolResult], evidence: dict) -> dict | None:
        system = (
            "You are a product analytics copilot. Use ONLY the supplied tool evidence. "
            "Never invent a number, metric, date, or causal claim. Do not say a metric was "
            "'caused by' something; say 'associated with' unless the evidence is a randomized "
            "experiment. Cite the tools you used. Return strict JSON with keys: summary (string), "
            "sections (array of {title, body}), caveats (array of strings), follow_ups (array of "
            "strings), citations (array of tool names). Keep it concise."
        )
        payload = {
            "question": question,
            "tools": [
                {
                    "tool": r.tool,
                    "status": r.status,
                    "summary": r.summary,
                    "arguments": r.arguments,
                }
                for r in results
            ],
            "evidence_facts": evidence["facts"],
            "evidence_numbers": evidence["numbers"][:200],
        }
        response = self.provider.generate(
            system, json.dumps(payload, default=str), max_tokens=get_settings().ai_max_output_tokens
        )
        if response.error or not response.text:
            return None
        parsed = parse_json_response(response.text)
        if not parsed:
            return None
        validation_error = self._validate_narrative(parsed, evidence, {r.tool for r in results})
        if validation_error:
            return None
        sections = parsed.get("sections") or []
        answer = str(parsed.get("summary", "")).strip()
        if sections:
            answer += "\n\n" + "\n\n".join(
                f"**{s.get('title', 'Finding')}**\n{s.get('body', '')}" for s in sections if isinstance(s, dict)
            )
        return {
            "answer": answer,
            "sections": sections,
            "caveats": parsed.get("caveats") or [],
            "follow_ups": parsed.get("follow_ups") or [],
            "citations": parsed.get("citations") or [],
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "estimated_cost_usd": response.estimated_cost_usd,
        }

    def _validate_narrative(self, parsed: dict, evidence: dict, used_tools: set[str]) -> str | None:
        summary = str(parsed.get("summary", ""))
        sections = parsed.get("sections") or []
        text = summary + " " + " ".join(
            f"{s.get('title', '')} {s.get('body', '')}" for s in sections if isinstance(s, dict)
        )
        if not summary.strip():
            return "empty summary"
        citations = parsed.get("citations") or []
        if not citations or not set(citations).issubset(used_tools):
            return "invalid citations"
        if CAUSAL_PATTERNS.search(text):
            return "strong causal language"
        numbers = evidence["numbers"]
        allowed = {0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 100.0, 0.05, 2026.0}
        for token in re.findall(r"-?\d+(?:\.\d+)?", text.replace(",", "")):
            value = float(token)
            if value in allowed:
                continue
            if any(
                abs(value - candidate) <= max(0.02, abs(candidate) * 0.02)
                or abs(value / 100 - candidate) <= max(0.002, abs(candidate) * 0.02)
                for candidate in numbers
            ):
                continue
            return f"unsupported number {token}"
        return None
