"""HTTP API for the analytics product and Copilot."""

from __future__ import annotations

import contextlib
import json
from datetime import date, timedelta

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse

from app.ai.orchestrator import Orchestrator
from app.ai.tools import ToolRegistry
from app.analytics import experiments as experiments_engine
from app.analytics import metrics, retention, segments
from app.analytics.definitions import ALLOWED_TABLES, METRIC_DEFINITIONS
from app.analytics.funnel import analyze_funnel
from app.core.config import get_settings
from app.core.errors import AppError, NotFoundError
from app.db import app_db
from app.db.duck import data_ready, query_rows, reset_connections
from app.pipeline.process import run_pipeline
from app.reports import builder as reports
from app.schemas import (
    AskRequest,
    CreateFunnelRequest,
    FunnelAnalyzeRequest,
    IngestRequest,
    ReportRequest,
    SqlRequest,
)
from app.text_to_sql import pipeline as sql_pipeline
from app.text_to_sql.executor import execute_sql
from app.text_to_sql.validator import validate_sql

router = APIRouter()
orchestrator = Orchestrator()
tool_registry = ToolRegistry()


def _load_json_fields(row: dict, fields: tuple[str, ...]) -> dict:
    for field in fields:
        if isinstance(row.get(field), str):
            with contextlib.suppress(ValueError):
                row[field.replace("_json", "")] = json.loads(row[field])
    return row


def _range(start_date: date | None, end_date: date | None, days: int = 29) -> tuple[date, date]:
    settings = get_settings()
    end = end_date or settings.data_end_date
    start = start_date or (end - timedelta(days=days))
    if start > end:
        raise AppError("INVALID_RANGE", "start_date must be on or before end_date.", 400)
    return start, end


@router.get("/health")
def health() -> dict:
    ready, message = data_ready()
    return {"status": "ok" if ready else "degraded", "data_ready": ready, "message": message}


@router.get("/meta")
def meta() -> dict:
    settings = get_settings()
    manifest = None
    if settings.duckdb_path.exists():
        try:
            rows = query_rows(
                "SELECT manifest_json FROM analytics.pipeline_manifest ORDER BY created_at DESC LIMIT 1"
            )
            if rows:
                manifest = json.loads(rows[0]["manifest_json"])
        except Exception:
            manifest = None
    event_names: list[str] = []
    if settings.duckdb_path.exists():
        try:
            event_names = [
                row["event_name"]
                for row in query_rows("SELECT DISTINCT event_name FROM analytics.events ORDER BY 1")
            ]
        except Exception:
            event_names = []
    return {
        "app": settings.app_name,
        "environment": settings.environment,
        "data_window": {
            "start_date": settings.data_start_date.isoformat(),
            "end_date": settings.data_end_date.isoformat(),
            "as_of": settings.as_of_date.isoformat(),
            "synthetic": True,
            "seed": settings.data_seed,
        },
        "llm": {
            "provider": settings.llm_provider,
            "deterministic_default": True,
            "optional_providers": ["ollama", "openai"],
            "model": settings.ollama_model if settings.llm_provider == "ollama" else settings.openai_model if settings.llm_provider == "openai" else "evidence-template-v1",
        },
        "limits": {
            "sql_max_rows": settings.sql_max_rows,
            "sql_timeout_seconds": settings.sql_timeout_seconds,
            "sql_max_joins": settings.sql_max_joins,
            "sql_max_subquery_depth": settings.sql_max_subquery_depth,
            "sql_max_ast_nodes": settings.sql_max_ast_nodes,
            "ai_max_tool_calls": settings.ai_max_tool_calls,
            "ai_tool_timeout_seconds": settings.ai_tool_timeout_seconds,
        },
        "metrics": METRIC_DEFINITIONS,
        "schema": ALLOWED_TABLES,
        "event_names": event_names,
        "tools": tool_registry.list_specs(),
        "manifest": manifest,
        "disclaimer": (
            "Synthetic data only. Metrics are computed deterministically in code. "
            "The Copilot never computes authoritative statistics."
        ),
    }


