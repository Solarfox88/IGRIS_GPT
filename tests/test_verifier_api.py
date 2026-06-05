"""API tests for Verifier Registry routes (#1246)."""
import pytest
import json
import re
from fastapi.testclient import TestClient
from igris.web.server import create_app


@pytest.fixture
def client():
    return TestClient(create_app(), raise_server_exceptions=False)


def _deploy_mission_payload():
    return {
        "mission": {
            "mission_id": "test_deploy_mission",
            "title": "Deploy test",
            "route": "deploy_operation",
            "risk": "high",
            "status": "waiting_approval",
            "execution_mode": "approval_required",
            "interlocutor_id": "owner",
            "trust_level": "admin",
            "requires_approval": True,
            "blocked": False,
            "steps": [
                {
                    "step_id": "s1",
                    "title": "Deploy step",
                    "action_type": "deploy",
                    "risk": "high",
                    "requires_approval": True,
                    "dry_run_only": True,
                }
            ],
        }
    }


def test_api_verifier_mission_returns_bundle(client):
    """POST /api/verifier/mission returns EvidenceBundle."""
    r = client.post("/api/verifier/mission", json=_deploy_mission_payload())
    assert r.status_code == 200
    d = r.json()
    assert "ok" in d, f"'ok' missing from response: {list(d.keys())}"
    assert "bundle" in d, f"'bundle' missing from response: {list(d.keys())}"
    bundle = d["bundle"]
    assert bundle is not None
    assert "mission_id" in bundle
    assert "results" in bundle
    assert len(bundle["results"]) > 0


def test_api_verifier_mission_deploy_requires_approval(client):
    """Deploy mission must pass approval policy verification."""
    r = client.post("/api/verifier/mission", json=_deploy_mission_payload())
    assert r.status_code == 200
    d = r.json()
    bundle = d.get("bundle") or {}
    results = bundle.get("results", [])
    # Approval policy verifier must pass (deploy correctly has requires_approval=True)
    approval_result = next((res for res in results if res.get("verifier_id") == "approval_policy"), None)
    if approval_result:
        assert approval_result.get("passed") is True, (
            f"Approval policy verifier should pass for deploy with requires_approval=True: {approval_result}"
        )


def test_api_verifier_mission_no_raw_secret(client):
    """API response must not contain raw secrets even if mission contains fake secret."""
    FAKE = "FAKE_TOKEN_VERIFY_API_NOTREAL_99887766"
    payload = {
        "mission": {
            "mission_id": "secret_test",
            "title": f"Mission with token={FAKE}",
            "route": "deploy_operation",
            "risk": "high",
            "status": "waiting_approval",
            "execution_mode": "approval_required",
            "interlocutor_id": "owner",
            "trust_level": "admin",
            "requires_approval": True,
            "blocked": False,
            "steps": [],
        }
    }
    r = client.post("/api/verifier/mission", json=payload)
    assert r.status_code == 200
    content = r.text
    assert FAKE not in content, f"Raw secret in API response: {content[:300]}"


def test_api_verifier_health(client):
    """GET /api/verifier/health returns health info."""
    r = client.get("/api/verifier/health")
    assert r.status_code == 200
    d = r.json()
    assert "ok" in d or "backends" in d or "verifiers_registered" in d


def test_api_verifier_invalid_payload_returns_safe_error(client):
    """POST /api/verifier/mission with empty/invalid payload returns safe error."""
    # Empty body
    r = client.post("/api/verifier/mission", json={})
    assert r.status_code in (200, 400, 422), f"Unexpected status: {r.status_code}"
    d = r.json()
    # Must not contain raw stacktrace
    content = json.dumps(d)
    assert "Traceback" not in content, "Stacktrace leaked in error response"
    assert "mission payload required" in content or "error" in d or "ok" in d

    # Null mission
    r2 = client.post("/api/verifier/mission", json={"mission": None})
    assert r2.status_code in (200, 400, 422)
    d2 = r2.json()
    assert "Traceback" not in json.dumps(d2)

    # Totally invalid
    r3 = client.post("/api/verifier/mission", content=b"not json",
                      headers={"Content-Type": "application/json"})
    assert r3.status_code in (200, 400, 422)
