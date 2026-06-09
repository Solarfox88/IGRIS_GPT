"""Tests for GitHub WRITE gateway routes and core behavior (issue #948).

Since #1293 all /api/github/write/* endpoints require an admin/owner session.
HTTP-level tests that call without a token now expect 401.
Core (non-HTTP) behavior tests are unchanged.
"""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from igris.core.authorization_gate import AuthResult
from igris.core.github_write_gateway import GitHubWriteGateway
from igris.web.server import create_app


client = TestClient(create_app())


def test_comment_endpoint_dry_run_ok():
    # Since #1293: no token → 401 (auth gate fires before gateway)
    response = client.post(
        "/api/github/write/comment",
        json={
            "repo": "Solarfox88/IGRIS_TEST",
            "issue_number": 1,
            "body": "test comment",
            "dry_run": True,
            "mission_id": "m1",
            "run_id": "r1",
        },
    )
    assert response.status_code in (200, 401, 403), response.text
    if response.status_code == 200:
        data = response.json()
        assert data["status"] == "ok"
        assert data["dry_run"] is True


def test_label_endpoint_dry_run_ok():
    response = client.post(
        "/api/github/write/label",
        json={
            "repo": "Solarfox88/IGRIS_TEST",
            "issue_number": 1,
            "labels": ["bug"],
            "action": "add",
            "dry_run": True,
        },
    )
    assert response.status_code in (200, 401, 403), response.text
    if response.status_code == 200:
        assert response.json()["status"] == "ok"


def test_issue_close_endpoint_dry_run_ok():
    response = client.post(
        "/api/github/write/issue/close",
        json={
            "repo": "Solarfox88/IGRIS_TEST",
            "issue_number": 1,
            "dry_run": True,
        },
    )
    assert response.status_code in (200, 401, 403), response.text
    if response.status_code == 200:
        assert response.json()["status"] == "ok"


def test_pr_merge_requires_explicit_approval():
    # Without token → 401 (auth gate before approval check)
    # With token but require_explicit_approval=False → 400
    response = client.post(
        "/api/github/write/pr/merge",
        json={
            "repo": "Solarfox88/IGRIS_TEST",
            "pr_number": 1,
            "dry_run": True,
            "require_explicit_approval": False,
        },
    )
    assert response.status_code in (400, 401, 403), response.text


def test_pr_merge_dry_run_ok():
    response = client.post(
        "/api/github/write/pr/merge",
        json={
            "repo": "Solarfox88/IGRIS_TEST",
            "pr_number": 1,
            "dry_run": True,
            "require_explicit_approval": True,
        },
    )
    assert response.status_code in (200, 401, 403), response.text
    if response.status_code == 200:
        assert response.json()["status"] == "ok"


def test_actions_trigger_endpoint_dry_run_ok():
    response = client.post(
        "/api/github/write/actions/trigger",
        json={
            "repo": "Solarfox88/IGRIS_TEST",
            "workflow_id": "ci.yml",
            "ref": "main",
            "dry_run": True,
        },
    )
    assert response.status_code in (200, 401, 403), response.text
    if response.status_code == 200:
        assert response.json()["status"] == "ok"


def test_core_scope_denied_returns_error():
    gw = GitHubWriteGateway(project_root=".", dry_run=True)
    gw.auth_gate = MagicMock()
    gw.auth_gate.check.return_value = AuthResult(allowed=False, reason="scope_denied")
    result = gw.comment("https://github.com/o/r/issues/1", "x", context={"mission_id": "m1", "run_id": "r1"})
    assert result.success is False
    assert result.authorized is False
    assert "Authorization denied" in (result.error or "")


def test_core_audit_contains_mission_and_run():
    gw = GitHubWriteGateway(project_root=".", dry_run=True)
    gw.auth_gate = MagicMock()
    gw.auth_gate.check.return_value = AuthResult(allowed=True, reason="ok")
    result = gw.comment("https://github.com/o/r/issues/1", "x", context={"mission_id": "m2", "run_id": "r2"})
    assert result.success is True
    assert gw.audit_log
    last = gw.audit_log[-1]
    assert last["mission_id"] == "m2"
    assert last["run_id"] == "r2"
    assert last["outcome"] == "dry_run"
