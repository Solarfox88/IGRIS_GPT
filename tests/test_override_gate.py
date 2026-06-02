from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from igris.core.gate_override import GateOverride, _SHARED_GATE_OVERRIDE
from igris.web.server import create_app


@pytest.fixture(autouse=True)
def _reset_shared_gate_override() -> None:
    _SHARED_GATE_OVERRIDE.reset()
    yield
    _SHARED_GATE_OVERRIDE.reset()


class TestGateOverrideCore:
    def test_generate_otp_clamps_ttl_to_15_minutes(self) -> None:
        gate = GateOverride()
        code = gate.generate_otp("admin", ttl=9999, scope="deploy", mission_id="m-1")
        assert len(code) == 6
        record = gate._records[code]
        assert record.ttl <= gate.MAX_TTL_SECONDS
        assert record.scope == "deploy"

    def test_validate_scope_must_match(self) -> None:
        gate = GateOverride()
        code = gate.generate_otp("admin", ttl=60, scope="deploy")
        assert gate.validate_otp(code, scope="deploy") is True
        assert gate.validate_otp(code, scope="memory") is False

    def test_request_confirm_consumes_and_revokes_override(self) -> None:
        gate = GateOverride()
        code = gate.request_override(
            user="admin",
            scope="deploy",
            ttl=60,
            reason="deploy staging",
            mission_id="mission-1",
        )
        gate.request_physical_approval(code)
        gate.approve_physically(code, approved_by="operator")
        assert gate.confirm_override(code, approved_by="operator", scope="deploy", mission_id="mission-1")
        assert gate.validate_otp(code) is False
        logs = gate.get_audit_logs()
        assert any(entry["action"] == "confirmed" for entry in logs)
        assert any(entry["action"] == "revoked" for entry in logs)

    def test_expired_override_is_auto_revoked(self) -> None:
        gate = GateOverride()
        code = gate.generate_otp("admin", ttl=0, scope="deploy")
        revoked = gate.revoke_expired()
        assert code in revoked
        assert gate.validate_otp(code) is False


class TestOverrideGateAPI:
    def test_request_and_confirm_override(self) -> None:
        client = TestClient(create_app())
        request_resp = client.post(
            "/api/safety/override/request",
            json={
                "user": "admin",
                "scope": "deploy",
                "ttl": 60,
                "reason": "deploy staging",
                "mission_id": "mission-1",
            },
        )
        assert request_resp.status_code == 200
        request_body = request_resp.json()
        code = request_body["code"]
        assert request_body["scope"] == "deploy"
        assert request_body["approved"] is False

        confirm_resp = client.post(
            "/api/safety/override/confirm",
            json={
                "approval_token": code,
                "approved_by": "operator",
                "scope": "deploy",
                "mission_id": "mission-1",
            },
        )
        assert confirm_resp.status_code == 200
        confirm_body = confirm_resp.json()
        assert confirm_body["confirmed"] is True
        assert confirm_body["code"] == code

    def test_confirm_override_rejects_scope_mismatch(self) -> None:
        client = TestClient(create_app())
        request_resp = client.post(
            "/api/safety/override/request",
            json={
                "user": "admin",
                "scope": "deploy",
                "ttl": 60,
                "reason": "deploy staging",
                "mission_id": "mission-1",
            },
        )
        code = request_resp.json()["code"]
        bad = client.post(
            "/api/safety/override/confirm",
            json={
                "approval_token": code,
                "approved_by": "operator",
                "scope": "memory",
                "mission_id": "mission-1",
            },
        )
        assert bad.status_code == 403

    def test_status_endpoint_lists_active_overrides(self) -> None:
        client = TestClient(create_app())
        client.post(
            "/api/safety/override/request",
            json={"user": "admin", "scope": "deploy", "ttl": 60, "reason": "deploy"},
        )
        resp = client.get("/api/safety/override/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["active_count"] == 1
        assert body["audit_count"] >= 2
        assert body["active_overrides"][0]["scope"] == "deploy"
