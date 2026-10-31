# Architecture

Modular monolith. Backend: FastAPI + DuckDB + SQLite. Frontend: React + TypeScript + Vite.

- DuckDB stores raw, staging, analytics, and quarantine tables.
- SQLite stores operational state: query history, AI interactions, reports,
  ingestion runs, data-quality issues, audit records, conversations, funnel definitions.
- All authoritative metrics are computed in code or SQL; the LLM only narrates evidence.
- Text-to-SQL uses reviewed deterministic templates, validation, read-only execution,
  allowlists, timeouts, row caps, and query logging.
- AI uses one orchestrator and 11 typed read-only tools.