@router.get("/overview")
def overview() -> dict:
    return metrics.overview()


@router.get("/engagement")
def engagement(
    start_date: date | None = None,
    end_date: date | None = None,
    granularity: str = Query("day", pattern="^(day|week|month)$"),
    group_by: str | None = Query(None, pattern="^(channel|device|country|plan|segment)$"),
) -> dict:
    start, end = _range(start_date, end_date, days=59)
    return metrics.engagement_series(start, end, granularity, group_by)


@router.get("/features")
def features(
    start_date: date | None = None,
    end_date: date | None = None,
    feature: str | None = None,
) -> dict:
    start, end = _range(start_date, end_date, days=59)
    return metrics.feature_adoption(start, end, feature)


@router.get("/sessions")
def sessions(
    start_date: date | None = None,
    end_date: date | None = None,
    granularity: str = Query("day", pattern="^(day|week|month)$"),
    group_by: str | None = Query(None, pattern="^(channel|device|country|plan|segment)$"),
) -> dict:
    start, end = _range(start_date, end_date, days=59)
    return metrics.session_metrics(start, end, granularity, group_by)


# ---------------------------------------------------------------------------
# Funnels
# ---------------------------------------------------------------------------
@router.get("/funnels")
def funnels() -> list[dict]:
    rows = app_db.list_funnels()
    for row in rows:
        row["stages"] = json.loads(row.pop("stages_json"))
    return rows


@router.post("/funnels")
def create_funnel(payload: CreateFunnelRequest) -> dict:
    event_names = {
        row["event_name"]
        for row in query_rows("SELECT DISTINCT event_name FROM analytics.events")
    }
    invalid = [stage.event_name for stage in payload.stages if stage.event_name not in event_names]
    if invalid:
        raise AppError(
            "INVALID_FUNNEL",
            "Funnel stages reference unknown event names.",
            400,
            {"invalid_event_names": invalid, "available_event_names": sorted(event_names)},
        )
    funnel_id = f"funnel_{abs(hash(payload.name)) % 10_000_000}"
    app_db.create_funnel(
        {
            "id": funnel_id,
            "name": payload.name,
            "description": payload.description,
            "stages": [stage.model_dump() for stage in payload.stages],
            "window_days": payload.window_days,
        }
    )
    return {"funnel_id": funnel_id, **payload.model_dump()}


def _funnel_stages(payload: FunnelAnalyzeRequest) -> tuple[list[dict], str, int]:
    if payload.stages:
        return [s.model_dump() for s in payload.stages], payload.name, payload.window_days
    record = app_db.get_funnel(payload.funnel_id)
    if not record:
        raise NotFoundError(f"Funnel '{payload.funnel_id}' not found.")
    return (
        json.loads(record["stages_json"]),
        record["name"],
        payload.window_days or int(record["window_days"]),
    )


@router.post("/funnels/analyze")
def funnel_analyze(payload: FunnelAnalyzeRequest) -> dict:
    stages, name, window = _funnel_stages(payload)
    start, end = _range(payload.start_date, payload.end_date, days=59)
    return analyze_funnel(
        stages,
        start,
        end,
        window_days=window,
        group_by=payload.group_by,
        compare_period=payload.compare_period,
        funnel_id=payload.funnel_id,
        name=name,
    )


@router.get("/funnels/{funnel_id}/analyze")
def funnel_analyze_get(
    funnel_id: str,
    start_date: date | None = None,
    end_date: date | None = None,
    window_days: int | None = None,
    group_by: str | None = Query(None, pattern="^(channel|device|country|plan|segment)$"),
    compare_period: bool = True,
) -> dict:
    payload = FunnelAnalyzeRequest(
        funnel_id=funnel_id,
        start_date=start_date,
        end_date=end_date,
        window_days=window_days or 14,
        group_by=group_by,
        compare_period=compare_period,
    )
    return funnel_analyze(payload)


