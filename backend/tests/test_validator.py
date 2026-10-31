from __future__ import annotations

import pytest

from app.core.errors import SqlRejectedError
from app.text_to_sql.validator import require_valid_sql, schema_prompt, validate_sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT user_id, event_name FROM analytics.events LIMIT 10",
        "SELECT acquisition_channel, COUNT(*) AS users FROM analytics.users GROUP BY 1",
        "SELECT * FROM analytics.daily_metrics WHERE metric_date >= '2026-09-01'",
        "SELECT AVG(checkout_conversion_rate) AS rate FROM analytics.daily_metrics",
        "WITH daily AS (SELECT metric_date, registered_users FROM analytics.daily_metrics) "
        "SELECT SUM(registered_users) FROM daily",
    ],
)
def test_accepts_read_only_allowlisted_queries(sql: str) -> None:
    result = validate_sql(sql)
    assert result.valid, result.errors
    assert result.normalized_sql
    assert result.tables


@pytest.mark.parametrize(
    ("sql", "fragment"),
    [
        ("DROP TABLE analytics.events", "Forbidden keyword"),
        ("DELETE FROM analytics.events", "Forbidden keyword"),
        ("UPDATE analytics.events SET event_name = 'x'", "Forbidden keyword"),
        ("PRAGMA database_list", "Forbidden keyword"),
        ("ATTACH 'other.db' AS other", "Forbidden keyword"),
        ("SELECT * FROM analytics.events; SELECT * FROM analytics.users", "single SQL statement"),
        ("SELECT * FROM raw.events", "not allowed"),
        ("SELECT secret FROM analytics.users", "Unknown or disallowed column"),
        ("SELECT * FROM read_csv_auto('secrets.csv')", "Table functions"),
        ("SELECT * FROM information_schema.tables", "System or external table"),
        ("SELECT * FROM analytics.events e JOIN analytics.users u ON e.user_id = u.user_id "
         "JOIN analytics.sessions s ON s.user_id = u.user_id "
         "JOIN analytics.subscriptions x ON x.user_id = u.user_id "
         "JOIN analytics.experiments y ON y.experiment_id = x.user_id", "Too many joins"),
        ("WITH RECURSIVE x AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM x) SELECT * FROM x", "Recursive"),
        ("SELECT 1 INTO copied", "SELECT ... INTO"),
    ],
)
def test_rejects_unsafe_or_unknown_sql(sql: str, fragment: str) -> None:
    result = validate_sql(sql)
    assert not result.valid
    assert any(fragment.lower() in error.lower() for error in result.errors), result.errors


def test_allows_one_trailing_semicolon() -> None:
    assert validate_sql("SELECT * FROM analytics.events;").valid


def test_rejects_empty_and_null_bytes() -> None:
    assert "empty" in validate_sql("   ").errors[0].lower()
    assert "null byte" in validate_sql("SELECT 1\x00").errors[0].lower()


def test_rejects_comments_hiding_forbidden_keywords() -> None:
    result = validate_sql("SELECT * FROM analytics.events -- drop table")
    assert not result.valid
    assert "Forbidden keyword" in result.errors[0]


def test_require_valid_sql_raises_application_error() -> None:
    with pytest.raises(SqlRejectedError) as exc:
        require_valid_sql("DROP TABLE analytics.events")
    assert exc.value.status_code == 400
    assert exc.value.code == "SQL_REJECTED"


def test_schema_prompt_lists_allowed_tables() -> None:
    prompt = schema_prompt()
    assert "analytics.events:" in prompt
    assert "analytics.daily_metrics:" in prompt
    assert "user_id" in prompt
