"""DuckDB analytical-store access.

The analytical database is written only by the data pipeline.  API requests use
read-only connections, and Text-to-SQL queries always go through the validator
and executor in ``app.text_to_sql``.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import duckdb
import pandas as pd

from app.core.config import get_settings
from app.core.errors import DataNotReadyError

logger = logging.getLogger(__name__)

_local = threading.local()
_lock = threading.Lock()


def _configure_readonly(conn: duckdb.DuckDBPyConnection) -> None:
    settings = get_settings()
    try:
        conn.execute(f"SET memory_limit='{settings.sql_memory_limit}'")
        conn.execute(f"SET threads={settings.sql_threads}")
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Could not set DuckDB limits: %s", exc)
    try:
        conn.execute("SET enable_external_access=false")
    except Exception as exc:  # pragma: no cover - depends on DuckDB version
        logger.debug("Could not disable external access: %s", exc)


def connect_readonly(path: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Return a thread-local read-only connection."""
    settings = get_settings()
    target = Path(path or settings.duckdb_path)
    if not target.exists():
        raise DataNotReadyError(
            f"Analytical database not found at {target}. Run: python -m app.pipeline.run"
        )
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = duckdb.connect(str(target), read_only=True)
        _configure_readonly(conn)
        _local.conn = conn
    return conn


def connect_readwrite(path: Path | None = None) -> duckdb.DuckDBPyConnection:
    settings = get_settings()
    target = Path(path or settings.duckdb_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(target))


def close_thread_connection() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        finally:
            _local.conn = None


def reset_connections() -> None:
    """Close all known thread-local read connections (used before ingestion)."""
    close_thread_connection()


def query_df(sql: str, params: list | tuple | None = None, path: Path | None = None) -> pd.DataFrame:
    conn = connect_readonly(path)
    return conn.execute(sql, params or []).fetch_df()


def query_rows(
    sql: str, params: list | tuple | None = None, path: Path | None = None
) -> list[dict]:
    df = query_df(sql, params, path)
    return df.to_dict(orient="records")


def data_ready() -> tuple[bool, str]:
    settings = get_settings()
    if not settings.duckdb_path.exists():
        return False, f"Missing {settings.duckdb_path}"
    try:
        conn = connect_readonly()
        row = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema='analytics' AND table_name='daily_metrics'"
        ).fetchone()
        if not row or row[0] == 0:
            return False, "analytics.daily_metrics is missing"
        return True, "ready"
    except Exception as exc:  # pragma: no cover - environment dependent
        return False, str(exc)


def reset_database(path: Path | None = None) -> None:
    """Delete the analytical database file (pipeline rebuild only)."""
    settings = get_settings()
    target = Path(path or settings.duckdb_path)
    with _lock:
        close_thread_connection()
        if target.exists():
            try:
                target.unlink()
            except PermissionError:
                # DuckDB may keep a WAL file open; try again after a short GC.
                import gc

                gc.collect()
                target.unlink()
