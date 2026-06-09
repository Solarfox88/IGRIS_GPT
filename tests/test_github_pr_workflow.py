"""Tests for Sprint 21 — GitHub PR Workflow Gated, No Auto-Merge.

Verifies:
- Gated commit requires approval + safety check
- Push to main/master blocked
- PR create requires approval
- No auto-merge endpoint
- No force push
- Secrets never in responses
- Branch validation
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from igris.layers.git_layer import github_workflow as gh_wf
from igris.web.server import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo for testing."""
    repo = tmp_path / "test_repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(repo), check=True, capture_output=True,
    )
    # Create initial commit on main
    (repo / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), check=True, capture_output=True)
    # Create feature branch
    subprocess.run(
        ["git", "checkout", "-b", "devin/test-feature"],
        cwd=str(repo), check=True, capture_output=True,
    )
    return repo


@pytest.fixture
def client():
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Branch validation
# ---------------------------------------------------------------------------


class TestBranchValidation:
    """Branch validation rules."""

    def test_main_blocked(self):
        issues = gh_wf.validate_branch_for_push("main")
        assert len(issues) > 0
        assert any("protected" in i.lower() for i in issues)

    def test_master_blocked(self):
        issues = gh_wf.validate_branch_for_push("master")
        assert len(issues) > 0

    def test_devin_branch_allowed(self):
        issues = gh_wf.validate_branch_for_push("devin/test-feature")
        assert len(issues) == 0

    def test_feature_branch_allowed(self):
        issues = gh_wf.validate_branch_for_push("feature/new-thing")
        assert len(issues) == 0

    def test_fix_branch_allowed(self):
        issues = gh_wf.validate_branch_for_push("fix/bug-123")
        assert len(issues) == 0

    def test_random_branch_rejected(self):
        issues = gh_wf.validate_branch_for_push("my-random-branch")
        assert len(issues) > 0
        assert any("allowlist" in i.lower() for i in issues)


# ---------------------------------------------------------------------------
# Gated commit
# ---------------------------------------------------------------------------


class TestGatedCommit:
    """Commit is gated by safety check + approval."""

    def test_commit_without_approval_rejected(self, git_repo):
        with patch.dict(os.environ, {"PROJECT_ROOT": str(git_repo)}):
            result = gh_wf.gated_commit(message="test", approval="")
            assert result.success is False
            assert "approval" in result.error.lower()

    def test_commit_wrong_approval_rejected(self, git_repo):
        with patch.dict(os.environ, {"PROJECT_ROOT": str(git_repo)}):
            result = gh_wf.gated_commit(message="test", approval="WRONG")
            assert result.success is False
            assert "approval" in result.error.lower()

    def test_commit_on_main_rejected(self, git_repo):
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=str(git_repo), check=True, capture_output=True,
        )
        with patch.dict(os.environ, {"PROJECT_ROOT": str(git_repo)}):
            result = gh_wf.gated_commit(
                message="test",
                approval=gh_wf.APPROVAL_TOKEN_COMMIT,
            )
            assert result.success is False
            assert "protected" in result.error.lower()

    def test_commit_with_approval_and_staged_files(self, git_repo):
        (git_repo / "new_file.txt").write_text("hello")
        subprocess.run(
            ["git", "add", "new_file.txt"],
            cwd=str(git_repo), check=True, capture_output=True,
        )
        with patch.dict(os.environ, {"PROJECT_ROOT": str(git_repo)}):
            result = gh_wf.gated_commit(
                message="feat: add new file",
                approval=gh_wf.APPROVAL_TOKEN_COMMIT,
            )
            assert result.success is True
            assert result.commit_hash

    def test_commit_no_staged_files_rejected(self, git_repo):
        with patch.dict(os.environ, {"PROJECT_ROOT": str(git_repo)}):
            result = gh_wf.gated_commit(
                message="empty commit",
                approval=gh_wf.APPROVAL_TOKEN_COMMIT,
            )
            assert result.success is False

    def test_commit_secret_file_rejected(self, git_repo):
        (git_repo / "config.py").write_text(
            'API_KEY = "sk-abcdefghijklmnopqrstuvwxyz12345678"\n'
        )
        subprocess.run(
            ["git", "add", "config.py"],
            cwd=str(git_repo), check=True, capture_output=True,
        )
        with patch.dict(os.environ, {"PROJECT_ROOT": str(git_repo)}):
            result = gh_wf.gated_commit(
                message="bad commit",
                approval=gh_wf.APPROVAL_TOKEN_COMMIT,
            )
            assert result.success is False

    def test_commit_result_no_secrets(self, git_repo):
        result = gh_wf.GatedCommitResult(
            error="key is sk-abcdefghijklmnopqrstuvwxyz",
        )
        d = result.to_dict()
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in d["error"]


