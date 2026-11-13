"""HTTP contract. Approval is not a field on the run request."""

from fastapi.testclient import TestClient

from healthcare_platform.api import create_app
from healthcare_platform.identity import NIA_TOKEN, OUT_TOKEN, REA_TOKEN, SOL_TOKEN
from healthcare_platform.platform import Platform


def _client() -> tuple[TestClient, Platform]:
    platform = Platform()
    return TestClient(create_app(platform)), platform


def test_health_reports_gates_and_does_not_dial(monkeypatch: object) -> None:
    monkeypatch.setenv("DATABASE_URL", "https://secret.example/db")  # type: ignore[attr-defined]
    monkeypatch.setenv("REDIS_URL", "")  # type: ignore[attr-defined]
    client, platform = _client()
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["simulation"] is True
    assert body["clinically_validated"] is False
    assert body["ehr_calls"] == 0
    assert body["organization"] == "SYN-ORG-NORTHBRIDGE"
    assert body["workflows"] == [
        "clinical-document-draft",
        "referral-triage",
        "prior-auth-prep",
    ]
    assert body["adapters"]["postgres"] == "blocked"
    assert body["adapters"]["redis"] == "not-run"
    assert body["adapters"]["ehr"] == "not-run"
    assert "secret.example" not in response.text
    assert platform.ehr_calls == 0


def test_run_approve_and_execute_over_http() -> None:
    client, platform = _client()
    denied = client.post(
        "/api/v1/workflows/prior-auth-prep/runs",
        json={"case_id": "PA-0001"},
    )
    assert denied.status_code == 401
    extra = client.post(
        "/api/v1/workflows/prior-auth-prep/runs",
        headers={"Authorization": f"Bearer {REA_TOKEN}"},
        json={"case_id": "PA-0001", "approved": True},
    )
    assert extra.status_code == 422
    started = client.post(
        "/api/v1/workflows/prior-auth-prep/runs",
        headers={"Authorization": f"Bearer {REA_TOKEN}"},
        json={"case_id": "PA-0001", "run_id": "http-1"},
    )
    assert started.status_code == 200
    assert started.json()["status"] == "AWAITING_APPROVAL"
    assert "SYN-PHI-" not in started.text
    outsider = client.get(
        "/api/v1/runs/http-1",
        headers={"Authorization": f"Bearer {OUT_TOKEN}"},
    )
    assert outsider.status_code == 403
    seen = client.get(
        "/api/v1/runs/http-1",
        headers={"Authorization": f"Bearer {REA_TOKEN}"},
    )
    assert seen.status_code == 200
    early = client.post(
        "/api/v1/runs/http-1/execute",
        headers={"Authorization": f"Bearer {SOL_TOKEN}"},
    )
    assert early.status_code == 409
    approved = client.post(
        "/api/v1/runs/http-1/approve",
        headers={"Authorization": f"Bearer {SOL_TOKEN}"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    executed = client.post(
        "/api/v1/runs/http-1/execute",
        headers={"Authorization": f"Bearer {SOL_TOKEN}"},
    )
    assert executed.status_code == 200
    assert executed.json()["idempotent"] is False
    again = client.post(
        "/api/v1/runs/http-1/execute",
        headers={"Authorization": f"Bearer {SOL_TOKEN}"},
    )
    assert again.json()["idempotent"] is True
    assert platform.store.effect_count() == 1
    assert platform.ehr_calls == 0


def test_judge_review_route_is_not_a_model_id() -> None:
    client, _platform = _client()
    missing = client.post(
        "/api/v1/evaluations/judge-review",
        headers={"Authorization": f"Bearer {NIA_TOKEN}"},
    )
    assert missing.status_code == 200
    assert len(missing.json()["disagreement_ids"]) == 12
    scored = client.post(
        "/api/v1/evaluations/mock-governed",
        headers={"Authorization": f"Bearer {NIA_TOKEN}"},
    )
    assert scored.status_code == 200
    assert scored.json()["exact_matches"] == 180
    promoted = client.post(
        "/api/v1/registry/mock-leaky/promote",
        headers={"Authorization": f"Bearer {NIA_TOKEN}"},
        json={"stage": "active"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["promoted"] is False
    report = client.get("/api/v1/reports/models")
    assert report.status_code == 200
    assert report.json()["price"] == "none"
    metrics = client.get("/metrics")
    assert "healthcare_runs_total" in metrics.text
