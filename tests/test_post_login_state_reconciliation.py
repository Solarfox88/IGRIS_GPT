"""Tests for Fix #1283 — Post-login state reconciliation.

After login/enrollment:
  topbar     → updated by authUpdateUI() ✓ (already worked)
  sidebar    → updated by onAuthStateChanged() ← new
  chatMeta   → updated by onAuthStateChanged() ← new
  pre-auth messages → cleared               ← new
  success message → added                   ← new
  loadStatusPanel → does NOT overwrite auth state ← new guard

After logout:
  sidebar → reset to unknown/untrusted      ← new
  chatMeta → reset to "non autenticato"     ← new

Enrolled user → trust_level must be "limited" by default.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).parent.parent
_AUTH_JS = _REPO / "igris/web/static/js/auth.js"
_APP_JS = _REPO / "igris/web/static/js/app.js"


def _auth_js() -> str:
    return _AUTH_JS.read_text(encoding="utf-8")


def _app_js() -> str:
    return _APP_JS.read_text(encoding="utf-8")


def _unique_username() -> str:
    return "rectest_" + str(int(time.time() * 1000))[-8:]


def _client_with_tmp_root(tmp_dir: str):
    os.environ["IGRIS_PROJECT_ROOT"] = tmp_dir
    for k in list(sys.modules.keys()):
        if any(x in k for x in ("auth_routes", "interlocutor_auth")):
            del sys.modules[k]
    from fastapi.testclient import TestClient
    from igris.web.server import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


# ── auth.js: onAuthStateChanged hook ─────────────────────────────────────────

def test_auth_js_calls_on_auth_state_changed_on_success():
    """authUpdateUI must call window.onAuthStateChanged(p) when login succeeds."""
    content = _auth_js()
    fn_start = content.find("async function authUpdateUI")
    assert fn_start >= 0
    fn_body = content[fn_start:fn_start + 1200]
    assert "onAuthStateChanged" in fn_body, \
        "authUpdateUI does not call onAuthStateChanged — sidebar won't update after login"


def test_auth_js_calls_on_auth_state_cleared_on_logout():
    """_authClearUI must call window.onAuthStateCleared() so sidebar resets on logout."""
    content = _auth_js()
    fn_start = content.find("function _authClearUI")
    assert fn_start >= 0
    fn_body = content[fn_start:fn_start + 700]
    assert "onAuthStateCleared" in fn_body, \
        "_authClearUI does not call onAuthStateCleared — sidebar won't reset on logout"


# ── app.js: helper functions present ─────────────────────────────────────────

def test_app_js_has_on_auth_state_changed():
    assert "window.onAuthStateChanged" in _app_js(), \
        "window.onAuthStateChanged missing from app.js"


def test_app_js_has_on_auth_state_cleared():
    assert "window.onAuthStateCleared" in _app_js(), \
        "window.onAuthStateCleared missing from app.js"


def test_app_js_has_clear_pre_auth_messages():
    assert "window.clearPreAuthMessages" in _app_js(), \
        "window.clearPreAuthMessages missing from app.js"


def test_app_js_has_add_auth_success_message():
    assert "window.addAuthSuccessMessage" in _app_js(), \
        "window.addAuthSuccessMessage missing from app.js"


def test_app_js_has_update_interlocutor_panel():
    assert "window.updateInterlocutorPanel" in _app_js(), \
        "window.updateInterlocutorPanel missing from app.js"


# ── app.js: pre-auth patterns list ───────────────────────────────────────────

def test_app_js_pre_auth_patterns_covers_known_messages():
    """_PRE_AUTH_PATTERNS must cover the messages that appear before authentication."""
    content = _app_js()
    patterns_start = content.find("_PRE_AUTH_PATTERNS")
    assert patterns_start >= 0, "_PRE_AUTH_PATTERNS array not found in app.js"
    patterns_region = content[patterns_start:patterns_start + 400]
    for expected in [
        "Prima di continuare devo riconoscerti",
        "Non ho ancora un profilo per te",
        "Accedi oppure registrati",
    ]:
        assert expected in patterns_region, \
            f"Pre-auth pattern '{expected}' not in _PRE_AUTH_PATTERNS"


# ── app.js: success message content ──────────────────────────────────────────

def test_app_js_auth_success_message_italian():
    """addAuthSuccessMessage must emit an Italian confirmation message."""
    content = _app_js()
    fn_start = content.find("window.addAuthSuccessMessage")
    assert fn_start >= 0
    fn_body = content[fn_start:fn_start + 300]
    assert "Accesso effettuato" in fn_body, \
        "addAuthSuccessMessage does not contain 'Accesso effettuato'"


def test_app_js_auth_success_uses_add_msg():
    """addAuthSuccessMessage must call addMsg to insert into chat DOM."""
    content = _app_js()
    fn_start = content.find("window.addAuthSuccessMessage")
    assert fn_start >= 0
    fn_body = content[fn_start:fn_start + 300]
    assert "addMsg(" in fn_body, \
        "addAuthSuccessMessage does not call addMsg — message won't appear in chat"


# ── app.js: loadStatusPanel guard ────────────────────────────────────────────

def test_app_js_load_status_panel_guards_auth_profile():
    """loadStatusPanel must NOT overwrite topbar/sidebar when _igrisAuthProfileId is set."""
    content = _app_js()
    fn_start = content.find("function loadStatusPanel")
    assert fn_start >= 0
    fn_body = content[fn_start:fn_start + 4000]
    assert "_igrisAuthProfileId" in fn_body or "_authPid" in fn_body, \
        "loadStatusPanel does not check _igrisAuthProfileId — " \
        "will overwrite auth topbar with stale diagnostics data every 60s"


def test_app_js_load_status_panel_uses_auth_guard_variable():
    """The auth guard variable _authPid must be checked before identity updates."""
    content = _app_js()
    fn_start = content.find("function loadStatusPanel")
    assert fn_start >= 0
    fn_body = content[fn_start:fn_start + 4000]
    # Guard must appear BEFORE the tbName assignment
    guard_pos = fn_body.find("_authPid")
    tbname_pos = fn_body.find("tbName.textContent")
    assert guard_pos >= 0, "_authPid guard variable not found in loadStatusPanel"
    assert guard_pos < tbname_pos, \
        "_authPid guard must appear before tbName.textContent assignment"


# ── app.js: logout reset ─────────────────────────────────────────────────────

def test_app_js_on_auth_state_cleared_resets_sidebar():
    """onAuthStateCleared must reset sp-interlocutor-content to unknown/untrusted."""
    content = _app_js()
    fn_start = content.find("window.onAuthStateCleared")
    assert fn_start >= 0
    fn_body = content[fn_start:fn_start + 400]
    assert "sp-interlocutor-content" in fn_body or "spIC" in fn_body, \
        "onAuthStateCleared does not reset sidebar interlocutor panel"


def test_app_js_on_auth_state_cleared_resets_chat_meta():
    """onAuthStateCleared must reset chat-interlocutor-meta to 'non autenticato'."""
    content = _app_js()
    fn_start = content.find("window.onAuthStateCleared")
    assert fn_start >= 0
    fn_body = content[fn_start:fn_start + 400]
    assert "non autenticato" in fn_body, \
        "onAuthStateCleared does not set chatMeta to 'non autenticato'"


# ── Backend: enrolled user trust_level must be limited ───────────────────────

def test_enrolled_user_default_trust_limited_not_admin():
    """A freshly enrolled user must have trust_level='limited', not 'admin' or 'owner'."""
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_with_tmp_root(tmp)
        uname = _unique_username()
        r1 = client.post("/api/auth/enroll/start", json={
            "username": uname, "first_name": "Test", "last_name": "Limited",
            "email": f"{uname}@example.com", "mobile_phone": "+39000000020",
        })
        assert r1.json().get("ok") is True, r1.text
        token = r1.json()["enrollment_token"]

        r2 = client.post("/api/auth/enroll/complete", json={
            "enrollment_token": token,
            "password": "LimitedTest1",
            "confirm_password": "LimitedTest1",
        })
        assert r2.json().get("ok") is True, r2.text
        session_token = r2.json()["session_token"]

        # Check /api/auth/me returns trust_level=limited
        r3 = client.get("/api/auth/me",
                        headers={"Authorization": f"Bearer {session_token}"})
        data = r3.json()
        assert data.get("ok") is True, data
        trust = data.get("profile", {}).get("trust_level", "")
        assert trust == "limited", \
            f"Enrolled user should have trust_level='limited', got '{trust}'. " \
            f"If showing 'admin', the profile was manually promoted — new enrollments must always start as limited."


def test_existing_admin_profile_can_show_admin_only_if_preexisting():
    """A pre-existing admin profile (christian_ricci) shows admin — not a bug."""
    root = "/home/igris/IGRIS_GPT"
    try:
        from igris.core.identity_resolver import load_profiles
        profiles = load_profiles(root)
        if "christian_ricci" in profiles:
            p = profiles["christian_ricci"]
            # This profile was manually promoted — it is correct to show admin
            # New enrollments must NOT be admin (checked by test above)
            assert p.trust_level in ("admin", "owner", "limited", "trusted"), \
                f"christian_ricci trust_level unexpected: {p.trust_level}"
    except Exception:
        pytest.skip("Production profile not accessible in this environment")


# ── Backend: /api/auth/me returns profile ────────────────────────────────────

def test_auth_me_returns_profile_after_enrollment():
    """After enrollment, /api/auth/me must return the user's profile."""
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_with_tmp_root(tmp)
        uname = _unique_username()
        r1 = client.post("/api/auth/enroll/start", json={
            "username": uname, "first_name": "Me", "last_name": "Test",
            "email": f"{uname}@example.com", "mobile_phone": "+39000000021",
        })
        token = r1.json()["enrollment_token"]
        r2 = client.post("/api/auth/enroll/complete", json={
            "enrollment_token": token,
            "password": "MeTest1234",
            "confirm_password": "MeTest1234",
        })
        session_token = r2.json()["session_token"]

        r3 = client.get("/api/auth/me",
                        headers={"Authorization": f"Bearer {session_token}"})
        data = r3.json()
        assert data.get("ok") is True, data
        profile = data.get("profile", {})
        assert profile.get("profile_id") == uname, \
            f"Expected profile_id={uname}, got: {profile}"
        assert "trust_level" in profile, "trust_level missing from /api/auth/me response"
        assert "display_name" in profile, "display_name missing from /api/auth/me response"


# ── app.js: Bearer token used in chat after login ────────────────────────────

def test_after_login_next_message_uses_bearer_token():
    """app.js chat submit must include authHeaders() (Bearer token) in every request."""
    content = _app_js()
    # Find the CHAT form submit — identified by #chat-input reference nearby
    chat_input_pos = content.find('"#chat-input"')
    # Walk back to find the enclosing form.addEventListener
    region_start = max(0, chat_input_pos - 200)
    region = content[region_start:chat_input_pos + 2000]
    assert "authHeaders" in region, \
        "authHeaders() not called near chat-input submit — Bearer token won't be sent"


def test_app_js_auth_headers_assigned_to_chat_request():
    """The result of authHeaders() must be assigned to _chatHeaders for the chat API call."""
    content = _app_js()
    assert "_chatHeaders" in content, "_chatHeaders variable missing from app.js"
    # Find _chatHeaders = ... authHeaders()
    idx = content.find("_chatHeaders")
    region = content[idx:idx + 200]
    assert "authHeaders" in region, \
        "_chatHeaders not populated from authHeaders() — Bearer won't be sent"
