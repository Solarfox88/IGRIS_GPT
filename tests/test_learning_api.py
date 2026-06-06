"""Tests for Learning API routes (#1247) — production-complete-strict."""
from __future__ import annotations
import json
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient
import igris.api.routes.learning_routes as lr

assert lr.router is not None, "FastAPI not available — learning router must load"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(lr.router)
    return app


def _client() -> TestClient:
    return TestClient(_make_app(), raise_server_exceptions=False)


def _reflection_payload(*, route="read_only_inspection", bundle_status="passed",
                         bundle_ok=True, user_feedback=""):
    return {
        "mission": {
            "mission_id": "test-m1",
            "title": "Test mission",
            "route": route,
            "risk": "low",
            "status": "planned",
            "execution_mode": "plan_only",
            "interlocutor_id": "owner",
            "trust_level": "admin",
            "requires_approval": False,
            "blocked": False,
            "steps": [],
        },
        "bundle": {"status": bundle_status, "ok": bundle_ok},
        "user_feedback": user_feedback,
    }


# ── module import ─────────────────────────────────────────────────────────────

def test_learning_routes_module_importable():
    assert hasattr(lr, "router")
    assert lr.router is not None


# ── GET /api/learning/health ──────────────────────────────────────────────────

def test_learning_health_returns_200_with_ok():
    client = _client()
    resp = client.get("/api/learning/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "ok" in data


def test_learning_health_no_server_error():
    client = _client()
    resp = client.get("/api/learning/health")
    assert resp.status_code < 500


# ── POST /api/learning/reflection ────────────────────────────────────────────

def test_reflection_missing_mission_returns_ok_false():
    client = _client()
    resp = client.post("/api/learning/reflection", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False


def test_reflection_valid_mission_returns_report_and_apply_result():
    client = _client()
    resp = client.post("/api/learning/reflection", json=_reflection_payload())
    assert resp.status_code == 200
    data = resp.json()
    assert "report" in data
    assert "apply_result" in data


def test_reflection_success_bundle_ok_true():
    client = _client()
    resp = client.post("/api/learning/reflection",
                       json=_reflection_payload(bundle_status="passed", bundle_ok=True))
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True


def test_reflection_blocked_mission():
    payload = _reflection_payload()
    payload["mission"]["blocked"] = True
    client = _client()
    resp = client.post("/api/learning/reflection", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "report" in data
    assert data["report"]["outcome"] == "blocked"


def test_reflection_invalid_payload_safe_no_stacktrace():
    """Invalid JSON body must return a safe error dict, not expose a raw stacktrace."""
    client = _client()
    # Send completely malformed body — TestClient with raise_server_exceptions=False
    # ensures server errors return HTTP 500 without blowing up the test process
    resp = client.post("/api/learning/reflection",
                       content=b"not json", headers={"content-type": "application/json"})
    # Either a 200 with ok=False or a 422/400 — must NOT be an unhandled 500
    assert resp.status_code in (200, 400, 422)
    if resp.status_code == 200:
        data = resp.json()
        assert data["ok"] is False
        # must not expose raw Python traceback text
        assert "Traceback" not in json.dumps(data)


def test_reflection_no_raw_secret_in_response():
    """API response must not contain the raw fake secret in key=value form."""
    FAKE = "FAKE_TOKEN_REFLECT_RESULT_NOTREAL"
    client = _client()
    resp = client.post("/api/learning/reflection",
                       json=_reflection_payload(user_feedback=f"token={FAKE}"))
    assert resp.status_code == 200
    assert f"token={FAKE}" not in resp.text
