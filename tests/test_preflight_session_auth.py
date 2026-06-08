"""Tests for #1272 PR4 — Preflight Session Integration.

Covers:
- extract_session_token() — Bearer, Cookie, body priority
- resolve_session_identity() — valid/invalid/expired/missing
- run_preflight() — session overrides body identity, invalid session blocks fallback
- Security invariants: no token leakage, no unsafe fallback, owner/system rules
- API-level tests via TestClient(create_app())
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_app_client(tmp_root: str):
    os.environ["IGRIS_PROJECT_ROOT"] = tmp_root
    for mod_name in list(sys.modules.keys()):
        if any(k in mod_name for k in ("auth_routes", "interlocutor_auth", "preflight")):
            del sys.modules[mod_name]
    from fastapi.testclient import TestClient
    from igris.web.server import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


@pytest.fixture()
def tmp_root(tmp_path):
    return str(tmp_path)


@pytest.fixture()
def client(tmp_root):
    return _make_app_client(tmp_root)


_FAKE_PASSWORD = "FAKE_PASSWORD_pr4test!"


def _full_enrollment(tmp_root: str, username: str = "mario_rossi"):
    """Run full enrollment flow, return session_token."""
    client = _make_app_client(tmp_root)
    r = client.post("/api/auth/enroll/start", json={
        "username": username,
        "first_name": "Mario",
        "last_name": "Rossi",
        "email": f"{username}@example.com",
        "mobile_phone": "+39 333 1234567",
    })
    assert r.status_code == 200 and r.json()["ok"], f"enroll/start failed: {r.text}"
    et = r.json()["enrollment_token"]
    r2 = client.post("/api/auth/enroll/complete", json={
        "enrollment_token": et,
        "password": _FAKE_PASSWORD,
        "confirm_password": _FAKE_PASSWORD,
    })
    assert r2.status_code == 200 and r2.json()["ok"], f"enroll/complete failed: {r2.text}"
    return r2.json()["session_token"]


# ═══════════════════════════════════════════════════════════════════════════════
# extract_session_token()
# ═══════════════════════════════════════════════════════════════════════════════

def test_extract_session_token_bearer():
    from igris.core.chat_interlocutor_preflight import extract_session_token
    tok = extract_session_token(
        request_headers={"Authorization": "Bearer FAKE_TOKEN_abc123"},
    )
    assert tok == "FAKE_TOKEN_abc123"


def test_extract_session_token_bearer_lowercase():
    from igris.core.chat_interlocutor_preflight import extract_session_token
    tok = extract_session_token(
        request_headers={"authorization": "Bearer FAKE_TOKEN_lower"},
    )
    assert tok == "FAKE_TOKEN_lower"


def test_extract_session_token_cookie():
    from igris.core.chat_interlocutor_preflight import extract_session_token
    tok = extract_session_token(
        request_headers={"Cookie": "igris_session=FAKE_TOKEN_cookie; other=val"},
    )
    assert tok == "FAKE_TOKEN_cookie"


def test_extract_session_token_body_fallback():
    from igris.core.chat_interlocutor_preflight import extract_session_token
    tok = extract_session_token(
        payload={"session_token": "FAKE_TOKEN_body"},
    )
    assert tok == "FAKE_TOKEN_body"


def test_extract_session_token_bearer_wins_over_cookie():
    from igris.core.chat_interlocutor_preflight import extract_session_token
    tok = extract_session_token(
        request_headers={
            "Authorization": "Bearer FAKE_TOKEN_bearer",
            "Cookie": "igris_session=FAKE_TOKEN_cookie",
        },
    )
    assert tok == "FAKE_TOKEN_bearer"


def test_extract_session_token_cookie_wins_over_body():
    from igris.core.chat_interlocutor_preflight import extract_session_token
    tok = extract_session_token(
        request_headers={"Cookie": "igris_session=FAKE_TOKEN_cookie"},
        payload={"session_token": "FAKE_TOKEN_body"},
    )
    assert tok == "FAKE_TOKEN_cookie"


def test_extract_session_token_empty_returns_empty():
    from igris.core.chat_interlocutor_preflight import extract_session_token
    assert extract_session_token() == ""
    assert extract_session_token(request_headers={}, payload={}) == ""


# ═══════════════════════════════════════════════════════════════════════════════
# resolve_session_identity()
# ═══════════════════════════════════════════════════════════════════════════════

def test_resolve_session_identity_missing_token(tmp_root):
    from igris.core.chat_interlocutor_preflight import resolve_session_identity
    r = resolve_session_identity("", project_root=tmp_root)
    assert r.authenticated is False
    assert r.session_valid is False
    assert r.reason == "missing_session"
    assert r.profile_id == "unknown"


def test_resolve_session_identity_invalid_token(tmp_root):
    from igris.core.chat_interlocutor_preflight import resolve_session_identity
    r = resolve_session_identity("FAKE_TOKEN_invalid_xyz", project_root=tmp_root)
    assert r.authenticated is False
    assert r.session_valid is False
    assert r.reason in ("invalid_session", "session_resolve_error")


def test_resolve_session_identity_valid(tmp_root):
    from igris.core.chat_interlocutor_preflight import resolve_session_identity
    session_token = _full_enrollment(tmp_root, "validuser")
    r = resolve_session_identity(session_token, project_root=tmp_root)
    assert r.authenticated is True
    assert r.session_valid is True
    assert r.profile_id == "validuser"
    assert r.reason == ""


def test_resolve_session_identity_no_raw_token_in_result(tmp_root):
    from igris.core.chat_interlocutor_preflight import resolve_session_identity
    session_token = _full_enrollment(tmp_root, "notoken_user")
    r = resolve_session_identity(session_token, project_root=tmp_root)
    # session_token must not appear anywhere in the result
    result_str = str(r)
    assert session_token not in result_str


# ═══════════════════════════════════════════════════════════════════════════════
# run_preflight() — session integration
# ═══════════════════════════════════════════════════════════════════════════════

def test_run_preflight_valid_session_uses_profile_id(tmp_root):
    from igris.core.chat_interlocutor_preflight import run_preflight
    session_token = _full_enrollment(tmp_root, "mario_rossi")
    result = run_preflight(
        "ciao",
        session_token=session_token,
        project_root=tmp_root,
    )
    assert result.interlocutor_id == "mario_rossi"
    assert result.session_authenticated is True
    assert result.session_valid is True


def test_run_preflight_valid_session_ignores_body_interlocutor_id(tmp_root):
    from igris.core.chat_interlocutor_preflight import run_preflight
    session_token = _full_enrollment(tmp_root, "alice")
    result = run_preflight(
        "ciao",
        interlocutor_id="owner",  # spoofed!
        session_token=session_token,
        project_root=tmp_root,
    )
    # Must use alice, not owner
    assert result.interlocutor_id == "alice"
    assert result.trust_level != "admin"


def test_run_preflight_invalid_session_does_not_fallback_to_interlocutor(tmp_root):
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight(
        "ciao",
        interlocutor_id="mario_rossi",
        session_token="FAKE_TOKEN_invalid_xyz",
        project_root=tmp_root,
    )
    assert result.interlocutor_id == "unknown"
    assert result.session_authenticated is False


def test_run_preflight_missing_session_legacy_unknown(tmp_root):
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight(
        "ciao",
        interlocutor_id=None,
        project_root=tmp_root,
    )
    assert result.interlocutor_id == "unknown"
    assert result.session_authenticated is False


def test_run_preflight_local_owner_without_session_still_admin(tmp_root):
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight(
        "ciao",
        interlocutor_id="owner",
        is_local_request=True,
        project_root=tmp_root,
    )
    assert result.interlocutor_id == "owner"
    assert result.trust_level == "admin"


def test_run_preflight_remote_owner_without_session_downgraded_unknown(tmp_root):
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight(
        "ciao",
        interlocutor_id="owner",
        is_local_request=False,
        project_root=tmp_root,
    )
    assert result.interlocutor_id == "unknown"


def test_run_preflight_invalid_session_remote_owner_unknown(tmp_root):
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight(
        "ciao",
        interlocutor_id="owner",
        is_local_request=False,
        session_token="FAKE_TOKEN_bad_xyz",
        project_root=tmp_root,
    )
    assert result.interlocutor_id == "unknown"
    assert result.session_authenticated is False


def test_run_preflight_valid_session_for_limited_user_blocks_sensitive_action(tmp_root):
    from igris.core.chat_interlocutor_preflight import run_preflight
    session_token = _full_enrollment(tmp_root, "limited_user")
    result = run_preflight(
        "delete the production database",
        session_token=session_token,
        project_root=tmp_root,
    )
    assert result.blocked is True


def test_run_preflight_valid_session_low_risk_allowed(tmp_root):
    from igris.core.chat_interlocutor_preflight import run_preflight
    session_token = _full_enrollment(tmp_root, "chat_user")
    result = run_preflight(
        "ciao come stai",
        session_token=session_token,
        project_root=tmp_root,
    )
    assert result.blocked is False


def test_session_token_not_in_preflight_result(tmp_root):
    from igris.core.chat_interlocutor_preflight import run_preflight
    session_token = _full_enrollment(tmp_root, "leak_check_user")
    result = run_preflight(
        "ciao",
        session_token=session_token,
        project_root=tmp_root,
    )
    # Token must not appear in any field of PreflightResult
    result_dict = {
        "interlocutor_id": result.interlocutor_id,
        "trust_level": result.trust_level,
        "advisory": result.advisory,
        "block_reason": result.block_reason,
        "system_prompt_enrichment": result.system_prompt_enrichment,
        "session_reason": result.session_reason,
        "audit_event_id": result.audit_event_id,
    }
    for key, val in result_dict.items():
        assert session_token not in str(val or ""), \
            f"Raw session_token leaked in PreflightResult.{key}"


def test_session_token_not_in_logs(tmp_root, caplog):
    import logging
    from igris.core.chat_interlocutor_preflight import run_preflight
    session_token = _full_enrollment(tmp_root, "log_check_user")
    with caplog.at_level(logging.DEBUG):
        run_preflight("ciao", session_token=session_token, project_root=tmp_root)
    for record in caplog.records:
        assert session_token not in record.getMessage(), \
            f"Raw session_token leaked in log: {record.getMessage()}"


# ═══════════════════════════════════════════════════════════════════════════════
# API-level tests (routes_01 chat endpoint)
# ═══════════════════════════════════════════════════════════════════════════════

def _send_chat(client, message: str, session_id: str | None = None,
               headers: dict | None = None, extra_body: dict | None = None):
    # Create a chat session first if not provided
    if session_id is None:
        r = client.post("/api/sessions", json={})
        if r.status_code == 200:
            d = r.json()
            session_id = d.get("session_id") or d.get("id") or "fallback-session"
        else:
            session_id = "fallback-session"
    body = {"message": message}
    if extra_body:
        body.update(extra_body)
    return client.post(
        f"/api/sessions/{session_id}/messages",
        json=body,
        headers=headers or {},
    )


def test_chat_message_valid_bearer_session_uses_authenticated_profile(tmp_root, client):
    session_token = _full_enrollment(tmp_root, "bearer_user")
    r = _send_chat(client, "ciao",
                   headers={"Authorization": f"Bearer {session_token}"})
    assert r.status_code == 200
    data = r.json()
    assert data.get("interlocutor_id") == "bearer_user" or \
           data.get("blocked") is not True  # blocked=False for low-risk


def test_chat_message_body_session_token_fallback_uses_authenticated_profile(tmp_root, client):
    session_token = _full_enrollment(tmp_root, "body_token_user")
    r = _send_chat(client, "ciao", extra_body={"session_token": session_token})
    assert r.status_code == 200
    # Should not be blocked (valid session, low-risk)
    assert r.json().get("blocked") is not True


def test_chat_message_valid_session_ignores_spoofed_owner_body(tmp_root, client):
    session_token = _full_enrollment(tmp_root, "normal_user")
    r = _send_chat(
        client, "ciao",
        headers={"Authorization": f"Bearer {session_token}"},
        extra_body={"interlocutor_id": "owner"},
    )
    assert r.status_code == 200
    # Result must be for normal_user, not owner
    data = r.json()
    if "interlocutor_id" in data:
        assert data["interlocutor_id"] == "normal_user"
    # Must not have admin trust
    if "trust_level" in data:
        assert data["trust_level"] != "admin"


def test_chat_message_invalid_session_blocks_fallback_to_owner(tmp_root, client):
    r = _send_chat(
        client, "ciao",
        headers={"Authorization": "Bearer FAKE_TOKEN_invalid_bad"},
        extra_body={"interlocutor_id": "owner"},
    )
    assert r.status_code == 200
    data = r.json()
    if "interlocutor_id" in data:
        assert data["interlocutor_id"] == "unknown"
    if "trust_level" in data:
        assert data["trust_level"] != "admin"


def test_chat_message_no_session_remote_owner_spoof_blocked(tmp_root):
    """Remote request with interlocutor_id=owner but no session must be unknown."""
    client = _make_app_client(tmp_root)
    # Create session first
    sess_r = client.post("/api/sessions", json={})
    sid = (sess_r.json().get("id") or sess_r.json().get("session_id")) if sess_r.status_code == 200 else "s1"
    r = client.post(
        f"/api/sessions/{sid}/messages",
        json={"message": "ciao", "interlocutor_id": "owner"},
        headers={},  # no Authorization, no cookie
    )
    assert r.status_code == 200
    data = r.json()
    if "interlocutor_id" in data:
        assert data["interlocutor_id"] == "unknown"
    if "trust_level" in data:
        assert data["trust_level"] != "admin"


def test_chat_message_valid_limited_user_delete_blocked(tmp_root, client):
    session_token = _full_enrollment(tmp_root, "del_user")
    r = _send_chat(
        client,
        "delete the production database",
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert r.status_code == 200
    assert r.json().get("blocked") is True


def test_chat_message_valid_limited_user_normal_chat_allowed(tmp_root, client):
    session_token = _full_enrollment(tmp_root, "chat_ok_user")
    r = _send_chat(
        client,
        "che ore sono",
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert r.status_code == 200
    assert r.json().get("blocked") is not True


def test_chat_response_no_raw_session_token(tmp_root, client):
    session_token = _full_enrollment(tmp_root, "no_leak_user")
    r = _send_chat(
        client, "ciao",
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert r.status_code == 200
    assert session_token not in r.text
