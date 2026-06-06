"""Tests for Shadow API routes (#1248)."""
from __future__ import annotations
import json
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient
import igris.api.routes.shadow_routes as sr

assert sr.router is not None, "FastAPI not available — shadow router must load"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(sr.router)
    return app


def _client() -> TestClient:
    return TestClient(_make_app(), raise_server_exceptions=False)


# ── GET /api/shadow/health ────────────────────────────────────────────────────

def test_api_shadow_health_returns_200():
    client = _client()
    resp = client.get("/api/shadow/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "ok" in data


# ── POST /api/shadow/evaluate ─────────────────────────────────────────────────

def test_api_shadow_evaluate_requires_message():
    client = _client()
    resp = client.post("/api/shadow/evaluate", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["shadow_only"] is True
    assert data["changed_decision"] is False


def test_api_shadow_evaluate_returns_report():
    client = _client()
    resp = client.post("/api/shadow/evaluate", json={"message": "controlla i log"})
    assert resp.status_code == 200
    data = resp.json()
    assert "report" in data
    assert data["shadow_only"] is True
    assert data["changed_decision"] is False


def test_api_shadow_evaluate_shadow_only():
    client = _client()
    resp = client.post("/api/shadow/evaluate", json={
        "message": "fai deploy",
        "route_decision": {"route": "chat_only", "risk": "low"},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["shadow_only"] is True
    assert data["changed_decision"] is False
    # The report itself must confirm shadow_only
    assert data["report"]["shadow_only"] is True
    assert data["report"]["changed_decision"] is False


def test_api_shadow_no_raw_secret():
    FAKE = "FAKE_TOKEN_SHADOW_1234567890"
    client = _client()
    resp = client.post("/api/shadow/evaluate", json={
        "message": f"deploy token={FAKE}",
        "trust_level": "untrusted",
    })
    assert resp.status_code == 200
    assert f"token={FAKE}" not in resp.text


def test_api_shadow_invalid_payload_safe():
    client = _client()
    resp = client.post("/api/shadow/evaluate",
                       content=b"not json",
                       headers={"content-type": "application/json"})
    assert resp.status_code in (200, 400, 422)
    if resp.status_code == 200:
        data = resp.json()
        assert data["ok"] is False
        assert "Traceback" not in json.dumps(data)


def test_api_shadow_with_memory_items():
    client = _client()
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
    client = _client()
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
