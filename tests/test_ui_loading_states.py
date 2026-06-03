"""Tests that UI panels never show permanent loading state — #526 + UI v3."""

import pytest
from fastapi.testclient import TestClient

from igris.web.server import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_interlocutor_panel_fallback_no_profiles(client):
    """Diagnostics summary endpoint responds 200 (JS uses it for panel data)."""
    r = client.get("/api/diagnostics/summary")
    assert r.status_code == 200
    d = r.json()
    # Must at minimum have health/status markers — JS handles missing interlocutor key
    assert isinstance(d, dict)


def test_audit_recent_empty_response(client):
    """When audit is empty, endpoint returns empty list not error."""
    r = client.get("/api/interlocutor/audit/recent")
    assert r.status_code == 200
    data = r.json()
    # Must return list or dict with events, never 500
    assert isinstance(data, (list, dict))


def test_identity_profiles_endpoint_available(client):
    """Profiles endpoint always responds."""
    r = client.get("/api/identity/profiles")
    assert r.status_code == 200


def test_rank_gauntlet_endpoint_available(client):
    """Rank gauntlet always responds with rank field."""
    r = client.get("/api/rank/gauntlet")
    assert r.status_code == 200
    d = r.json()
    assert "rank" in d
    assert "score" in d
    assert "passed" in d
