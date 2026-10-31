"""SQL validation for LLM-generated and user-submitted analytical SQL.

The validator is deliberately conservative.  It parses with sqlglot, permits a
single read-only SELECT/UNION/CTE statement, restricts tables and columns to the
documented analytical allow-list, and bounds joins, subquery depth and AST size.
The executor adds a row cap and runs on a read-only DuckDB connection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from app.analytics.definitions import ALLOWED_TABLES, allowed_table_names, table_columns
from app.core.config import get_settings
from app.core.errors import SqlRejectedError

FORBIDDEN_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|create|alter|truncate|attach|detach|copy|install|load|"
    r"pragma|export|import|grant|revoke|call|vacuum|checkpoint|use|set|replace|merge)\b",
    re.IGNORECASE,
)
FORBIDDEN_TABLE_FUNCTIONS = {
    "read_csv",
    "read_csv_auto",
    "read_parquet",
    "read_json",
    "read_json_auto",
    "read_ndjson",
    "read_ndjson_auto",
    "parquet_scan",
    "csv_scan",
    "json_scan",
    "glob",
    "sqlite_scan",
    "postgres_scan",
    "mysql_scan",
    "iceberg_scan",
    "delta_scan",
    "httpfs",
    "duckdb_extensions",
    "duckdb_settings",
    "duckdb_functions",
    "information_schema",
    "pg_catalog",
}
SYSTEM_SCHEMAS = {"information_schema", "pg_catalog", "system", "temp", "main"}
ALLOWED_SCHEMAS = {"analytics", "main", ""}
STATEMENT_TYPES = (exp.Select, exp.Union, exp.Intersect, exp.Except)
FORBIDDEN_NODE_NAMES = (
    "Insert",
    "Update",
    "Delete",
    "Create",
    "Drop",
    "Alter",
    "TruncateTable",
    "Command",
    "Pragma",
    "Attach",
    "Detach",
    "Copy",
    "Transaction",
    "Commit",
    "Rollback",
    "LoadData",
    "Export",
    "Into",
    "Grant",
    "Revoke",
    "Use",
    "Set",
    "Analyze",
    "Vacuum",
    "Checkpoint",
    "Merge",
)


@dataclass
class ValidationResult:
    valid: bool
    sql: str
    normalized_sql: str | None = None
    errors: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    joins: int = 0
    subquery_depth: int = 0
    ast_nodes: int = 0

    def as_dict(self) -> dict:
        return {
            "valid": self.valid,
            "sql": self.sql,
            "normalized_sql": self.normalized_sql,
            "errors": self.errors,
            "tables": self.tables,
            "columns": self.columns,
            "joins": self.joins,
            "subquery_depth": self.subquery_depth,
            "ast_nodes": self.ast_nodes,
        }


def _strip_literals(sql: str) -> str:
    sql = re.sub(r"'(?:''|[^'])*'", "''", sql)
    sql = re.sub(r'"(?:\"\"|[^"])*"', '""', sql)
    return sql


def _forbidden_node(expr: exp.Expression) -> str | None:
    for name in FORBIDDEN_NODE_NAMES:
        cls = getattr(exp, name, None)
        if cls is not None and isinstance(expr, cls):
            return name
    return None


def _subquery_depth(node: exp.Expression, depth: int = 0) -> int:
    if isinstance(node, (exp.Subquery, exp.CTE)):
        depth += 1
    deepest = depth
    for child in node.args.values():
        if isinstance(child, exp.Expression):
            deepest = max(deepest, _subquery_depth(child, depth))
        elif isinstance(child, list):
            for item in child:
                if isinstance(item, exp.Expression):
                    deepest = max(deepest, _subquery_depth(item, depth))
    return deepest


def validate_sql(sql: str, max_rows: int | None = None) -> ValidationResult:
    settings = get_settings()
    result = ValidationResult(valid=False, sql=sql)
    if not sql or not sql.strip():
        result.errors.append("SQL is empty.")
        return result
    if "\x00" in sql:
        result.errors.append("SQL contains a null byte.")
        return result
    stripped = _strip_literals(sql)
    match = FORBIDDEN_KEYWORDS.search(stripped)
    if match:
        result.errors.append(f"Forbidden keyword in SQL: {match.group(0).upper()}.")
        return result
    if ";" in sql.strip().rstrip(";"):
        result.errors.append("Only a single SQL statement is allowed.")
        return result

    try:
        statements = sqlglot.parse(sql, read="duckdb")
    except Exception as exc:
        result.errors.append(f"SQL could not be parsed: {exc}")
        return result
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        result.errors.append("Only a single SQL statement is allowed.")
        return result
    expr = statements[0]
    if not isinstance(expr, STATEMENT_TYPES):
        result.errors.append("Only read-only SELECT statements are allowed.")
        return result
    if isinstance(expr, exp.Select) and expr.args.get("into"):
        result.errors.append("SELECT ... INTO is not allowed.")
        return result

    for node in expr.walk():
        forbidden = _forbidden_node(node)
        if forbidden:
            result.errors.append(f"Forbidden SQL construct: {forbidden}.")
            return result
        if isinstance(node, exp.With) and node.args.get("recursive"):
            result.errors.append("Recursive CTEs are not allowed.")
            return result

    tables: set[str] = set()
    cte_names: set[str] = set()
    cte_columns: set[str] = set()
    select_aliases: set[str] = set()
    for node in expr.walk():
        if isinstance(node, exp.CTE):
            name = node.alias
            if name:
                cte_names.add(name.lower())
            inner = node.this
            if isinstance(inner, exp.Select):
                for select in inner.selects:
                    alias = select.alias_or_name
                    if alias and alias != "*":
                        cte_columns.add(alias.lower())
        if isinstance(node, exp.Select):
            for select in node.selects:
                # Only explicit aliases (``COUNT(*) AS users``) should widen the
                # known-column set.  Adding every bare projection would let
                # ``SELECT secret FROM analytics.users`` validate because the
                # unknown identifier is also its own implicit alias.
                if not isinstance(select, exp.Alias):
                    continue
                alias = select.alias_or_name
                if alias and alias != "*":
                    select_aliases.add(alias.lower())

    alias_map: dict[str, str] = {}
    for node in expr.find_all(exp.Table):
        table_name = (node.name or "").lower()
        schema = (node.db or "").lower()
        catalog = (node.catalog or "").lower()
        if isinstance(node.this, (exp.Anonymous, exp.Func)):
            result.errors.append("Table functions are not allowed.")
            return result
        if table_name in FORBIDDEN_TABLE_FUNCTIONS or schema in SYSTEM_SCHEMAS - {"main"}:
            result.errors.append(f"System or external table is not allowed: {table_name}.")
            return result
        if catalog:
            result.errors.append("Cross-catalog references are not allowed.")
            return result
        if schema and schema not in ALLOWED_SCHEMAS:
            result.errors.append(f"Schema '{schema}' is not allowed.")
            return result
        if table_name not in allowed_table_names() and table_name not in cte_names:
            result.errors.append(f"Table '{table_name}' is not in the allow-list.")
            return result
        if table_name not in cte_names:
            tables.add(table_name)
        if node.alias:
            alias_map[node.alias.lower()] = table_name

    joins = len(list(expr.find_all(exp.Join)))
    if joins > settings.sql_max_joins:
        result.errors.append(
            f"Too many joins: {joins}. The maximum is {settings.sql_max_joins}."
        )
    depth = _subquery_depth(expr)
    if depth > settings.sql_max_subquery_depth:
        result.errors.append(
            f"Subquery depth {depth} exceeds the maximum of {settings.sql_max_subquery_depth}."
        )
    nodes = len(list(expr.walk()))
    if nodes > settings.sql_max_ast_nodes:
        result.errors.append(
            f"Query has {nodes} AST nodes; the maximum is {settings.sql_max_ast_nodes}."
        )

    known_columns: set[str] = set(cte_columns) | select_aliases
    for table in tables:
        known_columns |= {c.lower() for c in table_columns(table)}
    used_columns: set[str] = set()
    for column in expr.find_all(exp.Column):
        name = (column.name or "").lower()
        qualifier = (column.table or "").lower()
        if name in {"*", ""}:
            continue
        used_columns.add(column.sql(dialect="duckdb"))
        if qualifier:
            resolved = alias_map.get(qualifier, qualifier)
            if resolved in cte_names:
                continue
            if resolved not in tables:
                result.errors.append(f"Unknown table alias '{qualifier}'.")
                continue
            if name not in {c.lower() for c in table_columns(resolved)}:
                result.errors.append(f"Column '{name}' is not allowed on table '{resolved}'.")
        elif name not in known_columns:
            result.errors.append(f"Unknown or disallowed column '{name}'.")
    if result.errors:
        return result

    result.valid = True
    result.normalized_sql = expr.sql(dialect="duckdb")
    result.tables = sorted(tables)
    result.columns = sorted(used_columns)
    result.joins = joins
    result.subquery_depth = depth
    result.ast_nodes = nodes
    return result


def require_valid_sql(sql: str) -> ValidationResult:
    result = validate_sql(sql)
    if not result.valid:
        raise SqlRejectedError(
            "Generated SQL failed validation and was not executed.",
            details={"errors": result.errors, "sql": sql},
        )
    return result


def schema_prompt() -> str:
    """Compact schema description for optional LLM SQL generation."""
    lines = []
    for table, meta in ALLOWED_TABLES.items():
        cols = ", ".join(f"{name} {dtype}" for name, dtype in meta["columns"].items())
        lines.append(f"analytics.{table}: {cols}")
    return "\n".join(lines)
