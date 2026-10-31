# Data

Synthetic data only. Window 2026-05-04 through 2026-10-30, seed 42, 5,000 users,
target at least 70,000 events (actual 73,067 events).

Seeded anomalies:

- Payment-provider checkout-completion collapse 2026-08-10 through 2026-08-16.
- Paid-social registration spike 2026-09-15.
- Cancellation spike week of 2026-10-05.
- Declining paid-social D7 retention after 2026-08-01.

Seeded experiment: `exp_onboarding_checklist_v1`, approximately 2,500 users,
50/50 split, activation within 7 days primary, purchase within 14 days secondary.
