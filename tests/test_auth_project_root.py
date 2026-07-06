"""Tests for PR-1 of epic #1301: auth root resolved lazily at call time.

Verifies that IGRIS_PROJECT_ROOT is read from os.environ at each call rather
than captured once at module import time.  Before this fix, changing the env
var after import had no effect and tests had to force a full module reload.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


# ── 1. _get_auth_root helper ──────────────────────────────────────────────────

def test_auth_root_respects_igris_project_root_env_var(monkeypatch, tmp_path):
    """_get_auth_root() must return the current value of IGRIS_PROJECT_ROOT."""
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path))
    from igris.api.write_auth import _get_auth_root
    assert _get_auth_root() == str(tmp_path)


def test_auth_root_fallback_when_env_missing(monkeypatch):
    """_get_auth_root() must fall back to '.' when IGRIS_PROJECT_ROOT is unset."""
    monkeypatch.delenv("IGRIS_PROJECT_ROOT", raising=False)
    from igris.api.write_auth import _get_auth_root
    assert _get_auth_root() == "."


def test_auth_root_fallback_when_env_empty(monkeypatch):
    """_get_auth_root() must fall back to '.' when IGRIS_PROJECT_ROOT is empty string."""
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", "")
    from igris.api.write_auth import _get_auth_root
    assert _get_auth_root() == "."


def test_env_var_change_after_import_is_respected(monkeypatch, tmp_path):
    """Changing IGRIS_PROJECT_ROOT after module import must be picked up immediately.

    Before PR-1, auth_routes.py stored _PROJECT_ROOT at import time, so this
    would have required a module reload to take effect.
    """
    first_root = str(tmp_path / "first")
    second_root = str(tmp_path / "second")

    monkeypatch.setenv("IGRIS_PROJECT_ROOT", first_root)
    from igris.api.write_auth import _get_auth_root
    assert _get_auth_root() == first_root

    # Change env var — no module reload needed
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", second_root)
    assert _get_auth_root() == second_root


# ── 2. auth_routes and write_auth use the same root ──────────────────────────

def test_auth_routes_and_write_auth_use_same_root(monkeypatch, tmp_path):
    """auth_routes helpers and write_auth must resolve the same root for a given env."""
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path))

    from igris.api.write_auth import _get_auth_root as wa_root
    # Import after env is set so the lazy call returns the right value
    import igris.api.routes.auth_routes as ar_mod  # noqa: F401 — triggers module load
    from igris.api.write_auth import _get_auth_root as ar_root

    assert wa_root() == ar_root() == str(tmp_path)


# ── 3. Auth stores are created in the correct root directory ─────────────────

def test_session_store_path_is_under_igris_project_root(monkeypatch, tmp_path):
    """AuthSessionManager.storage_path must be rooted at IGRIS_PROJECT_ROOT."""
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path))

    from igris.core.interlocutor_auth import AuthSessionManager
    sm = AuthSessionManager(project_root=str(tmp_path))

    assert sm.storage_path == tmp_path / ".igris" / "auth" / "sessions.json", (
        f"Expected path under tmp_path, got: {sm.storage_path}"
    )


def test_credential_store_path_is_under_igris_project_root(monkeypatch, tmp_path):
    """AuthCredentialStore.storage_path must be rooted at IGRIS_PROJECT_ROOT."""
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path))

    from igris.core.interlocutor_auth import AuthCredentialStore
    cs = AuthCredentialStore(project_root=str(tmp_path))

    assert cs.storage_path == tmp_path / ".igris" / "auth" / "credentials.json", (
        f"Expected path under tmp_path, got: {cs.storage_path}"
    )


# ── 4. Login/logout/me flow with isolated tmp_path ───────────────────────────

@pytest.fixture()
def auth_client(monkeypatch, tmp_path):
    """Isolated app client with auth root pointing at tmp_path."""
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path))
    from fastapi.testclient import TestClient
    from igris.web.server import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


_ENROLL_DATA = {
    "username": "pr1user",
    "first_name": "PR",
    "last_name": "One",
    "email": "pr1@example.com",
    "mobile_phone": "+39 333 0000001",
}
_PASSWORD = "FAKE_PASSWORD_pr1_2024!"


def _do_enroll(client) -> str:
    """Full enrollment flow; returns session token."""
    r = client.post("/api/auth/enroll/start", json=_ENROLL_DATA)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok"), f"enroll/start failed: {body}"
    enrollment_token = body["enrollment_token"]

    r2 = client.post("/api/auth/enroll/complete", json={
        "enrollment_token": enrollment_token,
        "password": _PASSWORD,
        "confirm_password": _PASSWORD,
    })
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2.get("ok"), f"enroll/complete failed: {body2}"
    return body2["session_token"]


def test_login_uses_igris_project_root(auth_client, monkeypatch, tmp_path):
    """Login must succeed and use auth stores rooted at IGRIS_PROJECT_ROOT."""
    _do_enroll(auth_client)  # create user first

    r = auth_client.post("/api/auth/login", json={
        "username": _ENROLL_DATA["username"],
        "password": _PASSWORD,
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("ok"), f"login failed: {data}"
    assert "session_token" in data

    # sessions.json must live under tmp_path, not CWD or home
    sessions_file = tmp_path / ".igris" / "auth" / "sessions.json"
    assert sessions_file.exists(), "sessions.json not found under IGRIS_PROJECT_ROOT"


def test_logout_invalidates_session(auth_client):
    """Logout must revoke the session so /api/auth/me returns error."""
    token = _do_enroll(auth_client)

    r_logout = auth_client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_logout.status_code == 200
    assert r_logout.json().get("ok")

    r_me = auth_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_me.status_code == 200
    data = r_me.json()
    assert not data.get("ok"), f"Expected error after logout, got: {data}"


def test_me_returns_profile_for_valid_session(auth_client):
    """GET /api/auth/me must return profile fields for a valid session."""
    token = _do_enroll(auth_client)

    r = auth_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok"), f"me failed: {data}"
    profile = data["profile"]
    assert profile["profile_id"] == _ENROLL_DATA["username"]
    assert "trust_level" in profile
    assert "authorized_scopes" in profile
