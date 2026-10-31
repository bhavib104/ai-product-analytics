# Security

- Synthetic data only; no PII.
- Credentials are not committed; `.env` is gitignored.
- DuckDB is read-only for AI SQL execution.
- SQLite operational store handles query history, AI interactions, audit records, and reports.
- No mandatory paid services; deterministic offline LLM mode is the default.
