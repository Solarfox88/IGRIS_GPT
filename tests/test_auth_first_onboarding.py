"""Tests for Fix #1278 — Auth-first onboarding gate.

Backend: unauthenticated REMOTE requests to chat endpoints return
  { auth_required: True, auth_actions: [...] }
  BEFORE any LLM call.

Frontend (static): app.js intercepts unauthenticated sends,
  auth.js provides intent detection helpers.

NOTE: TestClient is treated as "local" (is_trusted_local_request returns True
for host="testclient"). Backend gate tests that need to simulate a remote
request use unittest.mock.patch to override is_trusted_local_request → False.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO = Path(__file__).parent.parent
_AUTH_JS = _REPO / "igris/web/static/js/auth.js"
_APP_JS = _REPO / "igris/web/static/js/app.js"

# Module path used by routes_01 when it locally imports is_trusted_local_request
_PREFLIGHT_MODULE = "igris.core.chat_interlocutor_preflight"


@contextmanager
def _simulate_remote():
    """Simulate a remote unauthenticated request:
    - Patch is_trusted_local_request → False (remote host)
    - Set IGRIS_REQUIRE_AUTH=true (gate enabled)
    """
    import os
    old = os.environ.get("IGRIS_REQUIRE_AUTH", "")
    os.environ["IGRIS_REQUIRE_AUTH"] = "true"
    try:
        with patch(f"{_PREFLIGHT_MODULE}.is_trusted_local_request", return_value=False):
            yield
    finally:
        if old:
            os.environ["IGRIS_REQUIRE_AUTH"] = old
        else:
            os.environ.pop("IGRIS_REQUIRE_AUTH", None)


# ── Backend helpers ───────────────────────────────────────────────────────────

def _client():
    from fastapi.testclient import TestClient
    from igris.web.server import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


def _make_session(client) -> str:
    r = client.post("/api/sessions")
    assert r.status_code == 200
    return r.json()["id"]


def _chat(client, session_id, message, headers=None) -> dict:
    h = headers or {}
    r = client.post(
        f"/api/sessions/{session_id}/messages",
        json={"message": message, "interlocutor_id": "unknown"},
        headers=h,
    )
    return {"status": r.status_code, "data": r.json()}


# ── Tests: post_message gate (simulated remote) ───────────────────────────────

def test_unauthenticated_remote_gets_auth_required():
    """Remote request with no session token → auth_required: True."""
    client = _client()
    sid = _make_session(client)
    with _simulate_remote():
        resp = _chat(client, sid, "ciao", headers={})
    assert resp["data"].get("auth_required") is True, \
        f"Expected auth_required=True, got: {resp['data']}"


def test_unauthenticated_remote_auth_actions():
    """Auth-required response lists login and enroll actions."""
    client = _client()
    sid = _make_session(client)
    with _simulate_remote():
        resp = _chat(client, sid, "ciao", headers={})
    data = resp["data"]
    assert "auth_actions" in data, "auth_actions missing"
    assert "login" in data["auth_actions"]
    assert "enroll" in data["auth_actions"]


def test_unauthenticated_remote_no_llm_response():
    """Gate fires BEFORE LLM — response is deterministic Italian string."""
    client = _client()
    sid = _make_session(client)
    with _simulate_remote():
        resp = _chat(client, sid, "dimmi qualcosa", headers={})
    data = resp["data"]
    assert data.get("auth_required") is True
    # Response must be the deterministic gate message, not an LLM response
    resp_text = data.get("response", "")
    assert "riconoscerti" in resp_text or "autent" in resp_text or resp_text == "", \
        f"Unexpected LLM response leaked through gate: {resp_text}"


def test_unauthenticated_remote_trust_level_untrusted():
    """Gate response reports untrusted trust level."""
    client = _client()
    sid = _make_session(client)
    with _simulate_remote():
        resp = _chat(client, sid, "ciao", headers={})
    data = resp["data"]
    if "trust_level" in data:
        assert data["trust_level"] == "untrusted"


def test_unauthenticated_remote_interlocutor_unknown():
    """Gate response reports unknown interlocutor_id."""
    client = _client()
    sid = _make_session(client)
    with _simulate_remote():
        resp = _chat(client, sid, "ciao", headers={})
    data = resp["data"]
    if "interlocutor_id" in data:
        assert data["interlocutor_id"] == "unknown"


def test_unauthenticated_remote_auth_reason_present():
    """Gate response includes auth_reason field."""
    client = _client()
    sid = _make_session(client)
    with _simulate_remote():
        resp = _chat(client, sid, "ciao", headers={})
    data = resp["data"]
    assert "auth_reason" in data, "auth_reason missing from gate response"


def test_unauthenticated_remote_status_200():
    """Gate returns HTTP 200 (not 401 — client handles auth_required flag)."""
    client = _client()
    sid = _make_session(client)
    with _simulate_remote():
        resp = _chat(client, sid, "ciao", headers={})
    assert resp["status"] == 200, f"Expected 200, got {resp['status']}"


def test_authenticated_request_passes_gate():
    """A request with a valid session token should NOT be gated even when simulated remote."""
    import os, sys, time

    # Use a fresh tmp dir so auth data is isolated
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["IGRIS_PROJECT_ROOT"] = tmp
        # Clear cached auth modules so they pick up new path
        for k in list(sys.modules.keys()):
            if any(x in k for x in ("auth_routes", "interlocutor_auth")):
                del sys.modules[k]

        from fastapi.testclient import TestClient
        from igris.web.server import create_app
        client = TestClient(create_app(), raise_server_exceptions=False)

        _uname = "gatetest_" + str(int(time.time() * 1000))[-6:]
        r1 = client.post("/api/auth/enroll/start", json={
            "username": _uname,
            "first_name": "Gate",
            "last_name": "Test",
            "email": f"{_uname}@example.com",
            "mobile_phone": "+390000000001",
        })
        assert r1.status_code == 200 and r1.json().get("ok") is True, r1.text
        etok = r1.json()["enrollment_token"]

        r2 = client.post("/api/auth/enroll/complete", json={
            "enrollment_token": etok,
            "password": "FAKE_PASSWORD_GATE_1278",
            "confirm_password": "FAKE_PASSWORD_GATE_1278",
        })
        assert r2.status_code == 200 and r2.json().get("ok") is True, r2.text
        session_token = r2.json()["session_token"]

        sid = _make_session(client)
        with _simulate_remote():
            resp = _chat(client, sid, "ciao",
                         headers={"Authorization": f"Bearer {session_token}"})
        # Must NOT be gated — auth_required must be absent or False
        assert resp["data"].get("auth_required") is not True, \
            f"Authenticated request was incorrectly gated: {resp['data']}"


def test_invalid_bearer_token_gets_gated():
    """An invalid Bearer token counts as unauthenticated — gate fires for remote."""
    client = _client()
    sid = _make_session(client)
    with _simulate_remote():
        resp = _chat(client, sid, "ciao",
                     headers={"Authorization": "Bearer FAKE_TOKEN_INVALID_1278"})
    data = resp["data"]
    assert data.get("auth_required") is True, \
        f"Invalid token should be gated, got: {data}"


def test_gate_auth_reason_session_invalid_on_bad_token():
    """Invalid session → auth_reason is session_invalid or unauthenticated."""
    client = _client()
    sid = _make_session(client)
    with _simulate_remote():
        resp = _chat(client, sid, "ciao",
                     headers={"Authorization": "Bearer FAKE_TOKEN_INVALID_1278b"})
    data = resp["data"]
    reason = data.get("auth_reason", "")
    assert reason in ("session_invalid", "unauthenticated"), \
        f"Unexpected auth_reason: {reason}"


# ── Backend: stream endpoint auth-first gate (simulated remote) ───────────────

def _stream_chat(client, session_id, message, headers=None) -> dict:
    h = headers or {}
    r = client.post(
        "/api/chat/stream",
        json={"message": message, "session_id": session_id, "interlocutor_id": "unknown"},
        headers=h,
    )
    return {"status": r.status_code, "text": r.text}


def test_stream_unauthenticated_remote_gets_auth_gate():
    """Stream endpoint: unauthenticated remote request returns auth_required SSE event."""
    client = _client()
    sid = _make_session(client)
    with _simulate_remote():
        resp = _stream_chat(client, sid, "ciao", headers={})
    assert resp["status"] == 200
    assert "auth_required" in resp["text"], \
        f"Expected auth_required in SSE stream, got: {resp['text'][:300]}"


def test_stream_unauthenticated_auth_actions_in_sse():
    """Stream gate SSE contains login and enroll actions."""
    client = _client()
    sid = _make_session(client)
    with _simulate_remote():
        resp = _stream_chat(client, sid, "ciao", headers={})
    text = resp["text"]
    assert "login" in text and "enroll" in text, \
        f"auth_actions missing from stream gate SSE: {text[:300]}"


def test_stream_invalid_token_gets_gated():
    """Stream endpoint: invalid Bearer token → auth gate fires for remote."""
    client = _client()
    sid = _make_session(client)
    with _simulate_remote():
        resp = _stream_chat(client, sid, "ciao",
                            headers={"Authorization": "Bearer FAKE_TOKEN_STREAM_1278"})
    assert "auth_required" in resp["text"], \
        f"Expected auth_required in stream for invalid token, got: {resp['text'][:300]}"


# ── Frontend static: auth.js intent detection ────────────────────────────────

def _auth_js() -> str:
    return _AUTH_JS.read_text(encoding="utf-8")


def test_auth_js_has_is_enrollment_intent():
    assert "function isEnrollmentIntent" in _auth_js()


def test_auth_js_has_is_login_intent():
    assert "function isLoginIntent" in _auth_js()


def test_auth_js_has_is_auth_intent():
    assert "function isAuthIntent" in _auth_js()


def test_auth_js_has_handle_unauthenticated_message():
    assert "function handleUnauthenticatedMessage" in _auth_js()


def test_is_enrollment_intent_keywords():
    """Keyword list must cover Italian registration verbs."""
    content = _auth_js()
    for kw in ["registrarmi", "censirmi", "registrami", "register", "enroll"]:
        assert kw in content, f"Enrollment keyword '{kw}' missing from auth.js"


def test_is_login_intent_keywords():
    """Keyword list must cover Italian login verbs."""
    content = _auth_js()
    for kw in ["login", "accedi", "sign in"]:
        assert kw in content, f"Login keyword '{kw}' missing from auth.js"


def test_handle_unauthenticated_calls_show_enroll_for_enroll_intent():
    """handleUnauthenticatedMessage must call authShowEnroll for enrollment intent."""
    content = _auth_js()
    fn_start = content.find("function handleUnauthenticatedMessage")
    fn_body = content[fn_start:fn_start + 800]
    assert "authShowEnroll" in fn_body, \
        "handleUnauthenticatedMessage must call authShowEnroll for enrollment intent"


def test_handle_unauthenticated_calls_show_login_for_login_intent():
    """handleUnauthenticatedMessage must call authShowLogin for login intent."""
    content = _auth_js()
    fn_start = content.find("function handleUnauthenticatedMessage")
    fn_body = content[fn_start:fn_start + 800]
    assert "authShowLogin" in fn_body, \
        "handleUnauthenticatedMessage must call authShowLogin for login intent"


def test_auth_clear_ui_shows_non_autenticato():
    """_authClearUI must set topbar to 'non autenticato' (not blank or dash)."""
    content = _auth_js()
    fn_start = content.find("function _authClearUI")
    fn_body = content[fn_start:fn_start + 700]
    assert "non autenticato" in fn_body, \
        "_authClearUI must set topbar name to 'non autenticato'"


# ── Frontend static: app.js auth gate ────────────────────────────────────────

def _app_js() -> str:
    return _APP_JS.read_text(encoding="utf-8")


def test_app_js_has_get_session_token_check():
    """app.js must check getSessionToken() before sending chat."""
    content = _app_js()
    assert "getSessionToken" in content, "getSessionToken not referenced in app.js"


def test_app_js_has_handle_unauthenticated_message_call():
    """app.js must call handleUnauthenticatedMessage for unauthenticated sends."""
    content = _app_js()
    assert "handleUnauthenticatedMessage" in content, \
        "handleUnauthenticatedMessage not called in app.js"


def test_app_js_gate_returns_early():
    """app.js auth gate must return early (not proceed to fetch)."""
    content = _app_js()
    gate_start = content.find("Auth-first gate")
    assert gate_start >= 0, "Auth-first gate comment not found in app.js"
    gate_region = content[gate_start:gate_start + 600]
    assert "return" in gate_region, "Auth-first gate in app.js must return early"


def test_app_js_connesso_replaced():
    """app.js must not use 'connesso' — should say 'non autenticato'."""
    content = _app_js()
    assert '"connesso"' not in content and "'connesso'" not in content, \
        "'connesso' still present in app.js — should be 'non autenticato'"


def test_app_js_non_autenticato_present():
    """app.js must use 'non autenticato' as unauthenticated display text."""
    content = _app_js()
    assert "non autenticato" in content, \
        "'non autenticato' not found in app.js"


# ── Security invariants ───────────────────────────────────────────────────────

def test_gate_response_no_password_in_body():
    """Gate response must never contain a password field."""
    client = _client()
    sid = _make_session(client)
    with _simulate_remote():
        resp = _chat(client, sid, "ciao", headers={})
    body = json.dumps(resp["data"])
    assert "password" not in body.lower(), \
        f"Password found in gate response body: {body}"


def test_gate_response_no_session_token_in_body():
    """Gate response must never leak a session token."""
    client = _client()
    sid = _make_session(client)
    with _simulate_remote():
        resp = _chat(client, sid, "ciao", headers={})
    body = json.dumps(resp["data"])
    assert "session_token" not in body, \
        f"session_token field found in gate response: {body}"