# ---------------------------------------------------------------------------
# PR preparation
# ---------------------------------------------------------------------------


class TestPRPreparation:
    """PR body generation from branch info."""

    def test_prepare_pr_on_feature_branch(self, git_repo):
        (git_repo / "feature.py").write_text("print('hello')\n")
        subprocess.run(
            ["git", "add", "feature.py"],
            cwd=str(git_repo), check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "feat: add feature"],
            cwd=str(git_repo), check=True, capture_output=True,
        )
        with patch.dict(os.environ, {"PROJECT_ROOT": str(git_repo)}):
            prep = gh_wf.prepare_pr(base_branch="main", title="Test PR")
            assert prep.title == "Test PR"
            assert prep.branch == "devin/test-feature"
            assert prep.commit_count >= 1
            assert prep.ready is True

    def test_prepare_pr_on_main_rejected(self, git_repo):
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=str(git_repo), check=True, capture_output=True,
        )
        with patch.dict(os.environ, {"PROJECT_ROOT": str(git_repo)}):
            prep = gh_wf.prepare_pr()
            assert prep.ready is False
            assert "protected" in prep.error.lower()

    def test_prepare_pr_no_secrets_in_body(self, git_repo):
        (git_repo / "safe.txt").write_text("data\n")
        subprocess.run(
            ["git", "add", "safe.txt"],
            cwd=str(git_repo), check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "safe commit"],
            cwd=str(git_repo), check=True, capture_output=True,
        )
        with patch.dict(os.environ, {"PROJECT_ROOT": str(git_repo)}):
            prep = gh_wf.prepare_pr()
            d = prep.to_dict()
            assert "sk-" not in d["body"]
            assert "ghp_" not in d["body"]


# ---------------------------------------------------------------------------
# Gated PR creation
# ---------------------------------------------------------------------------


class TestGatedPRCreate:
    """PR creation requires approval."""

    def test_pr_create_without_approval_rejected(self, git_repo):
        with patch.dict(os.environ, {"PROJECT_ROOT": str(git_repo)}):
            result = gh_wf.gated_create_pr(
                title="Test PR", body="body", approval="",
            )
            assert result.success is False
            assert "approval" in result.error.lower()

    def test_pr_create_with_approval(self, git_repo):
        with patch.dict(os.environ, {"PROJECT_ROOT": str(git_repo)}):
            result = gh_wf.gated_create_pr(
                title="Test PR",
                body="body",
                approval=gh_wf.APPROVAL_TOKEN_PR,
            )
            assert result.success is True
            assert result.gated is True

    def test_pr_create_from_main_rejected(self, git_repo):
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=str(git_repo), check=True, capture_output=True,
        )
        with patch.dict(os.environ, {"PROJECT_ROOT": str(git_repo)}):
            result = gh_wf.gated_create_pr(
                title="Test",
                body="body",
                approval=gh_wf.APPROVAL_TOKEN_PR,
            )
            assert result.success is False
            assert "protected" in result.error.lower()

    def test_pr_result_no_secrets(self):
        result = gh_wf.GatedPRResult(
            error="token ghp_abcdefghijklmnopqrstuvwxyz1234567890",
        )
        d = result.to_dict()
        assert "ghp_abcdefghijklmnopqrstuvwxyz" not in d["error"]


# ---------------------------------------------------------------------------
# PR status
# ---------------------------------------------------------------------------


class TestPRStatus:
    """PR readiness status."""

    def test_status_on_feature_branch(self, git_repo):
        with patch.dict(os.environ, {"PROJECT_ROOT": str(git_repo)}):
            status = gh_wf.get_pr_status()
            assert status["branch"] == "devin/test-feature"
            assert status["on_protected_branch"] is False
            assert status["merge_endpoint_available"] is False
            assert status["auto_merge_available"] is False

    def test_status_no_merge_available(self, git_repo):
        with patch.dict(os.environ, {"PROJECT_ROOT": str(git_repo)}):
            status = gh_wf.get_pr_status()
            assert status["merge_endpoint_available"] is False
            assert status["auto_merge_available"] is False


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


