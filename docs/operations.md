# Operations

- Generate and load data: `python -m app.pipeline.run --generate`
- Re-run pipeline without regeneration: `python -m app.pipeline.run`
- Backend: `uvicorn app.main:app --host 127.0.0.1 --port 8000`
- Frontend: `npm run dev -- --host 127.0.0.1 --port 5173`
- Evaluation: `python -m app.evaluation.run`
- CI runs backend lint/tests and frontend typecheck/tests/build.
