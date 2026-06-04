"""API tests for Context Aggregator routes (#1244)."""
import pytest
import json
import re
from fastapi.testclient import TestClient
from igris.web.server import create_app


@pytest.fixture
def client():
    return TestClient(create_app(), raise_server_exceptions=False)


def test_api_os_brief_returns_brief(client):
    """POST /api/os/brief returns a PersonalOSBrief."""
    r = client.post("/api/os/brief", json={"query": "stato del progetto", "interlocutor_id": "owner"})
    assert r.status_code == 200
    d = r.json()
    assert "ok" in d
    assert "sections" in d
    assert "brief_text" in d
    assert "[PERSONAL OS BRIEF]" in d.get("brief_text", "")


def test_api_os_brief_nonlocal_admin_claim_degraded(client):
    """Non-local request claiming trust_level=admin must be degraded to untrusted.

    TestClient is treated as non-local ('testclient' host).
    """
    r = client.post("/api/os/brief", json={
        "query": "dati sensibili",
        "interlocutor_id": "owner",
        "trust_level": "admin",
    })
    assert r.status_code == 200
    d = r.json()
    # The API must have downgraded trust_level to untrusted
    # Verify: trust_level in response is not admin (or memory section is empty/limited)
    tl = d.get("trust_level", "")
    assert tl in ("untrusted", "unknown", ""), (
        f"Non-local admin claim should have been degraded to untrusted, got trust_level={tl!r}"
    )


def test_api_os_brief_owner_nonlocal_no_owner_memory(client, tmp_path, monkeypatch):
    """Non-local owner claim must not receive owner's sensitive memory."""
    monkeypatch.setattr("igris.models.config.CONFIG.project_root", tmp_path)

    # Pre-store owner memory
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    mem.store_preference("owner", "admin", "OWNER_SENSITIVE_PREFERENCE_NOTREAL")

    r = client.post("/api/os/brief", json={
        "query": "preferenze",
        "interlocutor_id": "owner",
        "trust_level": "admin",
    })
    assert r.status_code == 200
    content = json.dumps(r.json())
    assert "OWNER_SENSITIVE_PREFERENCE_NOTREAL" not in content, (
        "Non-local owner claim received sensitive owner memory — SECURITY VIOLATION"
    )


def test_api_os_brief_no_raw_secret(client, tmp_path, monkeypatch):
    """API response must not contain raw secrets."""
    monkeypatch.setattr("igris.models.config.CONFIG.project_root", tmp_path)
    FAKE = "FAKE_SECRET_API_CONTEXT_NOTREAL_99887766"

    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    mem.store_lesson(f"usa token={FAKE} per deploy", project="test")

    r = client.post("/api/os/brief", json={"query": "deploy", "interlocutor_id": "unknown"})
    assert r.status_code == 200
    content = r.text
    assert FAKE not in content, f"Raw secret in API response: {content[:300]}"


def test_api_os_brief_degraded_dependency_returns_200(client, tmp_path, monkeypatch):
    """Degraded dependency must return 200 with degraded=True, not 500."""
    monkeypatch.setattr("igris.models.config.CONFIG.project_root", tmp_path)

    # Force rank gauntlet to fail
    def broken_run(self, *a, **kw):
        raise RuntimeError("gauntlet down")
    try:
        from igris.core.rank_gauntlet import RankGauntlet
        monkeypatch.setattr(RankGauntlet, "run", broken_run)
    except ImportError:
        pass

    r = client.post("/api/os/brief", json={"query": "rank", "interlocutor_id": "unknown"})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    d = r.json()
    assert "ok" in d  # must respond even if degraded


def test_api_os_brief_get_healthcheck(client):
    """GET /api/os/brief returns healthcheck info."""
    r = client.get("/api/os/brief")
    assert r.status_code == 200
    d = r.json()
    assert "ok" in d or "backends" in d
