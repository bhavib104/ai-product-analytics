# AI Product Analytics & Decision Intelligence Copilot

Local-first MVP for product analytics, experimentation, anomaly detection, and
evidence-bound Copilot analysis.

## Run the backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.pipeline.run --generate
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Run the frontend


```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

## Verify

```powershell
cd backend
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m app.evaluation.run

cd ..\frontend
npm run typecheck
npm run test
npm run build
```

## Key verified results

- Synthetic data: 5,000 users, 73,067 events, 15,077 sessions, 570 subscriptions,
  2,356 experiment assignments, 180 daily metrics, 26 weekly metrics.
- Data quality: 97,601 rows read, 96,089 valid, 1,587 rejected.
- Three seeded anomalies detected: checkout conversion 2026-08-10 (0.0 vs 0.3888),
  registrations 2026-09-15 (74 vs baseline 28.5), cancellations 2026-10-05 (16 vs baseline 2.0).
- Experiment `exp_onboarding_checklist_v1`: activation_7d 52.27% control vs 62.63%
  treatment, p=3.66e-07; purchase_14d 5.45% vs 7.90%, p=1.71e-02.
- Backend tests: 78 passing. Frontend tests: 10 passing. Evaluation: 20/20 cases,
  21/21 tool calls, 16/16 SQL safety checks.
- LLM mode defaults to deterministic/offline.
