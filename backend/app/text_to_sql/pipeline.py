"""Question → reviewed SQL → validated read-only execution → logged result."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.db import app_db
from app.text_to_sql.executor import execute_sql
from app.text_to_sql.generator import generate_sql


def _chart(hint: dict | None, rows: list[dict], columns: list[dict]) -> dict:
    if not hint:
        return {"type": "table", "columns": columns, "data": rows}
    kind = hint.get("type", "table")
    if kind == "table" or not rows:
        return {"type": "table", "columns": columns, "data": rows}
    if kind == "funnel":
        first = rows[0]
        data = [
            {"stage": key.replace("_", " ").title(), "users": value}
            for key, value in first.items()
            if isinstance(value, (int, float))
        ]
        return {"type": "funnel", "data": data}
    return {
        "type": kind,
        "x": hint.get("x"),
        "y": hint.get("y"),
        "series": hint.get("series"),
        "data": rows,
    }


def _fmt(value) -> str:
    if isinstance(value, float):
        if abs(value) <= 1.5:
            return f"{value:.4f}"
        return f"{value:,.2f}"
    return str(value)


def summarize_result(rows: list[dict], columns: list[dict]) -> str:
    if not rows:
        return "The validated query returned no rows for the selected period."
    names = [c["name"] for c in columns]
    if len(rows) == 1:
        parts = [f"{name} = {_fmt(rows[0].get(name))}" for name in names[:8]]
        return "The query returned one row: " + ", ".join(parts) + "."
    first = rows[0]
    parts = [f"{name} = {_fmt(first.get(name))}" for name in names[:5]]
    return (
        f"The query returned {len(rows)} rows. The first row is: "
        + ", ".join(parts)
        + ". Values come directly from the validated SQL result."
    )


def answer_question(question: str, conversation_id: str | None = None) -> dict:
    query_id = f"qry_{uuid.uuid4().hex[:12]}"
    created_at = datetime.now(UTC).isoformat()
    generated = generate_sql(question)
    if not generated:
        answer = (
            "I could not map this question to a reviewed SQL template. The MVP does not "
            "free-form generate SQL without a matching template. Try asking about registrations, "
            "activation, purchase conversion, checkout conversion, retention, DAU/MAU, MRR, "
            "cancellations, feature adoption, experiments or anomalies."
        )
        app_db.insert_query_history(
            {
                "id": query_id,
                "conversation_id": conversation_id,
                "question": question,
                "generated_sql": None,
                "sql_params": None,
                "status": "UNSUPPORTED",
                "provider": "deterministic-template",
                "model": "template-v1",
                "row_count": 0,
                "duration_ms": 0,
                "error": "No reviewed template matched the question.",
                "result_preview": [],
                "columns": [],
                "chart": None,
                "answer": answer,
                "created_at": created_at,
            }
        )
        return {
            "query_id": query_id,
            "status": "unsupported",
            "question": question,
            "answer": answer,
            "sql": None,
            "rows": [],
            "columns": [],
            "chart": {"type": "table", "data": []},
            "template": None,
            "provider": "deterministic-template",
            "model": "template-v1",
        }

    try:
        result = execute_sql(generated["sql"])
    except Exception as exc:
        app_db.insert_query_history(
            {
                "id": query_id,
                "conversation_id": conversation_id,
                "question": question,
                "generated_sql": generated["sql"],
                "sql_params": None,
                "status": "REJECTED" if getattr(exc, "code", "") == "SQL_REJECTED" else "FAILED",
                "provider": generated.get("provider"),
                "model": generated.get("model"),
                "row_count": 0,
                "duration_ms": 0,
                "error": str(exc),
                "result_preview": [],
                "columns": [],
                "chart": None,
                "answer": None,
                "created_at": created_at,
            }
        )
        raise

    chart = _chart(generated.get("chart"), result["rows"], result["columns"])
    answer = summarize_result(result["rows"], result["columns"])
    record = {
        "id": query_id,
        "conversation_id": conversation_id,
        "question": question,
        "generated_sql": result["sql"],
        "sql_params": None,
        "status": "SUCCESS",
        "provider": generated.get("provider"),
        "model": generated.get("model"),
        "row_count": result["row_count"],
        "duration_ms": result["duration_ms"],
        "error": None,
        "result_preview": result["rows"][:20],
        "columns": result["columns"],
        "chart": chart,
        "answer": answer,
        "created_at": created_at,
    }
    app_db.insert_query_history(record)
    return {
        "query_id": query_id,
        "status": "success",
        "question": question,
        "answer": answer,
        "sql": result["sql"],
        "rows": result["rows"],
        "columns": result["columns"],
        "row_count": result["row_count"],
        "truncated": result["truncated"],
        "duration_ms": result["duration_ms"],
        "chart": chart,
        "validation": result["validation"],
        "template": generated.get("template"),
        "provider": generated.get("provider"),
        "model": generated.get("model"),
        "explanation": generated.get("explanation"),
    }


def history(limit: int = 50, offset: int = 0, status: str | None = None) -> list[dict]:
    return app_db.list_query_history(limit=limit, offset=offset, status=status)
