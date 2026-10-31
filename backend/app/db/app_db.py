"""SQLite operational store.

Holds query history, AI interactions/tool calls, reports, ingestion runs,
data-quality issues, audit events, conversation metadata and funnel definitions.
Analytical facts live in DuckDB.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    title TEXT
);

CREATE TABLE IF NOT EXISTS query_history (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    question TEXT NOT NULL,
    generated_sql TEXT,
    sql_params TEXT,
    status TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    row_count INTEGER,
    duration_ms INTEGER,
    error TEXT,
    result_preview TEXT,
    columns_json TEXT,
    chart_json TEXT,
    answer TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_query_history_created ON query_history(created_at DESC);

CREATE TABLE IF NOT EXISTS ai_interactions (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    sections_json TEXT,
    evidence_json TEXT,
    sql_text TEXT,
    provider TEXT,
    model TEXT,
    prompt_version TEXT,
    latency_ms INTEGER,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    estimated_cost_usd REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_interactions_created ON ai_interactions(created_at DESC);

CREATE TABLE IF NOT EXISTS ai_tool_calls (
    id TEXT PRIMARY KEY,
    interaction_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    arguments_json TEXT,
    status TEXT NOT NULL,
    duration_ms INTEGER,
    result_summary TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (interaction_id) REFERENCES ai_interactions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    question TEXT,
    interaction_id TEXT,
    query_id TEXT,
    format TEXT NOT NULL,
    content_md TEXT NOT NULL,
    content_html TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    rows_read INTEGER,
    rows_valid INTEGER,
    rows_rejected INTEGER,
    details_json TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS data_quality_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    table_name TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    sample_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    actor TEXT,
    payload_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at DESC);

CREATE TABLE IF NOT EXISTS funnel_definitions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    stages_json TEXT NOT NULL,
    window_days INTEGER NOT NULL DEFAULT 14,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def init_app_db(path: Path | None = None) -> None:
    settings = get_settings()
    target = Path(path or settings.app_db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def app_db(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    settings = get_settings()
    target = Path(path or settings.app_db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def insert_query_history(record: dict) -> None:
    with app_db() as conn:
        conn.execute(
            """INSERT INTO query_history
            (id, conversation_id, question, generated_sql, sql_params, status, provider,
             model, row_count, duration_ms, error, result_preview, columns_json, chart_json,
             answer, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                record["id"],
                record.get("conversation_id"),
                record["question"],
                record.get("generated_sql"),
                _json(record.get("sql_params")),
                record["status"],
                record.get("provider"),
                record.get("model"),
                record.get("row_count"),
                record.get("duration_ms"),
                record.get("error"),
                _json(record.get("result_preview")),
                _json(record.get("columns")),
                _json(record.get("chart")),
                record.get("answer"),
                record.get("created_at") or now_iso(),
            ),
        )


def list_query_history(limit: int = 50, offset: int = 0, status: str | None = None):
    with app_db() as conn:
        sql = "SELECT * FROM query_history"
        params: list = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_query_history(query_id: str) -> dict | None:
    with app_db() as conn:
        row = conn.execute("SELECT * FROM query_history WHERE id = ?", (query_id,)).fetchone()
        return dict(row) if row else None


def insert_ai_interaction(record: dict) -> None:
    with app_db() as conn:
        conn.execute(
            """INSERT INTO ai_interactions
            (id, conversation_id, question, answer, sections_json, evidence_json, sql_text,
             provider, model, prompt_version, latency_ms, prompt_tokens, completion_tokens,
             estimated_cost_usd, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                record["id"],
                record.get("conversation_id"),
                record["question"],
                record["answer"],
                _json(record.get("sections")),
                _json(record.get("evidence")),
                record.get("sql"),
                record.get("provider"),
                record.get("model"),
                record.get("prompt_version"),
                record.get("latency_ms"),
                record.get("prompt_tokens"),
                record.get("completion_tokens"),
                record.get("estimated_cost_usd"),
                record.get("created_at") or now_iso(),
            ),
        )


def insert_tool_call(record: dict) -> None:
    with app_db() as conn:
        conn.execute(
            """INSERT INTO ai_tool_calls
            (id, interaction_id, tool_name, arguments_json, status, duration_ms,
             result_summary, error, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                record["id"],
                record["interaction_id"],
                record["tool_name"],
                _json(record.get("arguments")),
                record["status"],
                record.get("duration_ms"),
                record.get("result_summary"),
                record.get("error"),
                record.get("created_at") or now_iso(),
            ),
        )


def get_ai_interaction(interaction_id: str) -> dict | None:
    with app_db() as conn:
        row = conn.execute(
            "SELECT * FROM ai_interactions WHERE id = ?", (interaction_id,)
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["tool_calls"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM ai_tool_calls WHERE interaction_id = ? ORDER BY created_at",
                (interaction_id,),
            ).fetchall()
        ]
        return result


def list_ai_interactions(limit: int = 50, offset: int = 0):
    with app_db() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM ai_interactions ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        ]


