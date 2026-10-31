"""Typed, allow-listed tools available to the Copilot orchestrator.

Every tool is read-only, has a Pydantic argument schema, runs with a timeout, and
is logged to SQLite.  The orchestrator can only call tools in this registry.
"""

from __future__ import annotations

import contextlib
import json
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.analytics import experiments, metrics, retention, segments
from app.analytics.funnel import analyze_funnel
from app.core.config import get_settings
from app.core.errors import AppError
from app.db import app_db
from app.db.duck import query_rows
from app.text_to_sql.executor import execute_sql


class DateRangeArgs(BaseModel):
    start_date: date | None = None
    end_date: date | None = None


class OverviewArgs(BaseModel):
    pass


class MetricSeriesArgs(DateRangeArgs):
    metric: str = Field(description="Metric key, e.g. dau, mrr, registrations, checkout_conversion_rate")
    granularity: Literal["day", "week", "month"] = "day"


class BreakdownArgs(DateRangeArgs):
    metric: str
    dimension: Literal["channel", "device", "country", "plan", "segment"] = "channel"


class FunnelArgs(DateRangeArgs):
    funnel_id: str = "default"
    window_days: int | None = None
    group_by: Literal["channel", "device", "country", "plan", "segment"] | None = None
    compare_period: bool = True


class RetentionArgs(DateRangeArgs):
    cohort_type: Literal["daily", "weekly", "monthly"] = "daily"
    group_by: Literal["channel", "device", "country", "plan", "segment"] | None = None
    periods: list[int] | None = None


class SegmentArgs(BaseModel):
    metric: str = "retention_d7"


class ExperimentArgs(BaseModel):
    experiment_id: str | None = None


class AnomalyArgs(DateRangeArgs):
    severity: Literal["low", "medium", "high", "critical"] | None = None


class FeatureArgs(DateRangeArgs):
    feature: str | None = None


class SessionArgs(DateRangeArgs):
    granularity: Literal["day", "week", "month"] = "day"
    group_by: Literal["channel", "device", "country", "plan", "segment"] | None = None


class SqlArgs(BaseModel):
    sql: str = Field(description="A single read-only analytical SELECT statement")


@dataclass
class ToolResult:
    tool: str
    arguments: dict
    status: str
    data: Any = None
    evidence: dict = field(default_factory=dict)
    summary: str = ""
    duration_ms: int = 0
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "tool": self.tool,
            "arguments": self.arguments,
            "status": self.status,
            "data": self.data,
            "evidence": self.evidence,
            "summary": self.summary,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


def _default_range(args: DateRangeArgs) -> tuple[date, date]:
    settings = get_settings()
    end = args.end_date or settings.data_end_date
    start = args.start_date or (end - timedelta(days=29))
    return start, end


def _numbers(value, limit: int = 400) -> list[float]:
    out: list[float] = []

    def walk(item):
        if len(out) >= limit:
            return
        if isinstance(item, (bool, int, float)):
            out.append(float(item))
        elif isinstance(item, dict):
            for v in item.values():
                walk(v)
        elif isinstance(item, (list, tuple)):
            for v in item:
                walk(v)

    walk(value)
    return out[:limit]


def _handler_overview(args: OverviewArgs) -> tuple[dict, str]:
    data = metrics.overview()
    k = data["kpis"]
    summary = (
        f"{k['total_users']} total users; {k['active_users_30d']} active in the last 30 days; "
        f"MRR ${k['mrr']:,.2f}; purchase conversion {k['purchase_conversion_rate']:.2%}; "
        f"D7 retention {k['retention_d7']:.2%}."
        if k.get("retention_d7") is not None
        else f"{k['total_users']} total users; MRR ${k['mrr']:,.2f}."
    )
    return data, summary


def _handler_metric_series(args: MetricSeriesArgs) -> tuple[dict, str]:
    start, end = _default_range(args)
    data = metrics.metric_series(args.metric, start, end, args.granularity)
    points = data.get("points", [])
    if points:
        first, last = points[0], points[-1]
        summary = (
            f"{args.metric}: {first['value']} on {first['date']} → {last['value']} on "
            f"{last['date']} ({len(points)} points)."
        )
    else:
        summary = f"{args.metric}: no data in the selected period."
    return data, summary