# ---------------------------------------------------------------------------
# Retention and segments
# ---------------------------------------------------------------------------
@router.get("/retention")
def retention_view(
    cohort_type: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    start_date: date | None = None,
    end_date: date | None = None,
    group_by: str | None = Query(None, pattern="^(channel|device|country|plan|segment)$"),
    periods: list[int] | None = Query(None),
) -> dict:
    start, end = _range(start_date, end_date, days=90)
    return retention.get_retention(cohort_type, start, end, group_by=group_by, periods=periods)


@router.get("/segments")
def segment_view(metric: str = "retention_d7") -> dict:
    return {
        "segments": segments.segment_summary(),
        "comparison": segments.segment_metric_comparison(metric),
    }


@router.get("/segments/comparison")
def segment_comparison(metric: str = "retention_d7") -> dict:
    return segments.segment_metric_comparison(metric)


@router.get("/segments/{segment}/users")
def segment_users(segment: str, limit: int = 50, offset: int = 0) -> dict:
    return segments.segment_users(segment, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Experiments and anomalies
# ---------------------------------------------------------------------------
@router.get("/experiments")
def experiment_list() -> list[dict]:
    return experiments_engine.list_experiments()


@router.get("/experiments/{experiment_id}")
def experiment_detail(experiment_id: str) -> dict:
    result = experiments_engine.analyze_experiment(experiment_id)
    if not result:
        raise NotFoundError(f"Experiment '{experiment_id}' not found.")
    return result


@router.get("/anomalies")
def anomalies(
    start_date: date | None = None,
    end_date: date | None = None,
    severity: str | None = Query(None, pattern="^(low|medium|high|critical)$"),
    limit: int = 100,
) -> dict:
    start, end = _range(start_date, end_date, days=179)
    sql = (
        "SELECT anomaly_id, metric_key, period_start, granularity, observed_value, "
        "baseline_value, deviation, robust_z, severity, method, sample_size, status, "
        "supporting_json, detected_at FROM analytics.anomaly_events "
        "WHERE period_start BETWEEN ? AND ?"
    )
    params: list = [start.isoformat(), end.isoformat()]
    if severity:
        sql += " AND severity = ?"
        params.append(severity)
    sql += " ORDER BY period_start DESC, ABS(robust_z) DESC LIMIT ?"
    params.append(min(max(limit, 1), 500))
    rows = query_rows(sql, params)
    return {"start_date": start.isoformat(), "end_date": end.isoformat(), "rows": rows}


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------
@router.post("/copilot/ask")
def copilot_ask(payload: AskRequest) -> dict:
    return orchestrator.answer(payload.question, payload.conversation_id)


@router.get("/copilot/interactions")
def copilot_interactions(limit: int = 50, offset: int = 0) -> list[dict]:
    rows = app_db.list_ai_interactions(limit=limit, offset=offset)
    return [_load_json_fields(row, ("sections_json", "evidence_json")) for row in rows]


@router.get("/copilot/interactions/{interaction_id}")
def copilot_interaction(interaction_id: str) -> dict:
    row = app_db.get_ai_interaction(interaction_id)
    if not row:
        raise NotFoundError("Interaction not found.")
    return _load_json_fields(row, ("sections_json", "evidence_json"))


# ---------------------------------------------------------------------------
# Text-to-SQL
# ---------------------------------------------------------------------------
@router.post("/sql/ask")
def sql_ask(payload: AskRequest) -> dict:
    return sql_pipeline.answer_question(payload.question, payload.conversation_id)


@router.post("/sql/validate")
def sql_validate(payload: SqlRequest) -> dict:
    return validate_sql(payload.sql).as_dict()


@router.post("/sql/execute")
def sql_execute(payload: SqlRequest) -> dict:
    return execute_sql(payload.sql)


@router.get("/history")
def history(limit: int = 50, offset: int = 0, status: str | None = None) -> list[dict]:
    return sql_pipeline.history(limit=limit, offset=offset, status=status)


@router.get("/history/{query_id}")
def history_detail(query_id: str) -> dict:
    row = app_db.get_query_history(query_id)
    if not row:
        raise NotFoundError("Query not found.")
    return _load_json_fields(row, ("result_preview", "columns_json", "chart_json", "sql_params"))


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
@router.get("/reports")
def report_list(limit: int = 50, offset: int = 0) -> list[dict]:
    return reports.list_reports(limit=limit, offset=offset)


@router.post("/reports")
def report_create(payload: ReportRequest) -> dict:
    return reports.create_report(
        payload.title,
        question=payload.question,
        interaction_id=payload.interaction_id,
        query_id=payload.query_id,
    )


@router.get("/reports/{report_id}")
def report_detail(report_id: str) -> dict:
    row = reports.get_report(report_id)
    if not row:
        raise NotFoundError("Report not found.")
    return row


@router.get("/reports/{report_id}/html", response_class=HTMLResponse)
def report_html(report_id: str) -> HTMLResponse:
    row = reports.get_report(report_id)
    if not row:
        raise NotFoundError("Report not found.")
    return HTMLResponse(content=row["content_html"])


@router.get("/reports/{report_id}/markdown", response_class=PlainTextResponse)
def report_markdown(report_id: str) -> PlainTextResponse:
    row = reports.get_report(report_id)
    if not row:
        raise NotFoundError("Report not found.")
    return PlainTextResponse(content=row["content_md"])


# ---------------------------------------------------------------------------
# Data explorer and operations
# ---------------------------------------------------------------------------
@router.get("/data/users")
def data_users(
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    segment: str | None = None,
) -> dict:
    return metrics.list_users(limit=limit, offset=offset, search=search, segment=segment)


@router.get("/data/users/{user_id}")
def data_user_detail(user_id: str) -> dict:
    row = metrics.get_user_detail(user_id)
    if not row:
        raise NotFoundError("User not found.")
    return row


@router.get("/data/events")
def data_events(
    limit: int = 50,
    offset: int = 0,
    user_id: str | None = None,
    event_name: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    return metrics.list_events(limit, offset, user_id, event_name, start_date, end_date)


@router.get("/data/subscriptions")
def data_subscriptions(limit: int = 50, offset: int = 0, status: str | None = None) -> dict:
    return metrics.list_subscriptions(limit, offset, status)


@router.get("/data/sessions")
def data_sessions(limit: int = 50, offset: int = 0, user_id: str | None = None) -> dict:
    return metrics.list_sessions(limit, offset, user_id)


@router.get("/metric-definitions")
def metric_definitions() -> list[dict]:
    return metrics.metric_definitions()


@router.get("/ingestion-runs")
def ingestion_runs(limit: int = 20) -> list[dict]:
    rows = app_db.list_ingestion_runs(limit=limit)
    return [_load_json_fields(row, ("details_json",)) for row in rows]


@router.get("/data-quality")
def data_quality(run_id: str | None = None, limit: int = 200) -> list[dict]:
    rows = app_db.list_quality_issues(run_id=run_id, limit=limit)
    return [_load_json_fields(row, ("sample_json",)) for row in rows]


@router.get("/audit")
def audit(limit: int = 100, offset: int = 0, event_type: str | None = None) -> list[dict]:
    return app_db.list_audit(limit=limit, offset=offset, event_type=event_type)


@router.post("/admin/ingest")
def admin_ingest(
    payload: IngestRequest,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    settings = get_settings()
    if settings.admin_api_token and x_admin_token != settings.admin_api_token:
        raise HTTPException(status_code=403, detail="Invalid admin token.")
    reset_connections()
    summary = run_pipeline(settings, force_generate=payload.force_generate)
    return {"status": "success", "summary": summary}
