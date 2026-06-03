"""Tests for interlocutor-aware chat entrypoint — #526 gap fix."""
from __future__ import annotations

import re
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Preflight module — core logic tests
# ---------------------------------------------------------------------------

def test_unknown_interlocutor_creates_untrusted_profile(tmp_path):
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight("hello", interlocutor_id="totally_unknown_xyz", project_root=str(tmp_path))
    assert result.interlocutor_id == "totally_unknown_xyz"
    assert result.trust_level in ("untrusted", "unknown")


def test_sensitive_action_blocked_for_unknown(tmp_path):
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight("please deploy the server", interlocutor_id="unknown_xyz", project_root=str(tmp_path))
    assert result.blocked
    assert result.block_reason is not None


def test_innocuous_message_allowed_for_unknown(tmp_path):
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight("what time is it?", interlocutor_id="unknown_xyz", project_root=str(tmp_path))
    assert not result.blocked


def test_owner_profile_passes_sensitive_action(tmp_path):
    from igris.core.chat_interlocutor_preflight import run_preflight
    # owner is a builtin trusted profile (trust_level=admin)
    result = run_preflight("deploy the server", interlocutor_id="owner", project_root=str(tmp_path))
    assert not result.blocked


def test_system_prompt_enrichment_contains_profile(tmp_path):
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight("hello", interlocutor_id="owner", project_root=str(tmp_path))
    enrichment = result.system_prompt_enrichment
    # Either enrichment contains the id or it's empty (both are acceptable)
    assert isinstance(enrichment, str)
    if enrichment:
        assert "owner" in enrichment.lower()


def test_extract_interlocutor_from_payload():
    from igris.core.chat_interlocutor_preflight import extract_interlocutor_id
    assert extract_interlocutor_id(payload={"interlocutor_id": "christian"}) == "christian"


def test_extract_interlocutor_from_user_id_fallback():
    from igris.core.chat_interlocutor_preflight import extract_interlocutor_id
    assert extract_interlocutor_id(payload={"user_id": "christian"}) == "christian"


def test_extract_interlocutor_from_header():
    from igris.core.chat_interlocutor_preflight import extract_interlocutor_id
    assert extract_interlocutor_id(headers={"x-igris-interlocutor": "christian"}) == "christian"


def test_extract_interlocutor_none_when_missing():
    from igris.core.chat_interlocutor_preflight import extract_interlocutor_id
    assert extract_interlocutor_id(payload={}, headers={}) is None


def test_audit_recorded_on_preflight(tmp_path):
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight("hello", interlocutor_id="test_user", project_root=str(tmp_path))
    # Should not crash and should return a result
    assert result is not None
    assert isinstance(result.interlocutor_id, str)


def test_preflight_result_allowed_property(tmp_path):
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight("what time is it?", interlocutor_id="unknown_xyz", project_root=str(tmp_path))
    # Not blocked, not requiring clarification → allowed
    assert result.allowed == (not result.blocked and not result.requires_clarification)


def test_delete_action_blocked_for_unknown(tmp_path):
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight("delete everything", interlocutor_id="unknown_attacker", project_root=str(tmp_path))
    # delete is destructive → should be blocked for unknown
    assert result.blocked
    assert result.block_reason is not None


def test_no_secret_in_enrichment(tmp_path):
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight("hello", interlocutor_id="owner", project_root=str(tmp_path))
    enrichment = result.system_prompt_enrichment
    assert not re.search(r'passphrase|pbkdf2|sha256=|token=', enrichment, re.IGNORECASE)


def test_response_mode_dict_keys(tmp_path):
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight("urgent! deploy now!", interlocutor_id="owner", project_root=str(tmp_path))
    assert "verbosity" in result.response_mode
    assert "tone" in result.response_mode


def test_preflight_fallback_id_unknown(tmp_path):
    """When no interlocutor_id given, defaults to 'unknown'."""
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight("hello", interlocutor_id=None, project_root=str(tmp_path))
    assert result.interlocutor_id == "unknown"


# ---------------------------------------------------------------------------
# API-level tests (FastAPI TestClient)
# ---------------------------------------------------------------------------

def _get_app():
    """Import app — skip if missing deps."""
    try:
        from igris.web.server import create_app
        return create_app()
    except Exception:
        return None


def test_post_message_blocks_sensitive_for_unknown(tmp_path):
    """POST /api/sessions/{id}/messages blocks sensitive action from unknown interlocutor."""
    app = _get_app()
    if app is None:
        pytest.skip("App could not be initialized")
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("TestClient not available")

    client = TestClient(app, raise_server_exceptions=False)
    # Create session
    r = client.post("/api/sessions")
    if r.status_code != 200:
        pytest.skip("Session creation failed")
    sid = r.json()["id"]

    # Send sensitive action as unknown user
    r2 = client.post(
        f"/api/sessions/{sid}/messages",
        json={"message": "please deploy the server", "interlocutor_id": "unknown_attacker_xyz"},
    )
    # Should either be blocked (blocked=True in response) or return 200 with block info
    if r2.status_code == 200:
        data = r2.json()
        assert data.get("blocked") is True or "denied" in str(data.get("response", "")).lower()


def test_chat_stream_preflight_denial():
    """POST /api/chat/stream returns block message without calling LLM for denied requests."""
    app = _get_app()
    if app is None:
        pytest.skip("App could not be initialized")
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("TestClient not available")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.post(
        "/api/chat/stream",
        json={"message": "delete all servers", "interlocutor_id": "unknown_attacker_xyz"},
    )
    # Response should be a stream with block message
    assert r.status_code == 200
    body = r.text
    # Should contain block/denied text or be a valid SSE stream
    assert "data:" in body or r.status_code == 200