def _handler_breakdown(args: BreakdownArgs) -> tuple[dict, str]:
    start, end = _default_range(args)
    data = metrics.dimension_breakdown(args.metric, start, end, args.dimension)
    rows = data.get("rows", [])
    if rows:
        top = rows[0]
        summary = (
            f"{args.metric} by {args.dimension}: {len(rows)} groups; top "
            f"{top['dimension_value']} = {top['value']}."
        )
        if "rate" in args.metric:
            bottom = min(rows, key=lambda row: row["value"])
            summary += f" Lowest: {bottom['dimension_value']} = {bottom['value']}."
    else:
        summary = f"{args.metric} by {args.dimension}: no data."
    return data, summary


def _handler_funnel(args: FunnelArgs) -> tuple[dict, str]:
    start, end = _default_range(args)
    record = app_db.get_funnel(args.funnel_id)
    if not record:
        raise AppError("NOT_FOUND", f"Funnel '{args.funnel_id}' not found.", 404)
    stages = json.loads(record["stages_json"])
    window = args.window_days or int(record["window_days"])
    data = analyze_funnel(
        stages,
        start,
        end,
        window_days=window,
        group_by=args.group_by,
        compare_period=args.compare_period,
        funnel_id=args.funnel_id,
        name=record["name"],
    )
    stage_list = data["stages"]
    worst = max(stage_list[1:], key=lambda s: s["dropoff_rate"]) if len(stage_list) > 1 else stage_list[0]
    summary = (
        f"{record['name']}: {stage_list[0]['users']} users entered; "
        f"{stage_list[-1]['users']} reached the final stage "
        f"({stage_list[-1]['from_start_conversion']:.2%} from start). Largest drop-off: "
        f"{worst['label']} ({worst['dropoff_rate']:.2%})."
    )
    if args.group_by and data.get("groups"):
        ranked = []
        for group in data["groups"]:
            stages_in_group = group.get("stages") or []
            if stages_in_group:
                ranked.append(
                    (
                        group.get("group"),
                        stages_in_group[-1].get("from_start_conversion", 0.0),
                        group.get("cohort_users", 0),
                    )
                )
        if ranked:
            weakest = min(ranked, key=lambda item: item[1])
            summary += (
                f" By {args.group_by}, the weakest group is {weakest[0]} "
                f"({weakest[1]:.2%} to the final stage, {weakest[2]} entrants)."
            )
    return data, summary


def _handler_retention(args: RetentionArgs) -> tuple[dict, str]:
    start, end = _default_range(args)
    data = retention.get_retention(
        args.cohort_type, start, end, group_by=args.group_by, periods=args.periods
    )
    d7 = data["summary"].get("d7")
    summary = (
        f"{args.cohort_type.title()} retention: D1 "
        f"{(data['summary'].get('d1') or {}).get('rate', 0):.2%}, "
        f"D7 {d7['rate']:.2%}, D30 "
        f"{(data['summary'].get('d30') or {}).get('rate', 0):.2%}."
        if d7
        else f"{args.cohort_type.title()} retention: insufficient complete cohorts."
    )
    if args.group_by and data.get("by_dimension"):
        rates = []
        for group in data["by_dimension"]:
            d7_period = next(
                (p for p in group["periods"] if p["period_days"] == 7), None
            )
            if d7_period:
                rates.append((group["value"], d7_period["rate"], d7_period["cohort_users"]))
        if rates:
            weakest = min(rates, key=lambda x: x[1])
            summary += (
                f" By {args.group_by}, the weakest D7 group is {weakest[0]} "
                f"({weakest[1]:.2%}, {weakest[2]} cohort users)."
            )
    return data, summary


def _handler_segments(args: SegmentArgs) -> tuple[dict, str]:
    data = segments.segment_summary()
    comparison = segments.segment_metric_comparison(args.metric)
    rule = data.get("rule_segments", [])
    top = rule[0] if rule else None
    summary = (
        f"{len(rule)} rule-based segments; largest is {top['name']} with {top['users']} users "
        f"({top['share']:.2%}). Compared {args.metric} across segments."
        if top
        else "No segments found."
    )
    return {"segments": data, "comparison": comparison}, summary


