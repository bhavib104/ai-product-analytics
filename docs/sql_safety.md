# SQL safety

- Single SELECT statement only.
- Destructive statements, DDL, DML, PRAGMA, ATTACH, COPY, INSTALL/LOAD, external table functions,
  system catalogs, and recursive CTEs are rejected.
- Allowlisted schemas: `raw`, `staging`, `analytics`, `quarantine`.
- Maximum 3 joins, subquery depth 2, 250 AST nodes.
- Row cap 500 and timeout 8 seconds.
- Generated SQL is displayed to the user and all executions are logged.
- Evaluation: 16/16 SQL safety checks passed.
