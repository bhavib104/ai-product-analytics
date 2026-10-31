# Evaluation

Evaluation harness: `backend/app/evaluation/run.py`.

- 20 cases: 14 Copilot, 6 Text-to-SQL.
- 20/20 passed.
- 21/21 Copilot tool calls successful.
- SQL accuracy: 6/6.
- SQL safety: 16/16.
- Citation coverage: 1.0.
- Median latency: 185.5 ms; p95: 1086 ms.
- Expected values are recomputed independently from raw CSVs.