def _handler_experiment(args: ExperimentArgs) -> tuple[dict, str]:
    if not args.experiment_id:
        available = experiments.list_experiments()
        if len(available) == 1:
            args = ExperimentArgs(experiment_id=available[0]["experiment_id"])
        else:
            return {"experiments": available}, f"{len(available)} experiments found."
    data = experiments.analyze_experiment(args.experiment_id)
    if not data:
        raise AppError("NOT_FOUND", f"Experiment '{args.experiment_id}' not found.", 404)
    activation = next(
        (m for m in data["metrics"] if m["metric_key"] == "activation_7d"), None
    )
    if activation and activation.get("statistics"):
        stats = activation["statistics"]
        summary = (
            f"Experiment {args.experiment_id}: activation 7d control "
            f"{stats.get('rate_control', 0):.2%} vs treatment "
            f"{stats.get('rate_treatment', 0):.2%}; p={stats.get('p_value')}; "
            f"absolute lift {stats.get('absolute_lift', 0):+.2%}."
        )
    else:
        summary = f"Experiment {args.experiment_id} found but activation results are incomplete."
    return data, summary


def _handler_anomalies(args: AnomalyArgs) -> tuple[dict, str]:
    start, end = _default_range(args)
    sql = (
        "SELECT anomaly_id, metric_key, period_start, granularity, observed_value, "
        "baseline_value, deviation, robust_z, severity, method, sample_size, supporting_json "
        "FROM analytics.anomaly_events WHERE period_start BETWEEN ? AND ?"
    )
    params: list = [start.isoformat(), end.isoformat()]
    if args.severity:
        sql += " AND severity = ?"
        params.append(args.severity)
    sql += " ORDER BY ABS(robust_z) DESC"
    rows = query_rows(sql, params)
    summary = (
        f"{len(rows)} anomalies in the period. "
        + (
            f"Strongest: {rows[0]['metric_key']} on {rows[0]['period_start']} "
            f"({rows[0]['severity']}, robust z={rows[0]['robust_z']})."
            if rows
            else "No anomalies detected."
        )
    )
    return {"anomalies": rows}, summary


def _handler_features(args: FeatureArgs) -> tuple[dict, str]:
    start, end = _default_range(args)
    data = metrics.feature_adoption(start, end, feature=args.feature)
    features = data.get("features", [])
    summary = (
        f"{len(features)} features; top feature {features[0]['feature_name']} with "
        f"{features[0]['users']} user-days and average adoption {features[0]['avg_adoption_rate']:.2%}."
        if features
        else "No feature adoption data."
    )
    return data, summary


def _handler_sessions(args: SessionArgs) -> tuple[dict, str]:
    start, end = _default_range(args)
    data = metrics.session_metrics(start, end, args.granularity, args.group_by)
    summary = "Session metrics computed from rebuilt event sessions."
    return data, summary


def _handler_sql(args: SqlArgs) -> tuple[dict, str]:
    result = execute_sql(args.sql)
    summary = (
        f"Validated SQL returned {result['row_count']} rows in {result['duration_ms']} ms"
        + (" (truncated at the row cap)." if result["truncated"] else ".")
    )
    return result, summary


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: type[BaseModel]
    handler: Callable[[Any], tuple[dict, str]]
    permission: str = "read"


