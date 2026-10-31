from __future__ import annotations

import pytest

API = "/api/v1"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/health", None),
        ("/meta", None),
        ("/overview", None),
        ("/engagement?granularity=week&group_by=channel", "groups"),
        ("/features", "features"),
        ("/sessions?granularity=month", "series"),
        ("/funnels", None),
        ("/retention?cohort_type=weekly&group_by=device", "summary"),
        ("/segments", "segments"),
        ("/experiments", None),
        ("/anomalies", "rows"),
        ("/metric-definitions", None),
        ("/data/users?limit=5", "rows"),
        ("/data/events?limit=5", "rows"),
        ("/data/subscriptions?limit=5", "rows"),
        ("/data/sessions?limit=5", "rows"),
        ("/ingestion-runs", None),
        ("/data-quality?limit=5", None),
        ("/history?limit=5", None),
        ("/reports?limit=5", None),
    ],
)
def test_read_endpoints_return_data(client, path: str, expected: str | None) -> None:
    response = client.get(API + path)
    assert response.status_code == 200, response.text
    body = response.json()
    if expected:
        assert expected in body
    if path.startswith("/data/") and expected == "rows":
        assert isinstance(body["rows"], list)


def test_health_reports_ready_data(client) -> None:
    body = client.get(API + "/health").json()
    assert body["status"] == "ok"
    assert body["data_ready"] is True


def test_meta_exposes_schema_metrics_and_tools(client) -> None:
    body = client.get(API + "/meta").json()
    assert body["data_window"]["synthetic"] is True
    assert body["data_window"]["seed"] == 42
    assert body["metrics"]
    assert "events" in body["schema"]
    assert body["event_names"]
    assert len(body["tools"]) >= 10
    assert body["limits"]["sql_max_rows"] > 0


def test_default_funnel_analysis(client) -> None:
    response = client.get(API + "/funnels/default/analyze?window_days=14&group_by=device")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["funnel_id"] == "default"
    assert len(body["stages"]) == 5
    assert body["groups"]
    assert body["cohort_users"] > 0


def test_experiment_detail_and_not_found(client) -> None:
    response = client.get(API + "/experiments/exp_onboarding_checklist_v1")
    assert response.status_code == 200
    assert response.json()["assignment"]["srm"]["interpretation"]
    missing = client.get(API + "/experiments/exp_missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


def test_sql_validate_and_execute(client) -> None:
    valid = client.post(
        API + "/sql/validate",
        json={"sql": "SELECT event_name, COUNT(*) AS events FROM analytics.events GROUP BY 1 ORDER BY 2 DESC"},
    )
    assert valid.status_code == 200
    assert valid.json()["valid"] is True

    unsafe = client.post(API + "/sql/validate", json={"sql": "DROP TABLE analytics.events"})
    assert unsafe.status_code == 200
    assert unsafe.json()["valid"] is False

    rejected = client.post(API + "/sql/execute", json={"sql": "DELETE FROM analytics.events"})
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "SQL_REJECTED"

    executed = client.post(
        API + "/sql/execute",
        json={"sql": "SELECT metric_date, dau FROM analytics.daily_metrics ORDER BY metric_date LIMIT 3"},
    )
    assert executed.status_code == 200, executed.text
    body = executed.json()
    assert body["row_count"] == 3
    assert len(body["rows"]) == 3
    assert body["validation"]["valid"] is True


def test_sql_ask_uses_reviewed_template(client) -> None:
    response = client.post(API + "/sql/ask", json={"question": "How many registrations were there by channel?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "success"
    assert body["sql"]
    assert body["rows"]
    assert body["validation"]["valid"] is True
    assert body["template"]


def test_sql_ask_unsupported_question_is_explicit(client) -> None:
    response = client.post(API + "/sql/ask", json={"question": "What is the weather tomorrow?"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unsupported"
    assert body["sql"] is None


def test_copilot_returns_evidence_and_persists_interaction(client) -> None:
    response = client.post(API + "/copilot/ask", json={"question": "What were the biggest anomalies?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["interaction_id"].startswith("int_")
    assert body["answer"]
    assert body["tool_calls"]
    assert body["evidence"]["facts"]
    assert body["fallback"] is False

    detail = client.get(API + f"/copilot/interactions/{body['interaction_id']}")
    assert detail.status_code == 200
    assert detail.json()["question"] == "What were the biggest anomalies?"
    listed = client.get(API + "/copilot/interactions?limit=10").json()
    assert any(row["id"] == body["interaction_id"] for row in listed)


def test_funnel_creation_validates_event_names(client) -> None:
    payload = {
        "name": "Test activation funnel",
        "stages": [
            {"key": "registration", "label": "Registration", "event_name": "user_registered"},
            {"key": "activation", "label": "Activation", "event_name": "account_activated"},
        ],
        "window_days": 7,
    }
    response = client.post(API + "/funnels", json=payload)
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["funnel_id"].startswith("funnel_")
    listed = client.get(API + "/funnels").json()
    assert any(row["id"] == created["funnel_id"] for row in listed)

    invalid = client.post(
        API + "/funnels",
        json={
            "name": "Bad funnel",
            "stages": [
                {"key": "a", "label": "A", "event_name": "not_an_event"},
                {"key": "b", "label": "B", "event_name": "also_missing"},
            ],
        },
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INVALID_FUNNEL"


def test_report_creation_and_exports(client) -> None:
    response = client.post(API + "/reports", json={"title": "Test KPI report", "question": "Current health?"})
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["content_md"].startswith("# Test KPI report")
    assert "KPI snapshot" in report["content_md"]

    html = client.get(API + f"/reports/{report['id']}/html")
    assert html.status_code == 200
    assert "<html" in html.text.lower()
    assert "Test KPI report" in html.text

    markdown = client.get(API + f"/reports/{report['id']}/markdown")
    assert markdown.status_code == 200
    assert markdown.text.startswith("# Test KPI report")


def test_unknown_resources_return_structured_404(client) -> None:
    for path in ("/funnels/missing/analyze", "/copilot/interactions/int_missing", "/reports/rep_missing"):
        response = client.get(API + path)
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "NOT_FOUND"
