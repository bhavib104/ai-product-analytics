# Implementation status

## Backend

- FastAPI application with all planned routes, CORS, request IDs, error envelope,
  lifespan initialization, and optional static frontend serving.
- DuckDB analytics store and SQLite operational store implemented.
- Synthetic data pipeline implemented and run successfully.
- Deterministic Text-to-SQL validator, generator, executor, and pipeline implemented.
- AI provider abstraction with deterministic default; 11 typed read-only tools;
  single orchestrator with evidence validation and deterministic fallback.
- Markdown/HTML report builder and persistence implemented.

## Frontend

- React + TypeScript + Vite application with 8 routes and shared UI/chart/layout components.
- All pages connected to real backend APIs with loading, error, and empty states.
- `npm run typecheck`, `npm run test` (10 tests), and `npm run build` pass.

## Data

- Users: 5,000
- Events: 73,067
- Sessions: 15,077
- Subscriptions: 570
- Experiment assignments: 2,356
- Daily metrics: 180
- Weekly metrics: 26
- Feature adoption daily: 1,772
- User metrics: 5,000
- Cohort retention: 5,856
- Retention by dimension: 17,384
- User segments: 5,000
- Experiment results: 4
- Anomaly events: 3
- Metric definitions: 18

## Quality and evaluation

- Data quality: 97,601 rows read, 96,089 valid, 1,587 rejected.
- Backend tests: 78 passing.
- Ruff: no errors.
- Evaluation: 20/20 cases passed.
- Copilot tool calls: 21/21 successful.
- SQL safety checks: 16/16 passed.
- Citation coverage: 1.0.
- Median Copilot latency: 185.5 ms; p95: 1086 ms.

## Known limitations

- Bundle size warning remains (784.20 kB / 226.44 kB gzip).
- Docker and Ollama are optional and were not running during verification.
- Evaluation uses the local synthetic dataset; no production data was used.
- Advanced features such as RAG, MCP, vector databases, streaming, multi-tenancy,
  and campaign execution are intentionally out of MVP scope.
