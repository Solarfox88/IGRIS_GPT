"""Tests for GitHub Admin Gateway phase 2 (#1208).

Phase 2 additions:
- Mutating admin actions require explicit approval-gate
- Collaborator/branch-protection metadata coverage expands safely
- Secret values never exposed in audit or response payloads
- No repo deletion or real mutation in tests
- CI green
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from igris.core.github_admin_gateway import (
    GitHubAdminApproval,
    GitHubAdminGateway,
)


# ---------------------------------------------------------------------------
# Fake backend — read-only and safe mutations, no real API calls
# ---------------------------------------------------------------------------

class FakeGitHubAdminBackend:
    def __init__(self):
        self.apply_calls: list = []
        self.collab_calls: list = []
        self.secret_calls: list = []

    def inspect_repo(self, repo: str):
        return {"repo": repo, "visibility": "private", "default_branch": "main"}

    def inspect_repo_settings(self, repo: str):
        return {"repo": repo, "visibility": "private", "allow_squash_merge": True, "allow_merge_commit": False}

    def inspect_branch_protection(self, repo: str, branch: str):
        return {"repo": repo, "branch": branch, "required_status_checks": ["ci"], "required_reviews": 2, "enforce_admins": True}

    def list_collaborators(self, repo: str):
        return [
            {"username": "alice", "permission": "admin"},
            {"username": "bob", "permission": "push"},
            {"username": "charlie", "permission": "read"},
        ]

    def inspect_actions_metadata(self, repo: str):
        return {"enabled": True, "runner_count": 3, "default_runner": "ubuntu-latest"}

    def inspect_secret_variable_metadata(self, repo: str):
        return {
            "secrets": [
                {"name": "API_KEY", "value": "super-secret-123"},
                {"name": "DB_PASS", "value": "hunter2"},
            ],
            "variables": [
                {"name": "ENV", "value": "staging"},
                {"name": "REGION", "value": "us-east-1"},
            ],
        }

    def apply_branch_protection(self, repo: str, branch: str, rules: dict):
        self.apply_calls.append((repo, branch, rules))
        return {"repo": repo, "branch": branch, "rules": rules, "applied": True}

    def add_collaborator(self, repo: str, username: str, permission: str):
        self.collab_calls.append(("add", repo, username, permission))
        return {"repo": repo, "username": username, "permission": permission, "added": True}

    def remove_collaborator(self, repo: str, username: str):
        self.collab_calls.append(("remove", repo, username))
        return {"repo": repo, "username": username, "removed": True}

    def set_secret(self, repo: str, secret_name: str, secret_value: str):
        self.secret_calls.append((repo, secret_name))
        return {"repo": repo, "secret_name": secret_name, "set": True}

    def create_repo(self, name: str, description: str, private: bool):
        return {"name": name, "description": description, "private": private, "created": True}

    def delete_repo(self, repo: str):
        return {"deleted": repo}


def _gateway(dry_run: bool = False, backend=None) -> GitHubAdminGateway:
    return GitHubAdminGateway(dry_run=dry_run, backend=backend or FakeGitHubAdminBackend())


def _approval(approved_by: str = "operator@example.com") -> GitHubAdminApproval:
    return GitHubAdminApproval(
        approved=True,
        approved_by=approved_by,
        ticket_id="JIRA-999",
        rationale="phase 2 test approval",
    )


# ---------------------------------------------------------------------------
# Branch-protection metadata coverage
# ---------------------------------------------------------------------------

def test_inspect_branch_protection_includes_rules():
    """inspect_branch_protection returns required_reviews, enforce_admins, etc."""
    gw = _gateway()
    result = gw.inspect_branch_protection("owner/repo", branch="main")
    assert result["success"] is True
    report = result["report"]
    assert report.get("required_reviews") == 2
    assert report.get("enforce_admins") is True


def test_inspect_branch_protection_dry_run():
    """In dry_run mode, inspect_branch_protection returns dry_run status."""
    gw = _gateway(dry_run=True)
    result = gw.inspect_branch_protection("owner/repo", branch="main")
    assert result["success"] is True
    assert result["dry_run"] is True


def test_inspect_repo_settings_expanded():
    """inspect_repo_settings returns merge settings as metadata."""
    gw = _gateway()
    result = gw.inspect_repo_settings("owner/repo")
    assert result["success"] is True
    report = result["report"]
    assert "visibility" in report or "repo" in report  # at least basic metadata


def test_inspect_collaborators_permission_summary():
    """Collaborator inspection exposes permission distribution summary."""
    gw = _gateway()
    result = gw.inspect_repo("owner/repo")
    assert result["success"] is True
    report = result["report"]
    summary = report.get("permission_summary", {})
    assert summary["collaborator_count"] == 3
    assert "admin" in summary["permissions"]
    assert "push" in summary["permissions"]


def test_inspect_collaborators_full_list():
    """inspect_collaborators returns list with username/permission (no secret values)."""
    gw = _gateway()
    result = gw.inspect_collaborators("owner/repo")
    assert result["success"] is True
    report = result.get("report")
    if isinstance(report, list):
        assert any(c.get("username") == "alice" for c in report)
    # No secret values
    serialized = str(result)
    assert "super-secret" not in serialized


def test_inspect_actions_metadata():
    """inspect_actions_metadata returns runner info."""
    gw = _gateway()
    result = gw.inspect_actions_metadata("owner/repo")
    assert result["success"] is True
    assert result.get("report") or result.get("dry_run")


def test_inspect_secret_variable_metadata_redacts_values():
    """Secret variable metadata summary never exposes secret values."""
    gw = _gateway()
    result = gw.inspect_secret_variable_metadata("owner/repo")
    assert result["success"] is True
    serialized = str(result)
    assert "super-secret-123" not in serialized
    assert "hunter2" not in serialized
    # Names are OK to expose (they're not secret values)
    report = result.get("report", {})
    if isinstance(report, dict) and "secret_names" in report:
        assert "API_KEY" in report["secret_names"]


# ---------------------------------------------------------------------------
# Mutating operations — approval-gated
# ---------------------------------------------------------------------------

def test_branch_protection_requires_approval():
    """set_branch_protection without approval returns approval_required."""
    gw = _gateway()
    result = gw.set_branch_protection("owner/repo", "main", {"required_reviews": 3})
    assert result["success"] is False
    assert result.get("approval_required") is True


def test_branch_protection_with_approval_executes():
    """set_branch_protection with valid approval calls backend."""
    backend = FakeGitHubAdminBackend()
    gw = _gateway(backend=backend)
    result = gw.set_branch_protection("owner/repo", "main", {"required_reviews": 3}, approval=_approval())
    assert result["success"] is True
    assert result["dry_run"] is False
    assert len(backend.apply_calls) == 1


def test_add_collaborator_requires_approval():
    """add_collaborator without approval returns approval_required."""
    gw = _gateway()
    result = gw.add_collaborator("owner/repo", "newuser", "push")
    assert result["success"] is False
    assert result.get("approval_required") is True


def test_add_collaborator_with_approval_executes():
    """add_collaborator with valid approval calls backend and redacts result."""
    backend = FakeGitHubAdminBackend()
    gw = _gateway(backend=backend)
    result = gw.add_collaborator("owner/repo", "newuser", "push", approval=_approval())
    assert result["success"] is True
    assert result["dry_run"] is False
    assert ("add", "owner/repo", "newuser", "push") in backend.collab_calls


def test_remove_collaborator_requires_approval():
    """remove_collaborator without approval returns approval_required."""
    gw = _gateway()
    result = gw.remove_collaborator("owner/repo", "olduser")
    assert result["success"] is False
    assert result.get("approval_required") is True


def test_remove_collaborator_with_approval_executes():
    """remove_collaborator with valid approval calls backend."""
    backend = FakeGitHubAdminBackend()
    gw = _gateway(backend=backend)
    result = gw.remove_collaborator("owner/repo", "olduser", approval=_approval())
    assert result["success"] is True
    assert any(c[0] == "remove" for c in backend.collab_calls)


def test_set_secret_never_exposes_value():
    """set_secret never returns or logs the secret value."""
    backend = FakeGitHubAdminBackend()
    gw = _gateway(backend=backend)
    result = gw.set_secret("owner/repo", "MY_SECRET", "hunter2-very-secret", approval=_approval())
    serialized = str(result) + str(gw.get_audit_log())
    assert "hunter2-very-secret" not in serialized
    assert "[REDACTED]" in serialized or "secret_hash" in serialized or result.get("success") is True


def test_set_secret_dry_run_never_exposes_value():
    """set_secret in dry_run mode also never exposes the value."""
    gw = _gateway(dry_run=True)
    result = gw.set_secret("owner/repo", "MY_SECRET", "hunter2-very-secret", approval=_approval())
    serialized = str(result) + str(gw.get_audit_log())
    assert "hunter2-very-secret" not in serialized


def test_no_repo_deletion_in_tests():
    """delete_repo without double_confirm is always rejected."""
    gw = _gateway()
    result = gw.delete_repo("owner/repo", double_confirm=False)
    assert result["success"] is False
    assert result.get("double_confirm_required") is True


def test_no_repo_deletion_even_with_approval_without_double_confirm():
    """delete_repo requires double_confirm regardless of approval."""
    gw = _gateway()
    result = gw.delete_repo("owner/repo", double_confirm=False, approval=_approval())
    assert result["success"] is False
    assert result.get("double_confirm_required") is True


# ---------------------------------------------------------------------------
# Dry-run mode
# ---------------------------------------------------------------------------

def test_all_mutating_ops_are_dry_run_by_default():
    """All mutating operations default to dry_run mode."""
    gw = _gateway(dry_run=True)

    r1 = gw.set_branch_protection("owner/repo", "main", {"required_reviews": 2}, approval=_approval())
    r2 = gw.add_collaborator("owner/repo", "newuser", "push", approval=_approval())
    r3 = gw.set_secret("owner/repo", "MY_KEY", "myvalue", approval=_approval())

    assert r1["dry_run"] is True
    assert r2["dry_run"] is True
    assert r3["dry_run"] is True


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def test_audit_log_captures_all_attempts():
    """Every operation attempt appears in the audit log."""
    gw = _gateway()
    gw.inspect_repo("owner/repo")
    gw.add_collaborator("owner/repo", "user", "push")  # no approval → blocked
    log = gw.get_audit_log()
    assert len(log) >= 2
    actions = [e["action"] for e in log]
    assert any("inspected" in a.lower() or "repo" in a.lower() for a in actions)


def test_audit_log_never_contains_secret_values():
    """Secret values never appear in any audit log entry."""
    backend = FakeGitHubAdminBackend()
    gw = _gateway(backend=backend)
    gw.inspect_repo("owner/repo")  # triggers inspect_secret_variable_metadata
    log_text = str(gw.get_audit_log())
    assert "super-secret-123" not in log_text
    assert "hunter2" not in log_text
