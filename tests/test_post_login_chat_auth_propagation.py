"""Fix #1286 — Post-login chat auth propagation tests.

Root cause: routes_01.py used CONFIG.project_root (PROJECT_ROOT=/home/igris/IGRIS_TEST)
as fallback for the auth session lookup, while auth_routes.py uses "." (CWD).
Sessions written to /home/igris/IGRIS_GPT/.igris/auth/sessions.json were looked up
in /home/igris/IGRIS_TEST/.igris/auth/ → not found → session_authenticated=False
→ gate fires → "Prima di continuare devo riconoscerti..." even after valid login.

Fix: routes_01.py now uses os.environ.get("IGRIS_PROJECT_ROOT") or "." (same as auth_routes).
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO = Path(__file__).parent.parent
_ROUTES_01 = _REPO / "igris/web/routers/routes_01.py"
_AUTH_ROUTES = _REPO / "igris/api/routes/auth_routes.py"
_APP_JS = _REPO / "igris/web/static/js/app.js"

_PREFLIGHT_MODULE = "igris.core.chat_interlocutor_preflight"


@contextmanager
def _gate_enabled_remote(tmp_dir: str):
    """Enable auth gate and simulate remote request in isolated tmp dir."""
    old = os.environ.get("IGRIS_REQUIRE_AUTH", "")
    old_root = os.environ.get("IGRIS_PROJECT_ROOT", "")
    os.environ["IGRIS_REQUIRE_AUTH"] = "true"
    os.environ["IGRIS_PROJECT_ROOT"] = tmp_dir
    try:
        with patch(f"{_PREFLIGHT_MODULE}.is_trusted_local_request", return_value=False):
            yield
    finally:
        if old:
            os.environ["IGRIS_REQUIRE_AUTH"] = old
        else:
            os.environ.pop("IGRIS_REQUIRE_AUTH", None)
        if old_root:
            os.environ["IGRIS_PROJECT_ROOT"] = old_root
        else:
            os.environ.pop("IGRIS_PROJECT_ROOT", None)


def _client_isolated(tmp_dir: str):
    os.environ["IGRIS_PROJECT_ROOT"] = tmp_dir
    for k in list(sys.modules.keys()):
        if any(x in k for x in ("auth_routes", "interlocutor_auth", "routes_01")):
            del sys.modules[k]
    from fastapi.testclient import TestClient
    from igris.web.server import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


def _enroll_and_login(client, tmp_dir: str) -> tuple[str, str]:
    """Enroll a fresh user and return (session_token, username)."""
    uname = "postlogin_" + str(int(time.time() * 1000))[-8:]
    r1 = client.post("/api/auth/enroll/start", json={
        "username": uname, "first_name": "P", "last_name": "L",
        "email": f"{uname}@test.com", "mobile_phone": "+39000000101",
    })
    assert r1.json().get("ok") is True, r1.text
    tok = r1.json()["enrollment_token"]
    r2 = client.post("/api/auth/enroll/complete", json={
        "enrollment_token": tok, "password": "PostLogin1!", "confirm_password": "PostLogin1!",
    })
    assert r2.json().get("ok") is True, r2.text
    return r2.json()["session_token"], uname


def _make_session(client) -> str:
    r = client.post("/api/sessions")
    assert r.status_code == 200
    return r.json()["id"]


# ── Backend: valid Bearer allows chat ─────────────────────────────────────────

def test_login_then_post_message_with_bearer_does_not_auth_required():
    """After enrollment, sending a message with Bearer token must NOT return auth_required."""
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        session_token, uname = _enroll_and_login(client, tmp)
        sid = _make_session(client)
        with _gate_enabled_remote(tmp):
            r = client.post(f"/api/sessions/{sid}/messages",
                            json={"message": "Ciao Igris", "interlocutor_id": uname},
                            headers={"Authorization": f"Bearer {session_token}"})
        data = r.json()
        assert data.get("auth_required") is not True, (
            f"Valid session Bearer should not trigger auth_required, got: {data}. "
            "Root cause: project_root mismatch between auth_routes and routes_01."
        )


def test_login_then_stream_with_bearer_does_not_auth_required():
    """After enrollment, streaming with Bearer token must NOT contain auth_required."""
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        session_token, uname = _enroll_and_login(client, tmp)
        sid = _make_session(client)
        with _gate_enabled_remote(tmp):
            r = client.post("/api/chat/stream",
                            json={"message": "Ciao", "session_id": sid, "interlocutor_id": uname},
                            headers={"Authorization": f"Bearer {session_token}"})
        assert '"auth_required": true' not in r.text.lower() or "true" not in r.text, (
            f"Valid Bearer should not trigger stream auth gate, got: {r.text[:300]}"
        )


def test_post_message_without_bearer_auth_required():
    """Without token, chat must return auth_required."""
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        sid = _make_session(client)
        with _gate_enabled_remote(tmp):
            r = client.post(f"/api/sessions/{sid}/messages",
                            json={"message": "Ciao", "interlocutor_id": "unknown"})
        assert r.json().get("auth_required") is True


def test_post_message_invalid_bearer_auth_required():
    """Invalid Bearer token must return auth_required."""
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        sid = _make_session(client)
        with _gate_enabled_remote(tmp):
            r = client.post(f"/api/sessions/{sid}/messages",
                            json={"message": "Ciao", "interlocutor_id": "unknown"},
                            headers={"Authorization": "Bearer FAKE_TOKEN_INVALID_1286"})
        assert r.json().get("auth_required") is True


def test_post_message_valid_bearer_resolves_profile_id():
    """Valid Bearer token: response must NOT be auth_required and must NOT be empty."""
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        session_token, uname = _enroll_and_login(client, tmp)
        sid = _make_session(client)
        with _gate_enabled_remote(tmp):
            r = client.post(f"/api/sessions/{sid}/messages",
                            json={"message": "Ciao", "interlocutor_id": uname},
                            headers={"Authorization": f"Bearer {session_token}"})
        data = r.json()
        assert data.get("auth_required") is not True
        assert "response" in data, f"Expected chat response, got: {data}"


# ── Static: frontend sends auth headers ───────────────────────────────────────

def _app_js() -> str:
    return _APP_JS.read_text(encoding="utf-8")


def test_app_js_chat_fetch_uses_auth_headers():
    """The chat API call must pass authHeaders() as extraHeaders to api()."""
    content = _app_js()
    # Find _chatHeaders assignment near the messages fetch
    idx = content.find("_chatHeaders")
    assert idx >= 0, "_chatHeaders variable not found in app.js"
    region = content[idx:idx + 300]
    assert "authHeaders" in region, \
        "_chatHeaders not populated from authHeaders() — Bearer won't be sent to /api/sessions/.../messages"


def test_app_js_api_merges_extra_headers():
    """api() must merge extraHeaders into the fetch options (not ignore them)."""
    content = _app_js()
    fn_start = content.find("async function api(")
    assert fn_start >= 0
    fn_body = content[fn_start:fn_start + 300]
    assert "extraHeaders" in fn_body, "api() does not accept extraHeaders parameter"
    assert "Object.assign" in fn_body or "...extraHeaders" in fn_body, \
        "api() does not merge extraHeaders — Authorization header will be dropped"


def test_app_js_api_does_not_override_authorization():
    """api() must not hard-code Authorization, overriding the extraHeaders value."""
    content = _app_js()
    fn_start = content.find("async function api(")
    fn_body = content[fn_start:fn_start + 300]
    # Must not set Authorization manually inside api()
    assert "Authorization" not in fn_body, \
        "api() sets Authorization header directly — will override Bearer from authHeaders()"


def test_send_button_path_uses_auth_headers():
    """Chat submit uses _chatHeaders from authHeaders() — not a hardcoded empty object."""
    content = _app_js()
    idx = content.find('"#chat-input"')
    region = content[max(0, idx - 200):idx + 2000]
    assert "_chatHeaders" in region, \
        "_chatHeaders not used in chat submit region — Bearer token not sent"
    assert "authHeaders" in region, \
        "authHeaders() not called in chat submit region"


def test_enter_key_path_uses_auth_headers():
    """The Enter-key send path must also use authHeaders (same submit handler as chat)."""
    content = _app_js()
    # The CHAT submit handler is identified by its proximity to #chat-input
    chat_input_pos = content.find('"#chat-input"')
    assert chat_input_pos >= 0, '"#chat-input" not found in app.js'
    # Walk back to find the enclosing form.addEventListener("submit"
    region_start = max(0, chat_input_pos - 300)
    submit_idx = content.rfind('form.addEventListener("submit"', region_start, chat_input_pos)
    if submit_idx < 0:
        submit_idx = content.find('form.addEventListener("submit"', chat_input_pos)
    assert submit_idx >= 0, "Chat form submit listener not found near #chat-input"
    region = content[submit_idx:submit_idx + 3000]
    assert "_chatHeaders" in region, \
        "_chatHeaders not in chat form submit handler — Enter key path won't send Bearer"


def test_stream_path_uses_auth_headers():
    """Any stream fetch must include auth headers."""
    content = _app_js()
    # Look for /api/chat/stream usage
    stream_idx = content.find("/api/chat/stream")
    if stream_idx < 0:
        pytest.skip("No stream path in app.js")
    region = content[max(0, stream_idx - 500):stream_idx + 500]
    has_auth = "authHeaders" in region or "_chatHeaders" in region or "getSessionToken" in region
    assert has_auth, \
        "Stream path near /api/chat/stream does not include authHeaders — Bearer not sent"


# ── Static: routes_01.py project_root consistency ────────────────────────────

def test_routes_01_does_not_fall_back_to_config_project_root():
    """routes_01.py must NOT fall back to CONFIG.project_root for auth session lookup.

    CONFIG.project_root reads PROJECT_ROOT env var (workspace dir, e.g. /home/igris/IGRIS_TEST).
    auth_routes.py reads IGRIS_PROJECT_ROOT (auth store, e.g. /home/igris/IGRIS_GPT).
    Using CONFIG.project_root as fallback creates a mismatch: sessions are stored in
    IGRIS_GPT but looked up in IGRIS_TEST → session_authenticated=False → auth_required.
    """
    content = _ROUTES_01.read_text(encoding="utf-8")
    # Find the project root assignment for preflight
    pf_root_idx = content.find("_pf_project_root")
    assert pf_root_idx >= 0
    region = content[pf_root_idx:pf_root_idx + 200]
    assert "CONFIG.project_root" not in region, (
        "routes_01.py falls back to CONFIG.project_root for auth session lookup. "
        "This causes project_root mismatch: CONFIG.project_root reads PROJECT_ROOT "
        "(workspace = /home/igris/IGRIS_TEST) but auth sessions are in IGRIS_PROJECT_ROOT "
        "(= /home/igris/IGRIS_GPT). Sessions not found → auth_required after valid login."
    )


def test_routes_01_stream_does_not_fall_back_to_config_project_root():
    """Stream endpoint in routes_01.py must also not fall back to CONFIG.project_root."""
    content = _ROUTES_01.read_text(encoding="utf-8")
    pf_root_idx = content.find("_pf_project_root_s")
    assert pf_root_idx >= 0
    region = content[pf_root_idx:pf_root_idx + 200]
    assert "CONFIG.project_root" not in region, (
        "Stream endpoint in routes_01.py falls back to CONFIG.project_root. "
        "Same mismatch as messages endpoint — sessions not found → auth_required."
    )


def test_auth_routes_and_routes_01_use_same_env_var():
    """Both auth_routes.py and routes_01.py must read IGRIS_PROJECT_ROOT for consistency."""
    auth_content = _AUTH_ROUTES.read_text(encoding="utf-8")
    routes_content = _ROUTES_01.read_text(encoding="utf-8")
    assert "IGRIS_PROJECT_ROOT" in auth_content, \
        "auth_routes.py does not use IGRIS_PROJECT_ROOT — inconsistency with routes_01"
    assert "IGRIS_PROJECT_ROOT" in routes_content, \
        "routes_01.py does not use IGRIS_PROJECT_ROOT — inconsistency with auth_routes"
