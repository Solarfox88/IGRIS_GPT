"""Tests for Auth API routes (#1272 PR 3).

Coverage:
    POST /api/auth/enroll/start
    POST /api/auth/enroll/complete
    POST /api/auth/login
    POST /api/auth/logout
    GET  /api/auth/me
    GET  /api/auth/health

Uses real TestClient(create_app()) against a fully isolated temp directory.
No mocks of auth internals — integration-style for the happy paths.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ── App factory ────────────────────────────────────────────────────────────────

def _make_client(tmp_root: str) -> TestClient:
    """Create a fresh app instance rooted at tmp_root."""
    os.environ["IGRIS_PROJECT_ROOT"] = tmp_root
    # Force reload of auth_routes so _PROJECT_ROOT picks up new env value
    for mod_name in list(sys.modules.keys()):
        if "auth_routes" in mod_name or "interlocutor_auth" in mod_name:
            del sys.modules[mod_name]
    from igris.web.server import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_root(tmp_path):
    return str(tmp_path)


@pytest.fixture()
def client(tmp_root):
    return _make_client(tmp_root)


# ── Helpers ────────────────────────────────────────────────────────────────────

_VALID_ENROLL = {
    "username": "testuser",
    "first_name": "Test",
    "last_name": "User",
    "email": "test@example.com",
    "mobile_phone": "+39 333 1234567",
}

_FAKE_PASSWORD = "FAKE_PASSWORD_abc123!"


def _do_enroll_start(client, overrides=None):
    body = dict(_VALID_ENROLL)
    if overrides:
        body.update(overrides)
    return client.post("/api/auth/enroll/start", json=body)


def _full_enrollment(client, username="testuser", password=None):
    """Complete full enrollment flow. Returns (enrollment_token, session_token)."""
    pw = password or _FAKE_PASSWORD
    r = _do_enroll_start(client, {"username": username})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    et = data["enrollment_token"]

    r2 = client.post("/api/auth/enroll/complete", json={
        "enrollment_token": et,
        "password": pw,
        "confirm_password": pw,
    })
    assert r2.status_code == 200, r2.text
    data2 = r2.json()
    assert data2["ok"] is True
    return et, data2["session_token"]


# ── GET /api/auth/health ───────────────────────────────────────────────────────

def test_health_returns_ok(client):
    r = client.get("/api/auth/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "credentials" in data
    assert "sessions" in data
    assert "enrollments" in data


# ── POST /api/auth/enroll/start — happy path ───────────────────────────────────

def test_enroll_start_success(client):
    r = _do_enroll_start(client)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "enrollment_token" in data
    assert len(data["enrollment_token"]) > 20
    assert data["profile_id"] == "testuser"
    assert "expires_at" in data


def test_enroll_start_token_not_empty(client):
    r = _do_enroll_start(client)
    tok = r.json()["enrollment_token"]
    assert tok and tok.strip()


# ── POST /api/auth/enroll/start — validation errors ───────────────────────────

def test_enroll_start_reserved_username_owner(client):
    r = _do_enroll_start(client, {"username": "owner"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["error"] == "validation_failed"
    assert "username_reserved" in data["details"]


def test_enroll_start_reserved_username_system(client):
    r = _do_enroll_start(client, {"username": "system"})
    assert r.json()["ok"] is False
    assert "username_reserved" in r.json()["details"]


def test_enroll_start_invalid_username_format(client):
    r = _do_enroll_start(client, {"username": "BAD USER!"})
    data = r.json()
    assert data["ok"] is False
    assert "invalid_username_format" in data["details"]


def test_enroll_start_invalid_email(client):
    r = _do_enroll_start(client, {"email": "not-an-email"})
    assert r.json()["ok"] is False
    assert "invalid_email" in r.json()["details"]


def test_enroll_start_invalid_phone(client):
    r = _do_enroll_start(client, {"mobile_phone": "abc"})
    assert r.json()["ok"] is False
    assert "invalid_mobile_phone" in r.json()["details"]


def test_enroll_start_missing_first_name(client):
    r = _do_enroll_start(client, {"first_name": ""})
    assert r.json()["ok"] is False
    assert "first_name_required" in r.json()["details"]


def test_enroll_start_missing_last_name(client):
    r = _do_enroll_start(client, {"last_name": "   "})
    assert r.json()["ok"] is False
    assert "last_name_required" in r.json()["details"]


def test_enroll_start_forbidden_field_trust_level(client):
    r = client.post("/api/auth/enroll/start", json={
        **_VALID_ENROLL,
        "trust_level": "admin",
    })
    data = r.json()
    assert data["ok"] is False
    assert data["error"] == "forbidden_field"
    assert "trust_level" in data["forbidden_fields"]


def test_enroll_start_forbidden_field_role(client):
    r = client.post("/api/auth/enroll/start", json={
        **_VALID_ENROLL,
        "role": "admin",
    })
    data = r.json()
    assert data["ok"] is False
    assert data["error"] == "forbidden_field"


def test_enroll_start_duplicate_username(client):
    _do_enroll_start(client)  # first enrollment
    r = _do_enroll_start(client)  # same username
    assert r.json()["ok"] is False
    assert r.json()["error"] == "username_taken"


# ── POST /api/auth/enroll/complete — happy path ────────────────────────────────

def test_enroll_complete_success(client):
    r = _do_enroll_start(client)
    et = r.json()["enrollment_token"]
    r2 = client.post("/api/auth/enroll/complete", json={
        "enrollment_token": et,
        "password": _FAKE_PASSWORD,
        "confirm_password": _FAKE_PASSWORD,
    })
    assert r2.status_code == 200
    data = r2.json()
    assert data["ok"] is True
    assert "session_token" in data
    assert len(data["session_token"]) > 20
    assert data["profile_id"] == "testuser"


def test_enroll_complete_password_mismatch(client):
    r = _do_enroll_start(client)
    et = r.json()["enrollment_token"]
    r2 = client.post("/api/auth/enroll/complete", json={
        "enrollment_token": et,
        "password": _FAKE_PASSWORD,
        "confirm_password": "WRONG_FAKE_PASSWORD",
    })
    assert r2.json()["ok"] is False
    assert r2.json()["error"] == "password_mismatch"


def test_enroll_complete_invalid_token(client):
    r = client.post("/api/auth/enroll/complete", json={
        "enrollment_token": "FAKE_TOKEN_invalid_token_xyz",
        "password": _FAKE_PASSWORD,
        "confirm_password": _FAKE_PASSWORD,
    })
    assert r.json()["ok"] is False
    assert r.json()["error"] == "invalid_enrollment_token"


def test_enroll_complete_profile_is_limited(client, tmp_root):
    _full_enrollment(client, "alice")
    from igris.core.identity_resolver import IdentityResolver
    ir = IdentityResolver(tmp_root)
    profile = ir.resolve("alice")
    assert profile.trust_level == "limited"
    assert "chat" in profile.authorized_scopes
    assert "memory_basic" in profile.authorized_scopes
    assert "read_own_profile" in profile.authorized_scopes
    assert "*" not in profile.authorized_scopes
    assert "admin" not in profile.authorized_scopes
    assert "deploy" not in profile.authorized_scopes


def test_enroll_complete_no_password_in_response(client):
    r = _do_enroll_start(client)
    et = r.json()["enrollment_token"]
    r2 = client.post("/api/auth/enroll/complete", json={
        "enrollment_token": et,
        "password": _FAKE_PASSWORD,
        "confirm_password": _FAKE_PASSWORD,
    })
    resp_text = r2.text
    assert _FAKE_PASSWORD not in resp_text


# ── POST /api/auth/login ───────────────────────────────────────────────────────

def test_login_success(client):
    _full_enrollment(client, "bob")
    r = client.post("/api/auth/login", json={
        "username": "bob",
        "password": _FAKE_PASSWORD,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "session_token" in data
    assert data["profile_id"] == "bob"


def test_login_wrong_password(client):
    _full_enrollment(client, "charlie")
    r = client.post("/api/auth/login", json={
        "username": "charlie",
        "password": "FAKE_PASSWORD_wrong",
    })
    data = r.json()
    assert data["ok"] is False
    assert data["error"] == "invalid_credentials"
    # No user enumeration
    assert "charlie" not in str(data.get("error", ""))
    assert "charlie" not in str(data.get("details", ""))


def test_login_unknown_user_same_error(client):
    """Login for unknown user must return same generic error (no enumeration)."""
    r = client.post("/api/auth/login", json={
        "username": "nonexistent_user_xyz",
        "password": _FAKE_PASSWORD,
    })
    assert r.json()["error"] == "invalid_credentials"


def test_login_no_password_in_response(client):
    _full_enrollment(client, "dave")
    r = client.post("/api/auth/login", json={
        "username": "dave",
        "password": _FAKE_PASSWORD,
    })
    assert _FAKE_PASSWORD not in r.text


# ── POST /api/auth/logout ──────────────────────────────────────────────────────

def test_logout_with_bearer(client):
    _, session_token = _full_enrollment(client, "eve")
    r = client.post("/api/auth/logout",
                    headers={"Authorization": f"Bearer {session_token}"})
    assert r.json()["ok"] is True


def test_logout_invalidates_session(client):
    _, session_token = _full_enrollment(client, "frank")
    client.post("/api/auth/logout",
                headers={"Authorization": f"Bearer {session_token}"})
    r = client.get("/api/auth/me",
                   headers={"Authorization": f"Bearer {session_token}"})
    assert r.json()["ok"] is False


def test_logout_no_token(client):
    r = client.post("/api/auth/logout", json={})
    assert r.json()["ok"] is False
    assert r.json()["error"] == "invalid_session"


# ── GET /api/auth/me ───────────────────────────────────────────────────────────

def test_me_returns_profile(client):
    _, session_token = _full_enrollment(client, "grace")
    r = client.get("/api/auth/me",
                   headers={"Authorization": f"Bearer {session_token}"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    p = data["profile"]
    assert p["profile_id"] == "grace"
    assert p["trust_level"] == "limited"
    assert "chat" in p["authorized_scopes"]


def test_me_no_password_in_profile(client):
    _, session_token = _full_enrollment(client, "henry")
    r = client.get("/api/auth/me",
                   headers={"Authorization": f"Bearer {session_token}"})
    profile_str = str(r.json().get("profile", {}))
    assert "password" not in profile_str.lower()
    assert _FAKE_PASSWORD not in profile_str


def test_me_no_email_mobile_in_profile(client):
    _, session_token = _full_enrollment(client, "iris")
    r = client.get("/api/auth/me",
                   headers={"Authorization": f"Bearer {session_token}"})
    profile_str = str(r.json().get("profile", {}))
    assert "email" not in profile_str.lower()
    assert "mobile" not in profile_str.lower()
    assert "phone" not in profile_str.lower()


def test_me_no_token(client):
    r = client.get("/api/auth/me")
    assert r.json()["ok"] is False
    assert r.json()["error"] == "authentication_required"


def test_me_invalid_token(client):
    r = client.get("/api/auth/me",
                   headers={"Authorization": "Bearer FAKE_TOKEN_invalid_xyz"})
    assert r.json()["ok"] is False
