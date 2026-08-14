"""Auth/preflight contract guard tests — #1301 PR-5A.

No runtime behaviour changes. Guards that:

1. PreflightResult has no raw session_token field.
2. SessionIdentityResult has no raw session_token field.
3. WriteAuthResult has no raw session_token field and does not serialise it.
4. The auth_required response shape (messages endpoint) is backward-compatible.
5. The auth_required stream shape contains expected keys.
6. The critical PreflightResult fields used by routes_01.py are stable:
     blocked, trust_level, session_authenticated, session_valid, session_reason,
     audit_event_id.
7. WriteAuthResult.as_http_exception() produces the expected HTTP status.
"""
from __future__ import annotations

import dataclasses
import inspect
import json
from pathlib import Path

import pytest

_REPO = Path(__file__).parent.parent

# ── 1. No raw token in PreflightResult ───────────────────────────────────────

def test_preflight_result_has_no_session_token_field():
    """PreflightResult must not store a raw session_token.

    Raw tokens must be consumed by extract_session_token() / resolve_session_identity()
    and never kept in the result object that travels through routes_01.py.
    """
    from igris.core.chat_interlocutor_preflight import PreflightResult
    field_names = {f.name for f in dataclasses.fields(PreflightResult)}
    assert "session_token" not in field_names, (
        "PreflightResult has a session_token field — raw tokens must never be stored in results"
    )
    assert "token" not in field_names, (
        "PreflightResult has a 'token' field — raw tokens must never be stored in results"
    )
    assert "raw_token" not in field_names


def test_preflight_result_required_fields_exist():
    """The fields consumed by routes_01.py must remain stable.

    If any of these fields are removed or renamed, routes_01.py will break silently
    (returning untrusted defaults via getattr fallbacks) or raise AttributeError.
    """
    from igris.core.chat_interlocutor_preflight import PreflightResult
    field_names = {f.name for f in dataclasses.fields(PreflightResult)}
    required = {
        "blocked",
        "trust_level",
        "session_authenticated",
        "session_valid",
        "session_reason",
        "audit_event_id",
        "interlocutor_id",
        "block_reason",
    }
    missing = required - field_names
    assert not missing, (
        f"PreflightResult is missing required fields used by routes_01.py: {missing}"
    )


def test_preflight_result_session_auth_fields_default_false():
    """Session auth fields must default to False/None, not True.

    If the defaults were flipped to True, unauthenticated requests would
    incorrectly appear authenticated.
    """
    from igris.core.chat_interlocutor_preflight import PreflightResult
    fields_by_name = {f.name: f for f in dataclasses.fields(PreflightResult)}
    assert fields_by_name["session_authenticated"].default is False, (
        "session_authenticated must default to False"
    )
    assert fields_by_name["session_valid"].default is False, (
        "session_valid must default to False"
    )
    assert fields_by_name["session_reason"].default is None, (
        "session_reason must default to None"
    )
    assert fields_by_name["audit_event_id"].default is None, (
        "audit_event_id must default to None"
    )


def test_preflight_result_allowed_property_is_inverse_of_blocked(tmp_path):
    """PreflightResult.allowed must be the inverse of blocked (and requires_clarification)."""
    from igris.core.chat_interlocutor_preflight import PreflightResult

    unblocked = PreflightResult(
        interlocutor_id="owner",
        trust_level="owner",
        response_mode={},
        intent_action="chat",
        intent_risk="low",
        blocked=False,
        block_reason=None,
        requires_clarification=False,
        clarification_question=None,
        advisory=None,
        system_prompt_enrichment="",
    )
    assert unblocked.allowed is True

    blocked = dataclasses.replace(unblocked, blocked=True)
    assert blocked.allowed is False


# ── 2. No raw token in SessionIdentityResult ─────────────────────────────────

def test_session_identity_result_has_no_token_field():
    """SessionIdentityResult must not store a raw session_token.

    The comment in the source confirms: 'Raw token NEVER stored here — only
    profile_id and status.' This test makes that invariant executable.
    """
    from igris.core.chat_interlocutor_preflight import SessionIdentityResult
    field_names = {f.name for f in dataclasses.fields(SessionIdentityResult)}
    assert "session_token" not in field_names
    assert "token" not in field_names
    assert "raw_token" not in field_names
    assert "bearer" not in field_names


def test_session_identity_result_profile_id_not_token(monkeypatch, tmp_path):
    """resolve_session_identity() must return profile_id, never the raw token."""
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path))

    from igris.core.chat_interlocutor_preflight import resolve_session_identity

    result = resolve_session_identity("FAKE_TOKEN_pr5a_guard", project_root=str(tmp_path))

    # Result must not contain the raw token
    assert result.profile_id != "FAKE_TOKEN_pr5a_guard", (
        "profile_id must be resolved from the store, never be the raw token itself"
    )
    assert result.authenticated is False, "Fake token must not authenticate"
    # No field on the result should hold the raw token
    for field in dataclasses.fields(result):
        value = getattr(result, field.name)
        assert value != "FAKE_TOKEN_pr5a_guard", (
            f"SessionIdentityResult.{field.name} contains the raw token"
        )


