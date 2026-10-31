# Metrics

- Daily activation and purchase rates are cohort-based.
- Checkout conversion is checkout-cohort based.
- Anomaly detection uses robust median/MAD and same-weekday/weekly baselines.
- All metric definitions are stored in `analytics.metric_definitions`.
- Authoritative values are computed by backend code or SQL, never by the LLM.