TOOLS: dict[str, ToolSpec] = {
    "get_overview": ToolSpec(
        "get_overview",
        "KPI overview: users, active users, MRR, conversion, D7 retention, trend, channels, segments, anomalies.",
        OverviewArgs,
        _handler_overview,
    ),
    "get_metric_series": ToolSpec(
        "get_metric_series",
        "Time series for one documented metric (dau, mrr, registrations, conversion rates, cancellations).",
        MetricSeriesArgs,
        _handler_metric_series,
    ),
    "get_dimension_breakdown": ToolSpec(
        "get_dimension_breakdown",
        "Break a metric down by channel, device, country, plan or segment.",
        BreakdownArgs,
        _handler_breakdown,
    ),
    "get_funnel": ToolSpec(
        "get_funnel",
        "Ordered funnel analysis with per-stage conversion and optional grouping/comparison.",
        FunnelArgs,
        _handler_funnel,
    ),
    "get_retention": ToolSpec(
        "get_retention",
        "Cohort retention matrix and D1/D7/D14/D30 summary, optionally by dimension.",
        RetentionArgs,
        _handler_retention,
    ),
    "get_segments": ToolSpec(
        "get_segments",
        "Rule-based segments, KMeans clusters, and segment metric comparison.",
        SegmentArgs,
        _handler_segments,
    ),
    "get_experiment": ToolSpec(
        "get_experiment",
        "Experiment results, SRM check, p-values, confidence intervals and power.",
        ExperimentArgs,
        _handler_experiment,
    ),
    "get_anomalies": ToolSpec(
        "get_anomalies",
        "Detected metric anomalies with baseline, robust z-score and severity.",
        AnomalyArgs,
        _handler_anomalies,
    ),
    "get_feature_adoption": ToolSpec(
        "get_feature_adoption",
        "Feature adoption summary and daily series.",
        FeatureArgs,
        _handler_features,
    ),
    "get_sessions": ToolSpec(
        "get_sessions",
        "Session volume, average duration and sessions per active user.",
        SessionArgs,
        _handler_sessions,
    ),
    "run_sql": ToolSpec(
        "run_sql",
        "Run a single validated read-only SELECT against the analytical allow-list. Use sparingly.",
        SqlArgs,
        _handler_sql,
    ),
}


class ToolRegistry:
    def __init__(self) -> None:
        self.specs = TOOLS

    def list_specs(self) -> list[dict]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "permission": spec.permission,
                "parameters": spec.parameters.model_json_schema(),
            }
            for spec in self.specs.values()
        ]

    def execute(self, name: str, arguments: dict, interaction_id: str | None = None) -> ToolResult:
        spec = self.specs.get(name)
        call_id = f"tool_{uuid.uuid4().hex[:12]}"
        started = time.perf_counter()
        if not spec:
            result = ToolResult(
                tool=name,
                arguments=arguments,
                status="error",
                error=f"Unknown tool '{name}'.",
                duration_ms=0,
            )
            self._log(call_id, interaction_id, result)
            return result
        try:
            parsed = spec.parameters.model_validate(arguments or {})
        except ValidationError as exc:
            result = ToolResult(
                tool=name,
                arguments=arguments,
                status="error",
                error=f"Invalid arguments: {exc.errors()}",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            self._log(call_id, interaction_id, result)
            return result

        settings = get_settings()
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(spec.handler, parsed)
        try:
            data, summary = future.result(timeout=settings.ai_tool_timeout_seconds)
            status = "success"
            error = None
        except FutureTimeout:
            data = None
            summary = ""
            status = "timeout"
            error = f"Tool exceeded {settings.ai_tool_timeout_seconds}s timeout."
            future.cancel()
        except AppError as exc:
            data = None
            summary = ""
            status = "error"
            error = exc.message
        except Exception as exc:  # pragma: no cover - defensive
            data = None
            summary = ""
            status = "error"
            error = str(exc)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        duration_ms = int((time.perf_counter() - started) * 1000)
        result = ToolResult(
            tool=name,
            arguments=parsed.model_dump(mode="json"),
            status=status,
            data=data,
            evidence={"numbers": _numbers(data), "facts": [summary] if summary else []},
            summary=summary,
            duration_ms=duration_ms,
            error=error,
        )
        self._log(call_id, interaction_id, result)
        return result

    def _log(self, call_id: str, interaction_id: str | None, result: ToolResult) -> None:
        if not interaction_id:
            return
        # Logging must never break a read-only tool call.
        with contextlib.suppress(Exception):
            app_db.insert_tool_call(
                {
                    "id": call_id,
                    "interaction_id": interaction_id,
                    "tool_name": result.tool,
                    "arguments": result.arguments,
                    "status": result.status,
                    "duration_ms": result.duration_ms,
                    "result_summary": result.summary[:2000] if result.summary else None,
                    "error": result.error,
                }
            )