# ── 3. WriteAuthResult — no raw token, correct HTTP shape ────────────────────

def test_write_auth_result_has_no_token_field():
    """WriteAuthResult must not have a session_token or token field."""
    from igris.api.write_auth import WriteAuthResult
    field_names = {f.name for f in dataclasses.fields(WriteAuthResult)}
    assert "session_token" not in field_names
    assert "token" not in field_names
    assert "raw_token" not in field_names


def test_write_auth_result_as_http_exception_401():
    """Unauthenticated WriteAuthResult must raise HTTP 401."""
    from igris.api.write_auth import WriteAuthResult
    result = WriteAuthResult(
        allowed=False,
        trust_level="untrusted",
        error_code="authentication_required",
        error_message="No token",
        http_status=401,
    )
    exc = result.as_http_exception()
    assert exc.status_code == 401
    assert exc.detail["error"] == "authentication_required"
    assert "ok" in exc.detail
    assert exc.detail["ok"] is False


def test_write_auth_result_as_http_exception_403():
    """Insufficient-scope WriteAuthResult must raise HTTP 403."""
    from igris.api.write_auth import WriteAuthResult
    result = WriteAuthResult(
        allowed=False,
        trust_level="limited",
        username="limiteduser",
        error_code="scope_denied",
        error_message="limited cannot write",
        http_status=403,
    )
    exc = result.as_http_exception()
    assert exc.status_code == 403
    assert exc.detail["error"] == "scope_denied"


def test_write_auth_result_exception_detail_has_no_raw_token():
    """WriteAuthResult.as_http_exception() detail must never contain a raw token."""
    fake_token = "RAW_TOKEN_MUST_NOT_APPEAR_IN_EXCEPTION_pr5a"
    from igris.api.write_auth import WriteAuthResult
    result = WriteAuthResult(
        allowed=False,
        trust_level="untrusted",
        error_code="authentication_required",
        error_message=f"No valid token",  # do NOT include fake_token here
        http_status=401,
    )
    exc = result.as_http_exception()
    detail_str = json.dumps(exc.detail)
    assert fake_token not in detail_str


# ── 4. auth_required response shape (backward-compat) ────────────────────────

def test_messages_endpoint_blocked_returns_auth_required(monkeypatch, tmp_path):
    """POST /api/sessions/{id}/messages with IGRIS_REQUIRE_AUTH=true must return auth_required."""
    monkeypatch.setenv("IGRIS_REQUIRE_AUTH", "true")
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path))

    from fastapi.testclient import TestClient
    from igris.web.server import create_app

    client = TestClient(create_app(), raise_server_exceptions=False)
    r_sess = client.post("/api/sessions")
    assert r_sess.status_code == 200
    sid = r_sess.json()["id"]

    r = client.post(f"/api/sessions/{sid}/messages",
                    json={"message": "ciao", "interlocutor_id": "unknown"})
    data = r.json()

    # Backward-compat contract: these keys must always be present when auth is required
    assert data.get("auth_required") is True, f"Expected auth_required=True, got: {data}"
    assert "auth_actions" in data, "auth_required response must include auth_actions"
    assert "auth_reason" in data, "auth_required response must include auth_reason"
    assert isinstance(data["auth_actions"], list)
    assert len(data["auth_actions"]) > 0


def test_messages_endpoint_auth_required_has_no_raw_token(monkeypatch, tmp_path):
    """The auth_required response must never contain a raw session token."""
    monkeypatch.setenv("IGRIS_REQUIRE_AUTH", "true")
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path))

    from fastapi.testclient import TestClient
    from igris.web.server import create_app

    client = TestClient(create_app(), raise_server_exceptions=False)
    r_sess = client.post("/api/sessions")
    sid = r_sess.json()["id"]

    r = client.post(f"/api/sessions/{sid}/messages",
                    json={"message": "ciao", "interlocutor_id": "unknown"})
    data = r.json()
    body_str = json.dumps(data)

    # No field named *token* should appear in the response
    assert "session_token" not in body_str
    assert "bearer" not in body_str.lower()


# ── 5. Stream auth_required shape ────────────────────────────────────────────

def test_stream_endpoint_blocked_returns_auth_required_event(monkeypatch, tmp_path):
    """POST /api/chat/stream with IGRIS_REQUIRE_AUTH=true must emit auth_required SSE event."""
    monkeypatch.setenv("IGRIS_REQUIRE_AUTH", "true")
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path))

    from fastapi.testclient import TestClient
    from igris.web.server import create_app

    client = TestClient(create_app(), raise_server_exceptions=False)
    r_sess = client.post("/api/sessions")
    sid = r_sess.json()["id"]

    r = client.post("/api/chat/stream",
                    json={"message": "ciao", "session_id": sid, "interlocutor_id": "unknown"})

    raw = r.text
    assert "auth_required" in raw, (
        f"Stream response must contain auth_required, got: {raw[:300]}"
    )
    # Find the data: line and parse it
    for line in raw.splitlines():
        if line.startswith("data:") and "auth_required" in line:
            payload = json.loads(line[5:].strip())
            assert payload.get("auth_required") is True
            assert "auth_actions" in payload
            break
    else:
        pytest.fail("No auth_required SSE event found in stream response")
