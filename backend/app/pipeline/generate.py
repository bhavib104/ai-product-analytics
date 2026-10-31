"""Deterministic synthetic product-analytics dataset generator.

The generator produces realistic user journeys, sessions, subscriptions, an A/B
experiment, seeded data-quality problems and deliberately seeded analytical
anomalies.  A fixed seed and fixed date window make every output file
reproducible.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

from app.core.config import Settings

CHANNELS = [
    {"key": "organic_search", "name": "Organic Search", "paid": 0, "weight": 24, "activation": 0.03, "activity": 1.30},
    {"key": "paid_social", "name": "Paid Social", "paid": 1, "weight": 20, "activation": -0.10, "activity": 0.60},
    {"key": "referral", "name": "Referral", "paid": 0, "weight": 15, "activation": 0.08, "activity": 1.60},
    {"key": "content", "name": "Content", "paid": 0, "weight": 12, "activation": -0.02, "activity": 1.10},
    {"key": "email", "name": "Email", "paid": 0, "weight": 10, "activation": 0.02, "activity": 1.20},
    {"key": "partner", "name": "Partner", "paid": 1, "weight": 8, "activation": 0.01, "activity": 1.00},
    {"key": "direct", "name": "Direct", "paid": 0, "weight": 11, "activation": 0.00, "activity": 0.90},
]
DEVICES = [
    {"key": "ios", "name": "iOS", "weight": 45, "activation": 0.03, "activity": 1.15},
    {"key": "android", "name": "Android", "weight": 40, "activation": -0.05, "activity": 0.90},
    {"key": "web", "name": "Web", "weight": 15, "activation": 0.02, "activity": 1.00},
]
COUNTRIES = [
    ("US", 35), ("IN", 20), ("GB", 12), ("DE", 8), ("CA", 7),
    ("AU", 5), ("BR", 5), ("FR", 4), ("JP", 2), ("Other", 2),
]
PLANS = [
    {"key": "starter", "name": "Starter", "weight": 45, "mrr_cents": 2900},
    {"key": "growth", "name": "Growth", "weight": 40, "mrr_cents": 9900},
    {"key": "enterprise", "name": "Enterprise", "weight": 15, "mrr_cents": 49900},
]
FEATURES = [
    ("dashboards", "Dashboards", "Core"),
    ("funnels", "Funnels", "Analytics"),
    ("retention", "Retention", "Analytics"),
    ("cohorts", "Cohorts", "Analytics"),
    ("segments", "Segments", "Analytics"),
    ("experiments", "Experiments", "Optimization"),
    ("reports", "Reports", "Reporting"),
    ("alerts", "Alerts", "Monitoring"),
    ("integrations", "Integrations", "Platform"),
    ("exports", "Exports", "Reporting"),
]
EXPERIMENT_ID = "exp_onboarding_checklist_v1"
EXPERIMENT_START = date(2026, 6, 1)
EXPERIMENT_END = date(2026, 8, 31)
ANDROID_OUTAGE_START = date(2026, 8, 10)
ANDROID_OUTAGE_END = date(2026, 8, 16)
PAID_SOCIAL_SPIKE_DATE = date(2026, 9, 15)
CANCELLATION_SPIKE_START = date(2026, 10, 5)
CANCELLATION_SPIKE_END = date(2026, 10, 11)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _weighted_choice(rng: random.Random, items: list[dict], key: str = "weight") -> dict:
    return rng.choices(items, weights=[i[key] for i in items], k=1)[0]


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


class SyntheticGenerator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.rng = random.Random(settings.data_seed)
        self.start = settings.data_start_date
        self.end = settings.data_end_date
        self.num_users = settings.data_num_users
        self.users: list[dict] = []
        self.events: list[dict] = []
        self.sessions: list[dict] = []
        self.subscriptions: list[dict] = []
        self.assignments: list[dict] = []
        self._session_seq = 0
        self._event_seq = 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _dates(self) -> list[date]:
        n = (self.end - self.start).days + 1
        return [self.start + timedelta(days=i) for i in range(n)]

    def _registration_date(self, channel: str) -> date:
        dates = self._dates()
        weights = []
        n = len(dates)
        for i, d in enumerate(dates):
            w = 1.0 + 0.8 * (i / max(1, n - 1))
            w *= {0: 1.10, 1: 1.05, 2: 1.05, 3: 1.05, 4: 1.00, 5: 0.72, 6: 0.68}[d.weekday()]
            if channel == "paid_social" and d == PAID_SOCIAL_SPIKE_DATE:
                w *= 7.0
            weights.append(w)
        return self.rng.choices(dates, weights=weights, k=1)[0]

    def _at(self, d: date, hour_low: int = 6, hour_high: int = 22) -> datetime:
        return datetime.combine(
            d,
            time(
                self.rng.randint(hour_low, hour_high - 1),
                self.rng.randint(0, 59),
                self.rng.randint(0, 59),
            ),
        )

    def _new_session_id(self) -> str:
        self._session_seq += 1
        return f"ses_{self._session_seq:07d}"

    def _add_event(
        self,
        user_id: str,
        event_name: str,
        ts: datetime,
        session_id: str | None,
        device: str,
        properties: dict | None = None,
    ) -> None:
        self.events.append(
            {
                "user_id": user_id,
                "event_name": event_name,
                "event_timestamp": iso(ts),
                "session_id": session_id or "",
                "device": device,
                "properties": json.dumps(properties or {}, sort_keys=True, separators=(",", ":")),
            }
        )

    def _add_session(
        self,
        user_id: str,
        device: str,
        start: datetime,
        duration_seconds: int,
        event_names: list[tuple[str, dict | None]],
    ) -> None:
        session_id = self._new_session_id()
        end = start + timedelta(seconds=duration_seconds)
        self.sessions.append(
            {
                "session_id": session_id,
                "user_id": user_id,
                "start_time": iso(start),
                "end_time": iso(end),
                "duration_seconds": duration_seconds,
                "event_count": len(event_names),
                "device": device,
            }
        )
        span = max(1, duration_seconds - 5)
        for idx, (name, props) in enumerate(event_names):
            offset = int(span * idx / max(1, len(event_names) - 1))
            self._add_event(
                user_id, name, start + timedelta(seconds=offset), session_id, device, props
            )

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def generate(self) -> dict:
        for i in range(self.num_users):
            self._generate_user(i)
        self._top_up_events()
        self._assign_event_ids()
        self._finalise_users()
        return self._write_outputs()

    def _generate_user(self, index: int) -> None:
        rng = self.rng
        user_id = f"u_{index + 1:06d}"
        channel = _weighted_choice(rng, CHANNELS)
        device = _weighted_choice(rng, DEVICES)
        country = rng.choices([c for c, _ in COUNTRIES], weights=[w for _, w in COUNTRIES], k=1)[0]
        reg_date = self._registration_date(channel["key"])
        reg_ts = self._at(reg_date)

        in_experiment = EXPERIMENT_START <= reg_date <= EXPERIMENT_END
        variant = ""
        assigned_at = None
        if in_experiment:
            variant = "control" if rng.random() < 0.5 else "treatment"
            assigned_at = reg_ts + timedelta(minutes=rng.randint(0, 60))
            self.assignments.append(
                {
                    "assignment_id": f"asg_{len(self.assignments) + 1:07d}",
                    "experiment_id": EXPERIMENT_ID,
                    "user_id": user_id,
                    "variant": variant,
                    "assigned_at": iso(assigned_at),
                }
            )

        # --- Onboarding -------------------------------------------------
        activation_p = 0.55 + channel["activation"] + device["activation"]
        if in_experiment:
            activation_p = 0.52 if variant == "control" else 0.64
        activation_p = max(0.12, min(0.92, activation_p))
        activated = rng.random() < activation_p
        activation_ts = None
        if activated:
            activation_ts = reg_ts + timedelta(
                days=rng.randint(0, 3), hours=rng.randint(0, 20), minutes=rng.randint(0, 59)
            )
            self._add_event(
                user_id, "user_registered", reg_ts, None, device["key"],
                {"channel": channel["key"], "country": country},
            )
            self._add_event(
                user_id, "account_activated", activation_ts, None, device["key"],
                {"variant": variant} if variant else {},
            )
        else:
            self._add_event(
                user_id, "user_registered", reg_ts, None, device["key"],
                {"channel": channel["key"], "country": country},
            )

        feature_used = False
        first_feature_ts = None
        if activated and rng.random() < 0.82:
            feature_used = True
            first_feature_ts = activation_ts + timedelta(
                days=rng.randint(0, 5), hours=rng.randint(0, 12), minutes=rng.randint(0, 59)
            )
            feature = rng.choice(FEATURES)
            self._add_event(
                user_id, "feature_used", first_feature_ts, None, device["key"],
                {"feature_key": feature[0], "feature_name": feature[1]},
            )

        purchased = False
        purchase_ts = None
        plan = None
        checkout_ts = None
        if activated and feature_used:
            checkout_p = 0.65
            if in_experiment:
                checkout_p = 0.50
            if rng.random() < checkout_p:
                checkout_ts = first_feature_ts + timedelta(
                    days=rng.randint(0, 7), hours=rng.randint(0, 12), minutes=rng.randint(0, 59)
                )
                if checkout_ts.date() <= self.end:
                    self._add_event(
                        user_id, "checkout_started", checkout_ts, None, device["key"],
                        {"plan_intent": "paid"},
                    )
                    purchase_p = 0.50
                    if in_experiment:
                        purchase_p = 0.39 if variant == "control" else 0.50
                    if ANDROID_OUTAGE_START <= checkout_ts.date() <= ANDROID_OUTAGE_END:
                        # Payment-provider incident: checkout completion collapses
                        # across devices, with Android hit hardest.
                        purchase_p = 0.0 if device["key"] == "android" else 0.02
                    if rng.random() < purchase_p:
                        purchase_ts = checkout_ts + timedelta(
                            days=rng.randint(0, 7), hours=rng.randint(0, 12),
                            minutes=rng.randint(0, 59),
                        )
                        if purchase_ts.date() <= self.end:
                            purchased = True
                            plan = _weighted_choice(rng, PLANS)
                            self._add_event(
                                user_id, "purchase_completed", purchase_ts, None, device["key"],
                                {"plan": plan["key"], "mrr_cents": plan["mrr_cents"]},
                            )
                            self._create_subscription(user_id, plan, purchase_ts.date())

        # --- Ongoing activity -------------------------------------------
        churn_date = self._subscription_churn_date(user_id)
        activity_start = reg_date + timedelta(days=1)
        if feature_used and first_feature_ts:
            activity_start = max(activity_start, first_feature_ts.date() + timedelta(days=1))
        if purchase_ts:
            activity_start = max(activity_start, purchase_ts.date() + timedelta(days=1))

        self._generate_ongoing_activity(
            user_id=user_id,
            device=device["key"],
            channel=channel["key"],
            start=activity_start,
            end=self.end,
            churn_date=churn_date,
            has_active_subscription=purchased,
        )

        self.users.append(
            {
                "user_id": user_id,
                "registration_date": reg_date.isoformat(),
                "country": country,
                "device_type": device["key"],
                "acquisition_channel": channel["key"],
                "subscription_type": plan["key"] if purchased else "free",
                "user_status": "active",
            }
        )

    def _create_subscription(self, user_id: str, plan: dict, start: date) -> None:
        rng = self.rng
        billing_cycle = "annual" if rng.random() < 0.30 else "monthly"
        cycle_days = 365 if billing_cycle == "annual" else 30
        mrr = plan["mrr_cents"] * (0.8 if billing_cycle == "annual" else 1.0)
        renewal = start + timedelta(days=cycle_days)
        cancelled_date = None
        status = "active"
        months_active = 0
        while renewal <= self.end:
            cancel_p = 0.04 if billing_cycle == "annual" else 0.08
            if CANCELLATION_SPIKE_START <= renewal <= CANCELLATION_SPIKE_END:
                cancel_p = 0.35
            if rng.random() < cancel_p:
                cancelled_date = renewal
                status = "cancelled"
                break
            months_active += 12 if billing_cycle == "annual" else 1
            renewal = renewal + timedelta(days=cycle_days)
        if status == "active":
            months_active += max(
                1, int((self.end - start).days / (365 if billing_cycle == "annual" else 30))
            )
        self.subscriptions.append(
            {
                "subscription_id": f"sub_{len(self.subscriptions) + 1:07d}",
                "user_id": user_id,
                "plan": plan["key"],
                "billing_cycle": billing_cycle,
                "start_date": start.isoformat(),
                "renewal_date": renewal.isoformat(),
                "status": status,
                "mrr_cents": mrr,
                "total_revenue_cents": mrr * max(1, months_active),
                "cancelled_date": cancelled_date.isoformat() if cancelled_date else "",
            }
        )
        if cancelled_date:
            self._add_event(
                user_id, "subscription_cancelled", self._at(cancelled_date, 8, 20), None,
                "web", {"plan": plan["key"]},
            )
        # Renewal events (account-level, no session).
        r = start + timedelta(days=cycle_days)
        while r <= self.end:
            if cancelled_date and r >= cancelled_date:
                break
            self._add_event(
                user_id, "subscription_renewed", self._at(r, 0, 6), None, "web",
                {"plan": plan["key"]},
            )
            r = r + timedelta(days=cycle_days)

    def _subscription_churn_date(self, user_id: str) -> date | None:
        for sub in self.subscriptions:
            if sub["user_id"] == user_id and sub["cancelled_date"]:
                return date.fromisoformat(sub["cancelled_date"])
        return None

    def _generate_ongoing_activity(
        self,
        *,
        user_id: str,
        device: str,
        channel: str,
        start: date,
        end: date,
        churn_date: date | None,
        has_active_subscription: bool,
    ) -> None:
        rng = self.rng
        if start > end:
            return
        channel_meta = next(c for c in CHANNELS if c["key"] == channel)
        device_meta = next(d for d in DEVICES if d["key"] == device)
        base = 0.036
        base *= channel_meta["activity"] * device_meta["activity"]
        base *= 1.40 if has_active_subscription else 0.90
        if channel == "paid_social" and start >= date(2026, 8, 1):
            base *= 0.50
        d = start
        while d <= end:
            if churn_date and d >= churn_date:
                break
            tenure = (d - start).days
            if tenure <= 14:
                decay = 1.60
            elif tenure <= 60:
                decay = 1.00
            elif tenure <= 120:
                decay = 0.70
            else:
                decay = 0.50
            weekday = 0.65 if d.weekday() >= 5 else 1.00
            p = min(0.35, base * decay * weekday)
            if rng.random() < p:
                n_sessions = 2 if rng.random() < 0.18 else 1
                for _ in range(n_sessions):
                    session_start = self._at(d, 6, 23)
                    duration = rng.randint(120, 1800)
                    n_events = rng.randint(2, 6)
                    names: list[tuple[str, dict | None]] = [("session_started", None)]
                    for _ in range(max(1, n_events - 1)):
                        roll = rng.random()
                        if roll < 0.52:
                            feature = rng.choice(FEATURES)
                            names.append(
                                ("feature_used", {"feature_key": feature[0], "feature_name": feature[1]})
                            )
                        elif roll < 0.68:
                            names.append(("dashboard_viewed", None))
                        elif roll < 0.78:
                            names.append(("report_exported", None))
                        elif roll < 0.86:
                            names.append(("alert_created", None))
                        elif roll < 0.93:
                            names.append(("integration_connected", None))
                        else:
                            names.append(("feature_used", {"feature_key": "dashboards", "feature_name": "Dashboards"}))
                    self._add_session(user_id, device, session_start, duration, names)
            d += timedelta(days=1)

    def _top_up_events(self) -> None:
        """Guarantee the MVP's minimum event volume deterministically."""
        target = 70_000
        attempts = 0
        while len(self.events) < target and attempts < 100_000:
            attempts += 1
            user = self.rng.choice(self.users) if self.users else None
            if not user:
                break
            reg = date.fromisoformat(user["registration_date"])
            if reg >= self.end:
                continue
            d = reg + timedelta(days=self.rng.randint(1, max(1, (self.end - reg).days)))
            start = self._at(d, 6, 23)
            names: list[tuple[str, dict | None]] = [("session_started", None)]
            for _ in range(self.rng.randint(2, 4)):
                feature = self.rng.choice(FEATURES)
                names.append(("feature_used", {"feature_key": feature[0], "feature_name": feature[1]}))
            self._add_session(user["user_id"], user["device_type"], start, self.rng.randint(120, 1200), names)

    def _assign_event_ids(self) -> None:
        self.events.sort(key=lambda e: (e["event_timestamp"], e["user_id"], e["event_name"]))
        for i, event in enumerate(self.events, start=1):
            event["event_id"] = f"evt_{i:08d}"

    def _finalise_users(self) -> None:
        last_activity: dict[str, date] = {}
        for event in self.events:
            uid = event["user_id"]
            day = date.fromisoformat(event["event_timestamp"][:10])
            if uid not in last_activity or day > last_activity[uid]:
                last_activity[uid] = day
        cancelled = {s["user_id"] for s in self.subscriptions if s["status"] == "cancelled"}
        for user in self.users:
            uid = user["user_id"]
            last = last_activity.get(uid)
            if uid in cancelled:
                user["user_status"] = "churned"
            elif last is None or (self.end - last).days > 30:
                user["user_status"] = "inactive"
            else:
                user["user_status"] = "active"
            subs = [s for s in self.subscriptions if s["user_id"] == uid]
            if subs:
                active = [s for s in subs if s["status"] == "active"]
                user["subscription_type"] = (active or subs)[-1]["plan"]
            else:
                user["subscription_type"] = "free"

    # ------------------------------------------------------------------
    # Raw output + data-quality injection
    # ------------------------------------------------------------------
    def _write_outputs(self) -> dict:
        data_dir = Path(self.settings.data_dir)
        raw_dir = data_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        users = [dict(u) for u in self.users]
        events = [dict(e) for e in self.events]
        sessions = [dict(s) for s in self.sessions]
        subscriptions = [dict(s) for s in self.subscriptions]
        assignments = [dict(a) for a in self.assignments]

        # Inject data-quality problems into the raw layer.
        rng = self.rng
        for _ in range(max(1, int(len(users) * 0.01))):
            users[rng.randrange(len(users))]["country"] = ""
        for _ in range(max(1, int(len(users) * 0.002))):
            users.append(dict(users[rng.randrange(len(users))]))

        for _ in range(max(1, int(len(events) * 0.010))):
            events.append(dict(events[rng.randrange(len(events))]))
        for _ in range(max(1, int(len(events) * 0.015))):
            events[rng.randrange(len(events))]["device"] = ""
        for _ in range(max(1, int(len(events) * 0.004))):
            row = dict(events[rng.randrange(len(events))])
            row["user_id"] = "u_999999"
            events.append(row)
        for _ in range(max(1, int(len(events) * 0.003))):
            row = dict(events[rng.randrange(len(events))])
            row["event_timestamp"] = "not-a-date" if rng.random() < 0.5 else "2027-01-01T00:00:00Z"
            events.append(row)
        for _ in range(max(1, int(len(events) * 0.002))):
            row = dict(events[rng.randrange(len(events))])
            if row["event_timestamp"].endswith("Z"):
                row["event_timestamp"] = row["event_timestamp"][:-1] + "+05:30"
            events.append(row)

        for _ in range(max(1, int(len(sessions) * 0.005))):
            sessions[rng.randrange(len(sessions))]["duration_seconds"] = -abs(
                sessions[rng.randrange(len(sessions))]["duration_seconds"]
            )

        for _ in range(max(1, int(len(subscriptions) * 0.005))):
            subscriptions[rng.randrange(len(subscriptions))]["status"] = ""
        for _ in range(max(1, int(len(subscriptions) * 0.003))):
            row = dict(subscriptions[rng.randrange(len(subscriptions))])
            row["renewal_date"] = row["start_date"]
            subscriptions.append(row)

        for _ in range(max(1, int(len(assignments) * 0.005))):
            assignments.append(dict(assignments[rng.randrange(len(assignments))]))

        experiments = [
            {
                "experiment_id": EXPERIMENT_ID,
                "name": "Onboarding checklist v1",
                "description": "Checklist-guided onboarding vs. existing onboarding.",
                "start_date": EXPERIMENT_START.isoformat(),
                "end_date": EXPERIMENT_END.isoformat(),
                "primary_metric": "activation_7d",
                "secondary_metric": "purchase_14d",
                "status": "completed",
            }
        ]
        products = [
            {"product_id": "prod_copilot", "product_name": "Analytics Copilot", "category": "SaaS"},
        ]
        features = [
            {"feature_key": k, "feature_name": n, "product_id": "prod_copilot", "category": c}
            for k, n, c in FEATURES
        ]
        channels = [
            {"channel_key": c["key"], "channel_name": c["name"], "paid_flag": c["paid"]}
            for c in CHANNELS
        ]

        files = {
            "users": (users, ["user_id", "registration_date", "country", "device_type", "acquisition_channel", "subscription_type", "user_status"]),
            "events": (events, ["event_id", "user_id", "event_name", "event_timestamp", "session_id", "device", "properties"]),
            "sessions": (sessions, ["session_id", "user_id", "start_time", "end_time", "duration_seconds", "event_count", "device"]),
            "subscriptions": (subscriptions, ["subscription_id", "user_id", "plan", "billing_cycle", "start_date", "renewal_date", "status", "mrr_cents", "total_revenue_cents", "cancelled_date"]),
            "experiments": (experiments, ["experiment_id", "name", "description", "start_date", "end_date", "primary_metric", "secondary_metric", "status"]),
            "experiment_assignments": (assignments, ["assignment_id", "experiment_id", "user_id", "variant", "assigned_at"]),
            "products": (products, ["product_id", "product_name", "category"]),
            "features": (features, ["feature_key", "feature_name", "product_id", "category"]),
            "acquisition_channels": (channels, ["channel_key", "channel_name", "paid_flag"]),
        }

        hashes = {}
        for name, (rows, fields) in files.items():
            path = raw_dir / f"{name}.csv"
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()

        manifest = {
            "seed": self.settings.data_seed,
            "data_start": self.start.isoformat(),
            "data_end": self.end.isoformat(),
            "num_users": self.num_users,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "counts": {
                "users_clean": len(self.users),
                "events_clean": len(self.events),
                "sessions_clean": len(self.sessions),
                "subscriptions_clean": len(self.subscriptions),
                "experiment_assignments_clean": len(self.assignments),
                "users_raw": len(users),
                "events_raw": len(events),
                "sessions_raw": len(sessions),
                "subscriptions_raw": len(subscriptions),
                "assignments_raw": len(assignments),
            },
            "file_hashes": hashes,
            "seeded_anomalies": [
                {
                    "metric": "checkout_conversion_rate",
                    "window_start": ANDROID_OUTAGE_START.isoformat(),
                    "window_end": ANDROID_OUTAGE_END.isoformat(),
                    "description": "Payment-provider incident: checkout completion collapsed across devices, with Android hit hardest.",
                },
                {
                    "metric": "registrations",
                    "window_start": PAID_SOCIAL_SPIKE_DATE.isoformat(),
                    "window_end": PAID_SOCIAL_SPIKE_DATE.isoformat(),
                    "description": "Paid-social registration spike with low-quality activation.",
                },
                {
                    "metric": "cancellations",
                    "window_start": CANCELLATION_SPIKE_START.isoformat(),
                    "window_end": CANCELLATION_SPIKE_END.isoformat(),
                    "description": "Monthly-plan cancellation spike.",
                },
                {
                    "metric": "retention_d7_paid_social",
                    "window_start": "2026-08-01",
                    "window_end": self.end.isoformat(),
                    "description": "Paid-social cohorts after August show weaker D7 retention.",
                },
            ],
            "expected_experiment": {
                "experiment_id": EXPERIMENT_ID,
                "primary_metric": "activation_7d",
                "secondary_metric": "purchase_14d",
                "design": "50/50 control/treatment; treatment expected to improve activation and purchase.",
            },
        }
        (data_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest
