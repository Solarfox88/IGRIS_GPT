"""Tests for Shadow API routes (#1248) — production-complete-ml-light-shadow-strict."""
from __future__ import annotations
import json
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient
import igris.api.routes.shadow_routes as sr

assert sr.router is not None, "FastAPI not available — shadow router must load"


# ── Isolated router app (fast, no full server state) ─────────────────────────

def _make_isolated_app() -> FastAPI:
    app = FastAPI()
    app.include_router(sr.router)
    return app


def _isolated_client() -> TestClient:
    return TestClient(_make_isolated_app(), raise_server_exceptions=False)


# ── Real app via create_app (full registry, shadow_routes must be registered) ─

def _real_client() -> TestClient:
    from igris.web.server import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


# ── GET /api/shadow/health — isolated ────────────────────────────────────────

def test_api_shadow_health_returns_200():
    client = _isolated_client()
    resp = client.get("/api/shadow/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "ok" in data


# ── POST /api/shadow/evaluate — isolated ─────────────────────────────────────

def test_api_shadow_evaluate_requires_message():
    client = _isolated_client()
    resp = client.post("/api/shadow/evaluate", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["shadow_only"] is True
    assert data["changed_decision"] is False


def test_api_shadow_evaluate_returns_report():
    client = _isolated_client()
    resp = client.post("/api/shadow/evaluate", json={"message": "controlla i log"})
    assert resp.status_code == 200
    data = resp.json()
    assert "report" in data
    assert data["shadow_only"] is True
    assert data["changed_decision"] is False


def test_api_shadow_evaluate_shadow_only():
    client = _isolated_client()
    resp = client.post("/api/shadow/evaluate", json={
        "message": "fai deploy",
        "route_decision": {"route": "chat_only", "risk": "low"},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["shadow_only"] is True
    assert data["changed_decision"] is False
    assert data["report"]["shadow_only"] is True
    assert data["report"]["changed_decision"] is False


def test_api_shadow_no_raw_secret():
    FAKE = "FAKE_TOKEN_SHADOW_1234567890"
    client = _isolated_client()
    resp = client.post("/api/shadow/evaluate", json={
        "message": f"deploy token={FAKE}",
        "trust_level": "untrusted",
    })
    assert resp.status_code == 200
    assert f"token={FAKE}" not in resp.text


def test_api_shadow_invalid_payload_safe():
    client = _isolated_client()
    resp = client.post("/api/shadow/evaluate",
                       content=b"not json",
                       headers={"content-type": "application/json"})
    assert resp.status_code in (200, 400, 422)
    if resp.status_code == 200:
        data = resp.json()
        assert data["ok"] is False
        assert "Traceback" not in json.dumps(data)


def test_api_shadow_with_memory_items():
    client = _isolated_client()
    resp = client.post("/api/shadow/evaluate", json={
        "message": "controlla i log",
        "memory_items": [
            {"id": "m1", "text": "log inspection lesson", "source": "lesson", "confidence": 0.8},
            {"id": "m2", "text": "unrelated memory", "source": "run_event", "confidence": 0.5},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["shadow_only"] is True
    assert data["changed_decision"] is False


def test_api_shadow_with_full_payload():
    client = _isolated_client()
    resp = client.post("/api/shadow/evaluate", json={
        "message": "fai deploy in produzione",
        "route_decision": {"route": "deploy_operation", "risk": "high"},
        "mission": {
            "route": "deploy_operation",
            "risk": "high",
            "blocked": False,
            "requires_approval": True,
            "status": "waiting_approval",
        },
        "bundle": {"status": "passed", "ok": True},
        "trust_level": "admin",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["shadow_only"] is True
    assert data["changed_decision"] is False
    assert "report" in data


# ── Real app tests — shadow_routes registered via router_registry ─────────────

def test_real_app_shadow_health_registered():
    """GET /api/shadow/health must be reachable via the real create_app()."""
    client = _real_client()
    resp = client.get("/api/shadow/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "ok" in data


def test_real_app_shadow_evaluate_registered():
    """POST /api/shadow/evaluate must be reachable via the real create_app()."""
    client = _real_client()
    resp = client.post("/api/shadow/evaluate", json={"message": "controlla i log"})
    assert resp.status_code == 200
    data = resp.json()
    assert "report" in data


def test_real_app_shadow_only_true():
    """Real app: shadow_only=True and changed_decision=False enforced."""
    client = _real_client()
    resp = client.post("/api/shadow/evaluate", json={"message": "fai deploy"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["shadow_only"] is True
    assert data["changed_decision"] is False


def test_real_app_no_raw_secret():
    """Real app: fake secret must not appear in API response."""
    FAKE = "FAKE_TOKEN_SHADOW_1234567890"
    client = _real_client()
    resp = client.post("/api/shadow/evaluate", json={
        "message": f"deploy token={FAKE}",
    })
    assert resp.status_code == 200
    assert f"token={FAKE}" not in resp.text


def test_real_app_invalid_payload_safe():
    """Real app: invalid JSON body must not expose stacktrace."""
    client = _real_client()
    resp = client.post("/api/shadow/evaluate",
                       content=b"not json",
                       headers={"content-type": "application/json"})
    assert resp.status_code in (200, 400, 422)
    if resp.status_code == 200:
        data = resp.json()
        assert data["ok"] is False
        assert "Traceback" not in json.dumps(data)
