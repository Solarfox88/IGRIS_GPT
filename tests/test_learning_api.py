"""Tests for Learning API routes (#1247)."""
from __future__ import annotations
import pytest


def test_learning_routes_module_importable():
    """Router module should import without error even without FastAPI app."""
    import igris.api.routes.learning_routes as lr
    # router may be None if fastapi not available, but module must load
    assert hasattr(lr, "router")


def test_learning_health_route_exists():
    """Router should have /health GET endpoint."""
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import igris.api.routes.learning_routes as lr
        if lr.router is None:
            pytest.skip("FastAPI not available")
        app = FastAPI()
        app.include_router(lr.router)
        client = TestClient(app)
        resp = client.get("/api/learning/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data
    except ImportError:
        pytest.skip("FastAPI not installed")


def test_learning_reflection_route_missing_mission():
    """POST /api/learning/reflection with no mission returns ok=False."""
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import igris.api.routes.learning_routes as lr
        if lr.router is None:
            pytest.skip("FastAPI not available")
        app = FastAPI()
        app.include_router(lr.router)
        client = TestClient(app)
        resp = client.post("/api/learning/reflection", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
    except ImportError:
        pytest.skip("FastAPI not installed")


def test_learning_reflection_route_success():
    """POST /api/learning/reflection with valid mission should return report."""
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import igris.api.routes.learning_routes as lr
        if lr.router is None:
            pytest.skip("FastAPI not available")
        app = FastAPI()
        app.include_router(lr.router)
        client = TestClient(app)

        payload = {
            "mission": {
                "mission_id": "test-m1",
                "title": "Test mission",
                "route": "read_only_inspection",
                "risk": "low",
                "status": "planned",
                "execution_mode": "plan_only",
                "interlocutor_id": "owner",
                "trust_level": "admin",
                "requires_approval": False,
                "blocked": False,
                "steps": [],
            },
            "bundle": {"status": "passed", "ok": True},
            "user_feedback": "",
        }
        resp = client.post("/api/learning/reflection", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "report" in data
        assert "apply_result" in data
    except ImportError:
        pytest.skip("FastAPI not installed")


def test_reflection_route_no_secret_in_response():
    """API response must not contain key=value secret patterns."""
    FAKE = "FAKE_TOKEN_API_NOTREAL_8877"
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import igris.api.routes.learning_routes as lr
        if lr.router is None:
            pytest.skip("FastAPI not available")
        app = FastAPI()
        app.include_router(lr.router)
        client = TestClient(app)

        payload = {
            "mission": {
                "mission_id": "test-mission-id",
                "title": "Test",
                "route": "read_only_inspection",
                "risk": "low",
                "status": "planned",
                "execution_mode": "plan_only",
                "interlocutor_id": "owner",
                "trust_level": "admin",
                "requires_approval": False,
                "blocked": False,
                "steps": [],
            },
            "bundle": {"status": "passed", "ok": True},
            "user_feedback": f"token={FAKE}",
        }
        resp = client.post("/api/learning/reflection", json=payload)
        # The key=value form should be redacted from signal texts
        assert f"token={FAKE}" not in resp.text
    except ImportError:
        pytest.skip("FastAPI not installed")
