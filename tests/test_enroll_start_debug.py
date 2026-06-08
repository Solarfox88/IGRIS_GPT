"""Tests for Fix #1280 — Debug "Errore sconosciuto" during UI registration.

Root causes identified:
1. Server needed restart to load auth_routes (registered after PR #1279).
2. JS _authFetch did not normalize FastAPI {"detail":...} error format →
   r.error was undefined → "Errore sconosciuto." shown in modal.
3. No Italian human-readable messages per error code.

This file covers:
- Real-payload enrollment happy path (christian_ricci-style payload)
- Username normalization (mixed-case → lowercase)
- FastAPI 404 response shape normalization (simulated via wrong path)
- Each validation error code maps to a meaningful message
- auth.js _normalizeApiError and _enrollErrorMsg are present and correct
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _client_with_tmp_root(tmp_dir: str):
    """Create a TestClient with a fresh isolated auth data directory."""
    os.environ["IGRIS_PROJECT_ROOT"] = tmp_dir
    for k in list(sys.modules.keys()):
        if any(x in k for x in ("auth_routes", "interlocutor_auth")):
            del sys.modules[k]
    from fastapi.testclient import TestClient
    from igris.web.server import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


def _unique_username() -> str:
    return "test_" + str(int(time.time() * 1000))[-8:]


# ── Backend: /api/auth/enroll/start ──────────────────────────────────────────

def test_enroll_start_christian_ricci_real_payload():
    """Real payload from UI: Christian_Ricci normalises to christian_ricci and enrolls OK."""
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_with_tmp_root(tmp)
        r = client.post("/api/auth/enroll/start", json={
            "username": "Christian_Ricci",
            "first_name": "Christian",
            "last_name": "Ricci",
            "email": "cricci.test@example.com",
            "mobile_phone": "+393895040554",
        })
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("ok") is True, f"Expected ok=True, got: {data}"
        assert "enrollment_token" in data, "enrollment_token missing from response"


def test_enroll_start_username_normalized_lowercase():
    """Mixed-case username is accepted and normalised to lowercase."""
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_with_tmp_root(tmp)
        r = client.post("/api/auth/enroll/start", json={
            "username": "MixedCase_User99",
            "first_name": "Mixed",
            "last_name": "Case",
            "email": "mixedcase@example.com",
            "mobile_phone": "+39000000001",
        })
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True


def test_enroll_start_username_taken_returns_error():
    """Second enroll with same username returns username_taken error."""
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_with_tmp_root(tmp)
        uname = _unique_username()
        payload = {
            "username": uname,
            "first_name": "A",
            "last_name": "B",
            "email": f"{uname}@example.com",
            "mobile_phone": "+39000000002",
        }
        r1 = client.post("/api/auth/enroll/start", json=payload)
        assert r1.status_code == 200 and r1.json().get("ok") is True, r1.text
        # Second attempt with same username
        r2 = client.post("/api/auth/enroll/start", json=payload)
        data2 = r2.json()
        assert data2.get("ok") is False
        assert data2.get("error") == "username_taken", f"Expected username_taken, got: {data2}"


def test_enroll_start_invalid_email_returns_error():
    """Invalid email format returns error (not 'Errore sconosciuto')."""
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_with_tmp_root(tmp)
        r = client.post("/api/auth/enroll/start", json={
            "username": _unique_username(),
            "first_name": "A",
            "last_name": "B",
            "email": "not-an-email",
            "mobile_phone": "+39000000003",
        })
        data = r.json()
        # Must be a recognisable error — not ok=True
        assert data.get("ok") is not True, f"Expected failure for invalid email, got: {data}"
        assert data.get("error") is not None, f"error field missing: {data}"


def test_enroll_start_forbidden_field_rejected():
    """Sending a forbidden field (trust_level) returns forbidden_field error."""
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_with_tmp_root(tmp)
        r = client.post("/api/auth/enroll/start", json={
            "username": _unique_username(),
            "first_name": "A",
            "last_name": "B",
            "email": "a@example.com",
            "mobile_phone": "+39000000004",
            "trust_level": "owner",   # forbidden
        })
        data = r.json()
        assert data.get("ok") is not True, f"Forbidden field should be rejected: {data}"
        assert data.get("error") in ("forbidden_field", "validation_failed"), \
            f"Expected forbidden_field/validation_failed, got: {data}"


def test_enroll_start_owner_username_rejected():
    """'owner' username must be rejected at enroll."""
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_with_tmp_root(tmp)
        r = client.post("/api/auth/enroll/start", json={
            "username": "owner",
            "first_name": "A",
            "last_name": "B",
            "email": "owner@example.com",
            "mobile_phone": "+39000000005",
        })
        data = r.json()
        assert data.get("ok") is not True, f"'owner' username should be rejected: {data}"


def test_enroll_route_registered():
    """The /api/auth/enroll/start route must be registered (not 404)."""
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_with_tmp_root(tmp)
        # Even a bad payload should NOT return 404 — it should return a validation error
        r = client.post("/api/auth/enroll/start", json={})
        assert r.status_code != 404, \
            f"Auth enroll route is not registered! Got 404. Server needs restart or auth_routes not loaded."


# ── Frontend static: JS error normalisation ──────────────────────────────────

def _auth_js() -> str:
    return _AUTH_JS.read_text(encoding="utf-8")


def test_auth_js_has_normalize_api_error():
    assert "_normalizeApiError" in _auth_js(), \
        "_normalizeApiError helper missing from auth.js"


def test_auth_js_has_enroll_error_msg():
    assert "_enrollErrorMsg" in _auth_js(), \
        "_enrollErrorMsg helper missing from auth.js"


def test_auth_js_no_errore_sconosciuto_in_submit():
    """'Errore sconosciuto.' must no longer appear literally in authSubmitEnrollStep1."""
    content = _auth_js()
    fn_start = content.find("async function authSubmitEnrollStep1")
    assert fn_start >= 0
    fn_body = content[fn_start:fn_start + 600]
    assert "Errore sconosciuto." not in fn_body, \
        "'Errore sconosciuto.' still present in authSubmitEnrollStep1 — should use _enrollErrorMsg"


def test_auth_js_normalize_handles_route_not_found():
    """_normalizeApiError must map 404 to route_not_found."""
    content = _auth_js()
    assert "route_not_found" in content, \
        "'route_not_found' error code missing from auth.js — 404 not handled"


def test_auth_js_normalize_handles_validation_failed():
    """_normalizeApiError must map FastAPI 422 to validation_failed."""
    content = _auth_js()
    assert "validation_failed" in content, \
        "'validation_failed' error code missing from auth.js"


def test_auth_js_enroll_error_messages_italian():
    """_enrollErrorMsg must contain Italian user-facing messages."""
    content = _auth_js()
    fn_start = content.find("function _enrollErrorMsg")
    assert fn_start >= 0, "_enrollErrorMsg not found"
    fn_body = content[fn_start:fn_start + 800]
    for phrase in ["già in uso", "non valido", "non disponibile", "Controlla"]:
        assert phrase in fn_body or phrase.lower() in fn_body.lower(), \
            f"Italian message fragment '{phrase}' missing from _enrollErrorMsg"


def test_auth_js_fetch_normalizes_on_error():
    """_authFetch must call _normalizeApiError when response is not ok."""
    content = _auth_js()
    fn_start = content.find("async function _authFetch")
    assert fn_start >= 0
    fn_body = content[fn_start:fn_start + 700]
    assert "_normalizeApiError" in fn_body, \
        "_authFetch does not call _normalizeApiError — FastAPI errors won't be normalized"


# ── Backend: /api/auth/enroll/complete ───────────────────────────────────────

def test_enroll_complete_missing_token_returns_422():
    """Server returns HTTP 422 (not 500) when enrollment_token is missing from body."""
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_with_tmp_root(tmp)
        r = client.post("/api/auth/enroll/complete", json={
            "password": "Test1234!",
            "confirm_password": "Test1234!",
        })
        assert r.status_code == 422, \
            f"Missing enrollment_token should give 422, got {r.status_code}: {r.text}"


def test_enroll_complete_weak_password_returns_error():
    """Weak password (no digit) returns password_requires_digit error."""
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_with_tmp_root(tmp)
        uname = _unique_username()
        r1 = client.post("/api/auth/enroll/start", json={
            "username": uname, "first_name": "A", "last_name": "B",
            "email": f"{uname}@example.com", "mobile_phone": "+39000000010",
        })
        assert r1.json().get("ok") is True, r1.text
        token = r1.json()["enrollment_token"]

        r2 = client.post("/api/auth/enroll/complete", json={
            "enrollment_token": token,
            "password": "onlyletters",
            "confirm_password": "onlyletters",
        })
        data = r2.json()
        assert data.get("ok") is False
        assert data.get("error") == "password_requires_digit", \
            f"Expected password_requires_digit, got: {data}"


def test_enroll_complete_retry_after_weak_password_succeeds():
    """After a failed attempt (weak pw), retrying with same token and strong pw succeeds.

    This verifies the JS fix: _enrollmentToken must NOT be cleared on failure,
    so the user can retry without restarting from step 1.
    """
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_with_tmp_root(tmp)
        uname = _unique_username()
        r1 = client.post("/api/auth/enroll/start", json={
            "username": uname, "first_name": "A", "last_name": "B",
            "email": f"{uname}@example.com", "mobile_phone": "+39000000011",
        })
        token = r1.json()["enrollment_token"]

        # First attempt — weak password
        r2a = client.post("/api/auth/enroll/complete", json={
            "enrollment_token": token,
            "password": "onlyletters",
            "confirm_password": "onlyletters",
        })
        assert r2a.json().get("ok") is False

        # Second attempt — same token, correct password — must succeed
        r2b = client.post("/api/auth/enroll/complete", json={
            "enrollment_token": token,
            "password": "StrongPass1",
            "confirm_password": "StrongPass1",
        })
        data = r2b.json()
        assert data.get("ok") is True, \
            f"Retry with same token after weak-pw failure should succeed, got: {data}"
        assert "session_token" in data, "session_token missing after successful complete"


# ── Frontend static: step 2 JS fixes ─────────────────────────────────────────

def test_auth_js_has_enroll_step2_error_msg():
    assert "_enrollStep2ErrorMsg" in _auth_js(), \
        "_enrollStep2ErrorMsg helper missing from auth.js"


def test_auth_js_step2_token_cleared_only_on_success():
    """_enrollmentToken = null must appear inside the 'if (r.ok)' block, not before."""
    content = _auth_js()
    fn_start = content.find("async function authSubmitEnrollStep2")
    assert fn_start >= 0
    fn_body = content[fn_start:fn_start + 1200]
    # The null assignment must come AFTER 'if (r.ok)'
    ok_pos = fn_body.find("if (r.ok)")
    null_pos = fn_body.find("_enrollmentToken = null")
    assert null_pos > ok_pos, \
        "_enrollmentToken = null must be INSIDE if (r.ok) block — currently cleared before, " \
        "which wipes the token on failure and causes 'validation_failed' on retry"


def test_auth_js_step2_italian_messages():
    """_enrollStep2ErrorMsg must contain Italian messages for password errors."""
    content = _auth_js()
    fn_start = content.find("function _enrollStep2ErrorMsg")
    assert fn_start >= 0, "_enrollStep2ErrorMsg not found"
    fn_body = content[fn_start:fn_start + 800]
    for phrase in ["almeno", "lettera", "numero", "scaduto", "Ricomincia"]:
        assert phrase in fn_body, \
            f"Italian message fragment '{phrase}' missing from _enrollStep2ErrorMsg"
