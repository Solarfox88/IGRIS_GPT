"""Tests for #1272 PR5 — Auth UI static checks.

Since we don't run a browser, these tests verify the static content of
auth.js, index.html and app.js for the security properties that must hold:
- password inputs are type=password
- no console.log of token/password
- sessionStorage (not localStorage) used for token
- Authorization Bearer used (not query string)
- no forbidden fields in enrollment form
- chat send includes authHeaders
- auth.js file exists and has required functions
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO = Path(__file__).parent.parent
_AUTH_JS = _REPO / "igris/web/static/js/auth.js"
_APP_JS = _REPO / "igris/web/static/js/app.js"
_INDEX_HTML = _REPO / "igris/web/templates/index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── auth.js existence and basic structure ─────────────────────────────────────

def test_auth_js_exists():
    assert _AUTH_JS.exists(), "auth.js not found"


def test_auth_js_has_get_session_token():
    content = _read(_AUTH_JS)
    assert "function getSessionToken" in content


def test_auth_js_has_set_session_token():
    content = _read(_AUTH_JS)
    assert "function setSessionToken" in content


def test_auth_js_has_clear_session_token():
    content = _read(_AUTH_JS)
    assert "function clearSessionToken" in content


def test_auth_js_has_auth_headers():
    content = _read(_AUTH_JS)
    assert "function authHeaders" in content


def test_auth_js_has_auth_login():
    content = _read(_AUTH_JS)
    assert "async function authLogin" in content


def test_auth_js_has_auth_logout():
    content = _read(_AUTH_JS)
    assert "async function authLogout" in content


def test_auth_js_has_auth_enroll_start():
    content = _read(_AUTH_JS)
    assert "async function authEnrollStart" in content


def test_auth_js_has_auth_enroll_complete():
    content = _read(_AUTH_JS)
    assert "async function authEnrollComplete" in content


def test_auth_js_has_auth_me():
    content = _read(_AUTH_JS)
    assert "async function authMe" in content


# ── Token storage: sessionStorage, not localStorage ──────────────────────────

def test_session_storage_used_not_local_storage():
    content = _read(_AUTH_JS)
    assert "sessionStorage" in content, "sessionStorage not used in auth.js"


def test_local_storage_not_used_for_token():
    content = _read(_AUTH_JS)
    # localStorage must not be CALLED in auth.js — comments are ok
    # Strip comment lines and check
    non_comment_lines = [
        line for line in content.splitlines()
        if not line.strip().startswith("//") and not line.strip().startswith("*")
    ]
    code_only = "\n".join(non_comment_lines)
    assert "localStorage" not in code_only, \
        "localStorage should not be used in auth.js (only sessionStorage allowed)"


# ── Authorization Bearer, not query string ────────────────────────────────────

def test_auth_headers_uses_bearer_not_query_string():
    content = _read(_AUTH_JS)
    assert '"Authorization"' in content or "'Authorization'" in content, \
        "Authorization header missing in auth.js"
    assert "Bearer" in content, "Bearer token not used in auth.js"
    # Token must not be added to query string
    assert "?token=" not in content
    assert "&token=" not in content
    assert "?session_token=" not in content


# ── No console.log of token or password ──────────────────────────────────────

def test_no_console_log_token_or_password():
    content = _read(_AUTH_JS)
    # Crude but effective: no console.log that could expose token or password
    lower = content.lower()
    bad_patterns = [
        "console.log(session_token",
        "console.log(token",
        "console.log(password",
        "console.log(pw",
    ]
    for pat in bad_patterns:
        assert pat not in lower, f"Potential credential leak in auth.js: {pat}"


# ── Login form: type=password ─────────────────────────────────────────────────

def test_login_form_uses_input_type_password():
    content = _read(_INDEX_HTML)
    # Should have at least one type="password" for login
    assert 'type="password"' in content or "type='password'" in content, \
        "No password input found in index.html"
    # Specifically the login password field
    assert "auth-login-password" in content


def test_login_password_input_has_correct_type():
    content = _read(_INDEX_HTML)
    # Find the input (not label) line containing auth-login-password
    for line in content.splitlines():
        if "auth-login-password" in line and "<input" in line:
            assert 'type="password"' in line or "type='password'" in line, \
                f"Login password input does not have type=password: {line}"
            return
    # If we reach here with no assertion, verify there's a password input nearby
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if "auth-login-password" in line:
            context = "\n".join(lines[max(0,i-1):i+3])
            assert 'type="password"' in context or "type='password'" in context, \
                f"No type=password near auth-login-password: {context}"
            return


# ── Enrollment form: type=password ────────────────────────────────────────────

def test_enroll_form_uses_input_type_password():
    content = _read(_INDEX_HTML)
    assert "auth-enroll-password" in content
    assert "auth-enroll-confirm" in content


def test_enroll_password_inputs_have_correct_type():
    content = _read(_INDEX_HTML)
    pw_count = 0
    for line in content.splitlines():
        if "auth-enroll-password" in line or "auth-enroll-confirm" in line:
            if "input" in line:
                assert 'type="password"' in line or "type='password'" in line, \
                    f"Enrollment password input missing type=password: {line}"
                pw_count += 1
    assert pw_count >= 2, f"Expected >=2 enrollment password inputs, found {pw_count}"


def test_enroll_password_has_autocomplete_new_password():
    content = _read(_INDEX_HTML)
    assert "autocomplete=\"new-password\"" in content or "autocomplete='new-password'" in content, \
        "autocomplete=new-password missing on enrollment password fields"


# ── No forbidden fields in enrollment form ────────────────────────────────────

def test_no_forbidden_fields_in_enroll_form():
    content = _read(_INDEX_HTML)
    # The enrollment modal must not have fields for trust_level, role, authorized_scopes
    forbidden = ["trust_level", "authorized_scopes", "role"]
    for f in forbidden:
        # Check for input with name=trust_level etc — exact match for form fields
        assert f'name="{f}"' not in content and f"name='{f}'" not in content, \
            f"Forbidden enrollment field '{f}' found in index.html form"


# ── Chat send uses authHeaders ────────────────────────────────────────────────

def test_chat_send_uses_auth_headers():
    content = _read(_APP_JS)
    assert "authHeaders" in content, "authHeaders not referenced in app.js chat send"


def test_chat_api_function_accepts_extra_headers():
    content = _read(_APP_JS)
    # The api() function should accept extraHeaders or similar
    assert "extraHeaders" in content or "extraHeaders" in content.replace(" ", ""), \
        "api() function does not accept extra headers"


def test_chat_no_password_field_in_payload():
    content = _read(_APP_JS)
    # The chat message payload must not include a password field
    # Find the sessions/messages API call
    found_chat_call = False
    for i, line in enumerate(content.splitlines()):
        if "sessions/" in line and "messages" in line and "POST" in line:
            found_chat_call = True
            # Check surrounding 5 lines for password key
            context_lines = content.splitlines()[max(0, i-2):i+5]
            context = "\n".join(context_lines)
            assert "password" not in context.lower(), \
                f"Password found in chat message payload context: {context}"
    # Don't fail if the pattern isn't found as it could be structured differently
    # (this is a best-effort check)


# ── index.html has auth.js loaded ────────────────────────────────────────────

def test_index_html_loads_auth_js():
    content = _read(_INDEX_HTML)
    assert "auth.js" in content, "auth.js not loaded in index.html"


def test_auth_js_loaded_after_app_js():
    content = _read(_INDEX_HTML)
    # Find script src= tags specifically (not comments)
    import re
    script_srcs = [(m.start(), m.group(1)) for m in re.finditer(r'<script[^>]+src=["\']([^"\']+)["\']', content)]
    src_names = [src for _, src in script_srcs]
    assert any("app.js" in s for s in src_names), "app.js script tag not found in index.html"
    assert any("auth.js" in s for s in src_names), "auth.js script tag not found in index.html"
    app_pos = next(pos for pos, src in script_srcs if "app.js" in src)
    auth_pos = next(pos for pos, src in script_srcs if "auth.js" in src)
    assert auth_pos > app_pos, "auth.js must be loaded after app.js (DOM must exist first)"


# ── Topbar auth buttons ───────────────────────────────────────────────────────

def test_index_html_has_login_button():
    content = _read(_INDEX_HTML)
    assert "tb-auth-btn" in content, "Login button (tb-auth-btn) not found in index.html"
    # Function must be in auth.js (no inline onclick)
    auth_js = _read(_AUTH_JS)
    assert "authShowLogin" in auth_js


def test_index_html_has_logout_button():
    content = _read(_INDEX_HTML)
    assert "tb-logout-btn" in content, "Logout button (tb-logout-btn) not found in index.html"
    auth_js = _read(_AUTH_JS)
    assert "authDoLogout" in auth_js


def test_index_html_has_enroll_button():
    content = _read(_INDEX_HTML)
    assert "tb-enroll-btn" in content, "Enroll button (tb-enroll-btn) not found in index.html"
    auth_js = _read(_AUTH_JS)
    assert "authShowEnroll" in auth_js


def test_no_inline_onclick_in_auth_modals():
    """auth.js wires listeners; index.html must have zero onclick= attributes."""
    content = _read(_INDEX_HTML)
    assert "onclick=" not in content, \
        "onclick= found in index.html — use event listeners in auth.js instead"


# ── Gauntlet check integration ────────────────────────────────────────────────

def test_gauntlet_includes_auth_enrollment_login_flow():
    gauntlet_path = _REPO / "igris/core/jarvis_core_gauntlet.py"
    content = gauntlet_path.read_text(encoding="utf-8")
    assert "auth_enrollment_login_flow" in content, \
        "auth_enrollment_login_flow not found in jarvis_core_gauntlet.py"
    assert "_check_auth_enrollment_login_flow" in content


def test_gauntlet_auth_mandatory():
    gauntlet_path = _REPO / "igris/core/jarvis_core_gauntlet.py"
    content = gauntlet_path.read_text(encoding="utf-8")
    # Check that auth is in MANDATORY_CHECKS
    mandatory_block_start = content.find("MANDATORY_CHECKS")
    mandatory_block_end = content.find(")", mandatory_block_start)
    mandatory_block = content[mandatory_block_start:mandatory_block_end]
    assert "auth_enrollment_login_flow" in mandatory_block, \
        "auth_enrollment_login_flow not in MANDATORY_CHECKS"
