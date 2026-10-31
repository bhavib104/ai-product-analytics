"""Read-only SQL execution with row caps and timing."""

from __future__ import annotations

import contextlib
import math
import time
from datetime import date, datetime
from datetime import time as dt_time
from decimal import Decimal

import numpy as np

from app.core.config import get_settings
from app.core.errors import AppError, QueryTimeoutError
from app.db.duck import connect_readonly
from app.text_to_sql.validator import ValidationResult, require_valid_sql


def _jsonable(value):
    if value is None:
        return None
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return value


def _column_types(df) -> list[dict]:
    return [
        {"name": str(name), "type": str(dtype)}
        for name, dtype in zip(df.columns, df.dtypes, strict=False)
    ]


def execute_sql(sql: str, params: list | tuple | None = None) -> dict:
    settings = get_settings()
    validation: ValidationResult = require_valid_sql(sql)
    normalized = (validation.normalized_sql or sql).strip().rstrip(";")
    max_rows = settings.sql_max_rows
    wrapped = f"SELECT * FROM ({normalized}) AS _validated LIMIT {max_rows + 1}"
    conn = connect_readonly()
    with contextlib.suppress(Exception):
        conn.execute(f"SET statement_timeout='{settings.sql_timeout_seconds}s'")
    started = time.perf_counter()
    try:
        df = conn.execute(wrapped, list(params or [])).fetch_df()
    except Exception as exc:
        message = str(exc)
        if "timeout" in message.lower() or "interrupted" in message.lower():
            raise QueryTimeoutError() from exc
        raise AppError(
            "SQL_EXECUTION_ERROR",
            "The validated query failed during execution.",
            400,
            {"error": message, "sql": normalized},
        ) from exc
    duration_ms = int((time.perf_counter() - started) * 1000)
    truncated = len(df) > max_rows
    if truncated:
        df = df.head(max_rows)
    rows = [
        {str(key): _jsonable(value) for key, value in record.items()}
        for record in df.to_dict(orient="records")
    ]
    return {
        "sql": normalized,
        "rows": rows,
        "columns": _column_types(df),
        "row_count": len(rows),
        "truncated": truncated,
        "duration_ms": duration_ms,
        "validation": validation.as_dict(),
    }