class TestAPIEndpoints:
    """HTTP endpoint tests."""

    def test_commit_endpoint_no_message(self, client):
        r = client.post("/api/git/commit", json={})
        assert r.status_code == 400

    def test_commit_endpoint_no_approval(self, client):
        r = client.post("/api/git/commit", json={"message": "test"})
        data = r.json()
        assert data["success"] is False

    def test_pr_prepare_endpoint(self, client):
        r = client.post("/api/github/pr/prepare", json={"base": "main"})
        assert r.status_code == 200
        data = r.json()
        assert "title" in data
        assert "body" in data

    def test_pr_create_endpoint_no_title(self, client):
        r = client.post("/api/github/pr/create", json={})
        # Auth gate (#1293): no token → 401 before title validation → 400
        assert r.status_code in (400, 401, 403), f"Unexpected: {r.status_code}"

    def test_pr_create_endpoint_no_approval(self, client):
        r = client.post(
            "/api/github/pr/create",
            json={"title": "Test PR"},
        )
        # Auth gate (#1293): no token → 401 before approval validation
        if r.status_code in (401, 403):
            return  # correctly blocked by auth gate
        data = r.json()
        assert data["success"] is False
        # Either approval required or not a git repo (depends on env)
        err = data.get("error", "").lower()
        assert "approval" in err or "git" in err

    def test_pr_status_endpoint(self, client):
        r = client.get("/api/github/pr/status")
        assert r.status_code == 200
        data = r.json()
        if "error" not in data:  # running in a real git repo
            assert "merge_endpoint_available" in data
            assert data["merge_endpoint_available"] is False
            assert data["auto_merge_available"] is False
        else:
            assert "git" in data["error"].lower()

    def test_no_merge_endpoint(self, client):
        r = client.post("/api/git/merge", json={})
        assert r.status_code == 404 or r.status_code == 405

    def test_no_force_push_endpoint(self, client):
        r = client.post("/api/git/force-push", json={})
        assert r.status_code == 404 or r.status_code == 405

    def test_no_auto_merge_endpoint(self, client):
        r = client.post("/api/github/pr/merge", json={})
        assert r.status_code == 404 or r.status_code == 405


# ---------------------------------------------------------------------------
# Gated push
# ---------------------------------------------------------------------------


class TestGatedPush:
    """Push requires approval and branch validation."""

    def test_push_without_approval(self, git_repo):
        with patch.dict(os.environ, {"PROJECT_ROOT": str(git_repo)}):
            result = gh_wf.gated_push(approval="")
            assert result["success"] is False
            assert "approval" in result.get("error", "").lower()

    def test_push_to_main_blocked(self, git_repo):
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=str(git_repo), check=True, capture_output=True,
        )
        with patch.dict(os.environ, {"PROJECT_ROOT": str(git_repo)}):
            result = gh_wf.gated_push(
                approval=gh_wf.APPROVAL_TOKEN_PUSH,
            )
            assert result["success"] is False
            assert "protected" in result.get("error", "").lower()


# ---------------------------------------------------------------------------
# Safety cross-checks
# ---------------------------------------------------------------------------


class TestSafetyCrossChecks:
    """Cross-cutting safety verifications."""

    def test_approval_tokens_consistent(self):
        assert gh_wf.APPROVAL_TOKEN_COMMIT == "I_APPROVE_GITHUB_WRITE"
        assert gh_wf.APPROVAL_TOKEN_PUSH == "I_APPROVE_GITHUB_WRITE"
        assert gh_wf.APPROVAL_TOKEN_PR == "I_APPROVE_GITHUB_WRITE"

    def test_protected_branches(self):
        assert "main" in gh_wf.PROTECTED_BRANCHES
        assert "master" in gh_wf.PROTECTED_BRANCHES

    def test_no_secrets_in_pr_preparation(self):
        prep = gh_wf.PRPreparation(
            body="key is sk-abcdefghijklmnopqrstuvwxyz1234",
        )
        d = prep.to_dict()
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in d["body"]

    def test_git_status_clean(self, client):
        """No unexpected files in git status."""
        import subprocess
        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, check=False,
        )
        for line in result.stdout.splitlines():
            path = line[3:].strip()
            assert not path.endswith(".env"), f"Found .env file: {path}"
            assert "secret" not in path.lower() or "test" in path.lower()
