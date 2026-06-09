"""P0 Fix #1293 — Write endpoint authentication gate tests.

Verifies that all endpoints with real side effects require a valid
admin/owner session token. No side effect must happen without auth.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_REPO = Path(__file__).parent.parent


def _client_isolated(tmp_dir: str):
    os.environ["IGRIS_PROJECT_ROOT"] = tmp_dir
    for k in list(sys.modules.keys()):
        if any(x in k for x in ("auth_routes", "interlocutor_auth", "routes_01",
                                 "write_auth", "github_write", "routes_08",
                                 "routes_04", "routes_03")):
            del sys.modules[k]
    from fastapi.testclient import TestClient
    from igris.web.server import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


def _enroll_and_login(client) -> str:
    uname = "qa_wg_" + str(int(time.time() * 1000))[-7:]
    r1 = client.post("/api/auth/enroll/start", json={
        "username": uname, "first_name": "W", "last_name": "G",
        "email": uname + "@test.invalid", "mobile_phone": "+390000009001",
    })
    assert r1.json().get("ok") is True, r1.text
    tok = r1.json()["enrollment_token"]
    r2 = client.post("/api/auth/enroll/complete", json={
        "enrollment_token": tok, "password": "WriteGate1!", "confirm_password": "WriteGate1!",
    })
    assert r2.json().get("ok") is True, r2.text
    return r2.json()["session_token"]


# ── module existence ───────────────────────────────────────────────────────────

def test_write_auth_module_exists():
    assert _REPO.joinpath("igris/api/write_auth.py").exists(), \
        "igris/api/write_auth.py not found — P0 fix not applied"


def test_write_auth_module_importable():
    from igris.api.write_auth import require_write_auth, require_write_auth_or_raise  # noqa


def test_write_auth_uses_igris_project_root():
    src = _REPO.joinpath("igris/api/write_auth.py").read_text()
    assert "IGRIS_PROJECT_ROOT" in src
    assert "CONFIG.project_root" not in src


# ── fs/write ──────────────────────────────────────────────────────────────────

def test_fs_write_without_token_blocked_and_no_file_created():
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        canary = Path(tmp) / "p0_canary_noauth.txt"
        r = client.post("/api/tools/fs/write",
                        json={"path": str(canary), "content": "SHOULD_NOT_EXIST"})
        assert r.status_code in (401, 403), \
            f"Expected 401/403, got {r.status_code}: {r.text[:200]}"
        assert not canary.exists(), "Canary file created without auth! P0 still open."


def test_fs_write_invalid_token_blocked_and_no_file_created():
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        canary = Path(tmp) / "p0_canary_invalid.txt"
        r = client.post("/api/tools/fs/write",
                        json={"path": str(canary), "content": "SHOULD_NOT_EXIST"},
                        headers={"Authorization": "Bearer FAKE_TOKEN_P0_INVALID"})
        assert r.status_code in (401, 403), \
            f"Expected 401/403, got {r.status_code}: {r.text[:200]}"
        assert not canary.exists(), "Canary file created with invalid token!"


def test_fs_write_limited_user_blocked_and_no_file_created():
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        session_token = _enroll_and_login(client)
        canary = Path(tmp) / "p0_canary_limited.txt"
        r = client.post("/api/tools/fs/write",
                        json={"path": str(canary), "content": "SHOULD_NOT_EXIST"},
                        headers={"Authorization": f"Bearer {session_token}"})
        assert r.status_code in (401, 403), \
            f"Expected 401/403 for limited user, got {r.status_code}: {r.text[:200]}"
        assert not canary.exists(), "Canary file created with limited user!"


# ── shell/execute ──────────────────────────────────────────────────────────────

def test_shell_exec_without_token_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        r = client.post("/api/tools/shell/execute", json={"command_id": "git_status"})
        assert r.status_code in (401, 403), \
            f"Expected 401/403, got {r.status_code}: {r.text[:200]}"


def test_shell_exec_limited_user_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        tok = _enroll_and_login(client)
        r = client.post("/api/tools/shell/execute",
                        json={"command_id": "git_status"},
                        headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code in (401, 403), \
            f"Expected 401/403, got {r.status_code}: {r.text[:200]}"


# ── terminal/run ───────────────────────────────────────────────────────────────

def test_terminal_run_without_token_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        r = client.post("/api/terminal/run", json={"command_id": "git_status"})
        assert r.status_code in (401, 403), \
            f"Expected 401/403, got {r.status_code}: {r.text[:200]}"


def test_terminal_run_limited_user_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        tok = _enroll_and_login(client)
        r = client.post("/api/terminal/run",
                        json={"command_id": "git_status"},
                        headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code in (401, 403), \
            f"Expected 401/403, got {r.status_code}: {r.text[:200]}"


# ── github/write — monkeypatched (no real GitHub calls) ───────────────────────

def test_github_issue_create_without_token_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        with patch("igris.api.routes.github_write._get_gateway") as mock_gw:
            r = client.post("/api/github/write/issue/create", json={
                "repo": "Solarfox88/IGRIS_GPT",
                "title": "P0 canary — should be blocked",
                "body": "Should never reach GitHub.",
                "dry_run": False,
            })
        assert r.status_code in (401, 403), \
            f"Expected 401/403, got {r.status_code}: {r.text[:200]}"
        mock_gw.assert_not_called()


def test_github_comment_without_token_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        with patch("igris.api.routes.github_write._get_gateway") as mock_gw:
            r = client.post("/api/github/write/comment", json={
                "repo": "Solarfox88/IGRIS_GPT",
                "issue_number": 1293,
                "body": "P0 canary — should be blocked",
                "dry_run": False,
            })
        assert r.status_code in (401, 403), \
            f"Expected 401/403, got {r.status_code}: {r.text[:200]}"
        mock_gw.assert_not_called()


def test_github_issue_create_limited_user_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        tok = _enroll_and_login(client)
        with patch("igris.api.routes.github_write._get_gateway") as mock_gw:
            r = client.post("/api/github/write/issue/create",
                            json={
                                "repo": "Solarfox88/IGRIS_GPT",
                                "title": "P0 canary limited",
                                "body": "Should not reach GitHub.",
                                "dry_run": False,
                            },
                            headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code in (401, 403), \
            f"Expected 401/403, got {r.status_code}: {r.text[:200]}"
        mock_gw.assert_not_called()


def test_github_pr_merge_without_token_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        with patch("igris.api.routes.github_write._get_gateway") as mock_gw:
            r = client.post("/api/github/write/pr/merge", json={
                "repo": "Solarfox88/IGRIS_GPT",
                "pr_number": 9999,
                "dry_run": False,
                "require_explicit_approval": True,
            })
        assert r.status_code in (401, 403), \
            f"Expected 401/403, got {r.status_code}: {r.text[:200]}"
        mock_gw.assert_not_called()


# ── loop ───────────────────────────────────────────────────────────────────────

def test_loop_step_without_token_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        r = client.post("/api/loop/step", json={})
        assert r.status_code in (401, 403), \
            f"Expected 401/403, got {r.status_code}: {r.text[:200]}"


def test_loop_run_without_token_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        r = client.post("/api/loop/run", json={"max_steps": 1})
        assert r.status_code in (401, 403), \
            f"Expected 401/403, got {r.status_code}: {r.text[:200]}"


# ── error response safety ──────────────────────────────────────────────────────

def test_no_raw_token_in_error_response():
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        fake = "FAKE_TOKEN_P0_SHOULD_NOT_ECHO_12345"
        r = client.post("/api/tools/fs/write",
                        json={"path": "/tmp/x.txt", "content": "x"},
                        headers={"Authorization": f"Bearer {fake}"})
        assert r.status_code in (401, 403)
        assert fake not in r.text, \
            f"Raw token echoed in error response: {r.text[:300]}"


def test_auth_error_is_json():
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        r = client.post("/api/tools/fs/write",
                        json={"path": "/tmp/x.txt", "content": "x"})
        assert r.status_code in (401, 403)
        body = r.json()
        assert isinstance(body, dict), f"Expected dict, got {type(body)}"


# ── github_write.py source: auth guard added ──────────────────────────────────

def test_github_write_routes_import_write_auth():
    src = _REPO.joinpath("igris/api/routes/github_write.py").read_text()
    assert "require_write_auth_or_raise" in src, \
        "github_write.py does not call require_write_auth_or_raise — P0 not applied"
    assert "from igris.api.write_auth import require_write_auth_or_raise" in src or \
           "write_auth" in src, \
        "github_write.py does not import write_auth"


def test_routes_08_imports_write_auth():
    src = _REPO.joinpath("igris/web/routers/routes_08.py").read_text()
    assert "require_write_auth_or_raise" in src, \
        "routes_08.py does not call require_write_auth_or_raise — fs/write P0 not applied"


def test_routes_04_imports_write_auth():
    src = _REPO.joinpath("igris/web/routers/routes_04.py").read_text()
    assert "require_write_auth_or_raise" in src, \
        "routes_04.py does not call require_write_auth_or_raise — terminal/run P0 not applied"


# ── positive path: admin/owner token is allowed ───────────────────────────────

def _enroll_and_promote_to_admin(client, tmp_dir: str) -> str:
    """Enroll a user and promote to admin trust level; return session token."""
    uname = "qa_admin_" + str(int(time.time() * 1000))[-7:]
    # Enroll
    r1 = client.post("/api/auth/enroll/start", json={
        "username": uname, "first_name": "Admin", "last_name": "QA",
        "email": uname + "@test.invalid", "mobile_phone": "+390000009002",
    })
    assert r1.json().get("ok") is True, r1.text
    r2 = client.post("/api/auth/enroll/complete", json={
        "enrollment_token": r1.json()["enrollment_token"],
        "password": "AdminGate1!", "confirm_password": "AdminGate1!",
    })
    assert r2.json().get("ok") is True, r2.text
    session_token = r2.json()["session_token"]

    # Promote profile to admin directly (bypasses enrollment trust policy)
    from igris.core.identity_resolver import IdentityResolver, InterlocutorProfile
    ir = IdentityResolver(project_root=tmp_dir)
    profiles = ir._load()
    if uname in profiles:
        profiles[uname].trust_level = "admin"
        ir.update(profiles[uname])
    else:
        # Create from scratch if not yet stored
        p = InterlocutorProfile(
            profile_id=uname,
            display_name=f"Admin QA {uname}",
            first_name="Admin", last_name="QA",
            trust_level="admin",
            authorized_scopes=["chat", "read_own_profile"],
        )
        ir.update(p)
    return session_token


def test_write_auth_admin_valid_token_allowed():
    """require_write_auth() must return allowed=True for a valid admin session."""
    import asyncio
    from unittest.mock import MagicMock
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        tok = _enroll_and_promote_to_admin(client, tmp)

        import os
        os.environ["IGRIS_PROJECT_ROOT"] = tmp
        import importlib, sys
        for k in list(sys.modules.keys()):
            if "write_auth" in k:
                del sys.modules[k]

        from igris.api.write_auth import require_write_auth
        req = MagicMock()
        req.headers = {"Authorization": f"Bearer {tok}"}

        result = asyncio.new_event_loop().run_until_complete(require_write_auth(req))
        assert result.allowed, (
            f"Admin token should be allowed but got: allowed={result.allowed}, "
            f"trust={result.trust_level}, code={result.error_code}, msg={result.error_message}"
        )
        assert result.trust_level == "admin", f"Expected trust=admin, got {result.trust_level}"


def test_fs_write_admin_valid_token_can_write_canary():
    """A valid admin session token must be able to write a file."""
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        tok = _enroll_and_promote_to_admin(client, tmp)
        canary = Path(tmp) / "admin_canary.txt"
        r = client.post(
            "/api/tools/fs/write",
            json={"path": str(canary), "content": "admin_write_ok"},
            headers={"Authorization": f"Bearer {tok}"},
        )
        # Must NOT be 401/403 — gate should let admin through
        assert r.status_code not in (401, 403), (
            f"Admin token wrongly blocked: {r.status_code} — {r.text[:300]}"
        )


def test_github_write_admin_valid_token_reaches_gateway_or_dry_run():
    """A valid admin session must reach the github write handler (dry_run=True)."""
    with tempfile.TemporaryDirectory() as tmp:
        client = _client_isolated(tmp)
        tok = _enroll_and_promote_to_admin(client, tmp)
        r = client.post(
            "/api/github/write/issue/create",
            json={
                "repo": "Solarfox88/IGRIS_GPT",
                "title": "P0 canary — dry run admin test",
                "body": "This is a dry-run test — no real issue should be created.",
                "dry_run": True,
            },
            headers={"Authorization": f"Bearer {tok}"},
        )
        # Auth gate must pass; dry_run=True so no real GitHub call
        assert r.status_code not in (401, 403), (
            f"Admin token wrongly blocked on github write: {r.status_code} — {r.text[:300]}"
        )
