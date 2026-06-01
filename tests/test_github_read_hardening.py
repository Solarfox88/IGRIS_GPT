"""Tests for GitHub READ gateway hardening (#1127).

Covers:
- Secret-path denylist blocks sensitive files
- Persistent audit (JSONL file on disk)
- Content redaction in normalized output
- Backward compatibility with existing tests
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from igris.core.authorization_gate import AuthResult, AuthorizationGate
from igris.core.github_read_gateway import (
    GitHubReadGateway,
    _is_secret_path,
)


def _make_gw(audit_dir: str = None) -> GitHubReadGateway:
    auth = MagicMock(spec=AuthorizationGate)
    auth.check.return_value = AuthResult(allowed=True, reason="ok")
    return GitHubReadGateway(
        auth_gate=auth,
        repo="owner/repo",
        audit_dir=audit_dir,
    )


# ---------------------------------------------------------------------------
# Secret-path denylist tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    ".env",
    ".env.local",
    ".env.production",
    "config/.env",
    "id_rsa",
    ".ssh/id_rsa",
    "id_ed25519",
    "private_key.pem",
    "credentials.json",
    "secrets.yaml",
    "service_account.json",
    "my_token.txt",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".git-credentials",
    ".docker/config.json",
    ".htpasswd",
    "deploy.key",
    "server.p12",
    "cert.pfx",
])
def test_secret_path_detected(path: str):
    assert _is_secret_path(path) is True, f"{path} should be blocked"


@pytest.mark.parametrize("path", [
    "README.md",
    "src/main.py",
    "tests/test_api.py",
    "package.json",
    "Dockerfile",
    "igris/core/safety.py",
    ".github/workflows/ci.yml",
    "docs/architecture.md",
    "config.sample.json",
])
def test_safe_path_allowed(path: str):
    assert _is_secret_path(path) is False, f"{path} should NOT be blocked"


def test_read_file_blocks_secret_path():
    """read_file raises PermissionError for secret paths."""
    gw = _make_gw()
    with pytest.raises(PermissionError, match="Secret-path read blocked"):
        gw.read_file(".env", branch="main", dry_run=True)


def test_read_file_blocks_env_local():
    gw = _make_gw()
    with pytest.raises(PermissionError, match="Secret-path read blocked"):
        gw.read_file("config/.env.local", branch="main", dry_run=True)


def test_read_file_blocks_id_rsa():
    gw = _make_gw()
    with pytest.raises(PermissionError, match="Secret-path read blocked"):
        gw.read_file(".ssh/id_rsa", branch="main", dry_run=True)


def test_read_file_allows_normal_files():
    """read_file allows non-secret paths in dry_run mode."""
    gw = _make_gw()
    result = gw.read_file("src/main.py", branch="main", dry_run=True)
    assert result["dry_run"] is True
    assert result["resource"] == "file"


def test_secret_path_audit_logs_blocked():
    """Blocked secret reads are logged in audit trail."""
    with tempfile.TemporaryDirectory() as td:
        gw = _make_gw(audit_dir=td)
        with pytest.raises(PermissionError):
            gw.read_file(".env", branch="main", dry_run=True, mission_id="m1")

        assert gw._audit_log
        last = gw._audit_log[-1]
        assert last["blocked"] is True
        assert last["blocked_reason"] == "secret_path_denied"
        assert last["mission_id"] == "m1"

        # Also persisted
        audit_file = Path(td) / "github_read_audit.jsonl"
        assert audit_file.exists()
        line = json.loads(audit_file.read_text().strip().split("\n")[-1])
        assert line["blocked"] is True


# ---------------------------------------------------------------------------
# Persistent audit tests
# ---------------------------------------------------------------------------

def test_persistent_audit_writes_jsonl():
    """With audit_dir, operations persist to JSONL file."""
    with tempfile.TemporaryDirectory() as td:
        gw = _make_gw(audit_dir=td)
        gw.read_issue(42, dry_run=True, mission_id="m1", run_id="r1")
        gw.read_pr(10, dry_run=True)

        audit_file = Path(td) / "github_read_audit.jsonl"
        assert audit_file.exists()
        lines = audit_file.read_text().strip().split("\n")
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["resource"] == "issue/42"
        assert first["mission_id"] == "m1"
        assert first["run_id"] == "r1"


def test_no_audit_dir_no_file_written():
    """Without audit_dir, no file written (backward compat)."""
    gw = _make_gw(audit_dir=None)
    gw.read_issue(42, dry_run=True)
    assert gw._audit_dir is None
    assert len(gw._audit_log) == 1


# ---------------------------------------------------------------------------
# Content redaction tests
# ---------------------------------------------------------------------------

def test_normalize_issue_redacts_body():
    """Issue body is passed through redact_secrets."""
    raw = {
        "number": 1, "title": "test", "state": "open",
        "body": "normal content",
        "labels": [], "assignees": [], "url": "u", "createdAt": "t", "updatedAt": "t",
    }
    result = GitHubReadGateway._normalize_issue(raw)
    assert result["body"] == "normal content"


def test_normalize_pr_redacts_body():
    """PR body is passed through redact_secrets."""
    raw = {
        "number": 1, "title": "test", "state": "open",
        "body": "normal content",
        "headRefName": "feature", "baseRefName": "main",
        "commits": [], "statusCheckRollup": [], "url": "u",
    }
    result = GitHubReadGateway._normalize_pr(raw)
    assert result["body"] == "normal content"


# ---------------------------------------------------------------------------
# Backward compatibility tests
# ---------------------------------------------------------------------------

def test_existing_gateway_init_signature():
    """Gateway works with old init signature (no audit_dir)."""
    auth = MagicMock(spec=AuthorizationGate)
    auth.check.return_value = AuthResult(allowed=True, reason="ok")
    gw = GitHubReadGateway(auth_gate=auth, repo=".")
    assert gw._audit_dir is None


def test_dry_run_read_issue():
    """Dry run read_issue returns expected shape."""
    gw = _make_gw()
    result = gw.read_issue(1, dry_run=True, mission_id="m1", run_id="r1")
    assert result["dry_run"] is True
    assert result["resource"] == "issue"


def test_audit_log_contains_mission_and_run():
    gw = _make_gw()
    gw.read_issue(5, dry_run=True, mission_id="mx", run_id="rx")
    assert gw._audit_log[-1]["mission_id"] == "mx"
    assert gw._audit_log[-1]["run_id"] == "rx"
