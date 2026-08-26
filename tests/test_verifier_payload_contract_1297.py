"""Tests for verifier/reflection payload contract (#1297).

Verifies that:
1. Missing 'mission' field returns a helpful error message
2. Wrong field names (bundle, mission_plan) get a specific hint
3. Correct payload is accepted
"""
from __future__ import annotations

import json
from fastapi import FastAPI
from fastapi.testclient import TestClient

from igris.api.routes.verifier_routes import router as verifier_router
from igris.api.routes.learning_routes import router as learning_router


def _make_app() -> FastAPI:
    app = FastAPI()
    if verifier_router:
        app.include_router(verifier_router)
    if learning_router:
        app.include_router(learning_router)
    return app


def _client() -> TestClient:
    return TestClient(_make_app())


def test_verifier_missing_mission_field_has_helpful_error() -> None:
    """Missing 'mission' field should return a helpful error with expected format."""
    with _client() as c:
        resp = c.post("/api/verifier/mission", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "mission" in data["error"]
        assert "Expected" in data["error"]


def test_verifier_wrong_field_name_gets_specific_hint() -> None:
    """Using 'bundle' instead of 'mission' should mention the wrong field."""
    with _client() as c:
        resp = c.post("/api/verifier/mission", json={"bundle": {"mission_id": "x"}})
        data = resp.json()
        assert data["ok"] is False
        assert "bundle" in data["error"]
        assert "mission" in data["error"]


def test_verifier_mission_plan_field_gets_hint() -> None:
    """Using 'mission_plan' instead of 'mission' should mention the wrong field."""
    with _client() as c:
        resp = c.post("/api/verifier/mission", json={"mission_plan": {"mission_id": "x"}})
        data = resp.json()
        assert data["ok"] is False
        assert "mission_plan" in data["error"]


def test_verifier_correct_payload_is_accepted() -> None:
    """Correct payload with 'mission' field should be processed."""
    with _client() as c:
        resp = c.post("/api/verifier/mission", json={
            "mission": {
                "mission_id": "test-1297",
                "title": "Test mission",
                "route": "code_writing",
                "steps": [],
            }
        })
        data = resp.json()
        # Should not return the "mission payload required" error
        assert "error" not in data or "mission payload required" not in str(data.get("error", ""))


def test_reflection_missing_mission_field_has_helpful_error() -> None:
    """Missing 'mission' field should return a helpful error with expected format."""
    with _client() as c:
        resp = c.post("/api/learning/reflection", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "mission" in data["error"]
        assert "Expected" in data["error"]


def test_reflection_wrong_field_name_gets_specific_hint() -> None:
    """Using 'bundle' instead of 'mission' should mention the wrong field."""
    with _client() as c:
        resp = c.post("/api/learning/reflection", json={"bundle": {"mission_id": "x"}})
        data = resp.json()
        assert data["ok"] is False
        assert "bundle" in data["error"]
        assert "mission" in data["error"]