def insert_report(record: dict) -> None:
    with app_db() as conn:
        conn.execute(
            """INSERT INTO reports
            (id, title, question, interaction_id, query_id, format, content_md, content_html,
             metadata_json, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                record["id"],
                record["title"],
                record.get("question"),
                record.get("interaction_id"),
                record.get("query_id"),
                record["format"],
                record["content_md"],
                record["content_html"],
                _json(record.get("metadata")),
                record.get("created_at") or now_iso(),
            ),
        )


def list_reports(limit: int = 50, offset: int = 0):
    with app_db() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, title, question, interaction_id, query_id, format, created_at "
                "FROM reports ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        ]


def get_report(report_id: str) -> dict | None:
    with app_db() as conn:
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        return dict(row) if row else None


def insert_audit(event_type: str, payload: dict, actor: str = "system") -> None:
    with app_db() as conn:
        conn.execute(
            "INSERT INTO audit_events (event_type, actor, payload_json, created_at) "
            "VALUES (?,?,?,?)",
            (event_type, actor, _json(payload), now_iso()),
        )


def list_audit(limit: int = 100, offset: int = 0, event_type: str | None = None):
    with app_db() as conn:
        sql = "SELECT * FROM audit_events"
        params: list = []
        if event_type:
            sql += " WHERE event_type = ?"
            params.append(event_type)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def start_ingestion_run(run_id: str, source: str) -> None:
    with app_db() as conn:
        conn.execute(
            "INSERT INTO ingestion_runs (id, source, status, started_at) VALUES (?,?,?,?)",
            (run_id, source, "RUNNING", now_iso()),
        )


def finish_ingestion_run(run_id: str, status: str, summary: dict, error: str | None = None) -> None:
    with app_db() as conn:
        conn.execute(
            """UPDATE ingestion_runs SET status=?, finished_at=?, rows_read=?, rows_valid=?,
            rows_rejected=?, details_json=?, error=? WHERE id=?""",
            (
                status,
                now_iso(),
                summary.get("rows_read"),
                summary.get("rows_valid"),
                summary.get("rows_rejected"),
                _json(summary),
                error,
                run_id,
            ),
        )


def insert_quality_issue(run_id: str, table_name: str, issue_type: str, row_count: int, sample):
    with app_db() as conn:
        conn.execute(
            "INSERT INTO data_quality_issues "
            "(run_id, table_name, issue_type, row_count, sample_json, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (run_id, table_name, issue_type, row_count, _json(sample), now_iso()),
        )


def list_ingestion_runs(limit: int = 20):
    with app_db() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM ingestion_runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        ]


def list_quality_issues(run_id: str | None = None, limit: int = 200):
    with app_db() as conn:
        if run_id:
            rows = conn.execute(
                "SELECT * FROM data_quality_issues WHERE run_id=? ORDER BY row_count DESC LIMIT ?",
                (run_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM data_quality_issues ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def seed_funnel_definitions() -> None:
    definitions = [
        {
            "id": "default",
            "name": "Core activation funnel",
            "description": (
                "Registration → account activation → first feature usage → "
                "subscription selection → purchase."
            ),
            "stages": [
                {"key": "registration", "label": "User Registration", "event_name": "user_registered"},
                {"key": "activation", "label": "Account Activation", "event_name": "account_activated"},
                {"key": "feature", "label": "First Feature Usage", "event_name": "feature_used"},
                {"key": "checkout", "label": "Subscription Selection", "event_name": "checkout_started"},
                {"key": "purchase", "label": "Purchase", "event_name": "purchase_completed"},
            ],
            "window_days": 14,
            "is_default": 1,
        },
        {
            "id": "onboarding",
            "name": "Activation only",
            "description": "Registration → activation → first feature usage.",
            "stages": [
                {"key": "registration", "label": "Registration", "event_name": "user_registered"},
                {"key": "activation", "label": "Activation", "event_name": "account_activated"},
                {"key": "feature", "label": "First Feature Usage", "event_name": "feature_used"},
            ],
            "window_days": 7,
            "is_default": 0,
        },
    ]
    with app_db() as conn:
        for d in definitions:
            conn.execute(
                """INSERT OR IGNORE INTO funnel_definitions
                (id, name, description, stages_json, window_days, is_default, created_at)
                VALUES (?,?,?,?,?,?,?)""",
                (
                    d["id"],
                    d["name"],
                    d["description"],
                    _json(d["stages"]),
                    d["window_days"],
                    d["is_default"],
                    now_iso(),
                ),
            )


def list_funnels():
    with app_db() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM funnel_definitions ORDER BY is_default DESC, name"
            ).fetchall()
        ]


def create_funnel(record: dict) -> None:
    with app_db() as conn:
        conn.execute(
            """INSERT INTO funnel_definitions
            (id, name, description, stages_json, window_days, is_default, created_at)
            VALUES (?,?,?,?,?,?,?)""",
            (
                record["id"],
                record["name"],
                record.get("description"),
                _json(record["stages"]),
                record.get("window_days", 14),
                0,
                now_iso(),
            ),
        )


def get_funnel(funnel_id: str) -> dict | None:
    with app_db() as conn:
        row = conn.execute(
            "SELECT * FROM funnel_definitions WHERE id = ?", (funnel_id,)
        ).fetchone()
        return dict(row) if row else None


def ensure_conversation(conversation_id: str, title: str | None = None) -> None:
    with app_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO conversations (id, created_at, updated_at, title) "
            "VALUES (?,?,?,?)",
            (conversation_id, now_iso(), now_iso(), title),
        )
        conn.execute(
            "UPDATE conversations SET updated_at=? WHERE id=?", (now_iso(), conversation_id)
        )
