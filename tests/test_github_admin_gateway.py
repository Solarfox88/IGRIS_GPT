"""Tests for the GitHub admin gateway baseline (#949)."""

import pytest

from igris.core.github_admin_gateway import GitHubAdminApproval, GitHubAdminGateway


class FakeGitHubAdminBackend:
    def inspect_repo(self, repo: str):
        return {
            "repo": repo,
            "settings": {"visibility": "private", "default_branch": "main"},
            "branch_protection": {"main": {"required_reviews": 2}},
            "collaborators": [{"username": "alice", "permission": "push"}],
            "actions_metadata": {"enabled": True, "runner_count": 2},
            "secrets_variables_metadata": {
                "secrets": [{"name": "API_KEY", "value": "super-secret"}],
                "variables": [{"name": "ENV", "value": "staging"}],
            },
        }

    def inspect_repo_settings(self, repo: str):
        return {"repo": repo, "visibility": "private", "default_branch": "main"}

    def inspect_branch_protection(self, repo: str, branch: str):
        return {"repo": repo, "branch": branch, "required_reviews": 2}

    def list_collaborators(self, repo: str):
        return [{"username": "alice", "permission": "push"}]

    def inspect_actions_metadata(self, repo: str):
        return {"enabled": True, "runner_count": 2}

    def inspect_secret_variable_metadata(self, repo: str):
        return {
            "secrets": [{"name": "API_KEY", "value": "super-secret"}],
            "variables": [{"name": "ENV", "value": "staging"}],
        }

    def apply_branch_protection(self, repo: str, branch: str, rules: dict):
        return {"repo": repo, "branch": branch, "rules": rules}

    def add_collaborator(self, repo: str, username: str, permission: str):
        return {"repo": repo, "username": username, "permission": permission}

    def remove_collaborator(self, repo: str, username: str):
        return {"repo": repo, "username": username}

    def set_secret(self, repo: str, secret_name: str, secret_value: str):
        return {"repo": repo, "secret_name": secret_name, "secret_value": secret_value}

    def create_repo(self, name: str, description: str, private: bool):
        return {"name": name, "description": description, "private": private}

    def delete_repo(self, repo: str):
        return {"deleted": repo}


def test_inspect_repo_redacts_secret_values():
    gateway = GitHubAdminGateway(dry_run=False, backend=FakeGitHubAdminBackend())
    report = gateway.inspect_repo("owner/repo")
    assert report["success"] is True
    payload = report["report"]
    assert payload["repo_settings"]["visibility"] == "private"
    assert payload["branch_protection"]["required_reviews"] == 2
    assert payload["collaborators"][0]["username"] == "alice"
    serialized = str(payload)
    assert "super-secret" not in serialized
    assert "staging" not in serialized
    assert gateway.get_audit_log()


def test_branch_protection_proposal_is_dry_run():
    gateway = GitHubAdminGateway(dry_run=True, backend=FakeGitHubAdminBackend())
    proposal = gateway.propose_branch_protection_change(
        "owner/repo",
        "main",
        {"required_reviews": 2, "dismiss_stale_reviews": True},
    )
    assert proposal["success"] is True
    assert proposal["dry_run"] is True
    assert proposal["proposal"]["approval_required"] is True
    assert gateway.get_audit_log()


def test_mutation_blocked_without_approval():
    gateway = GitHubAdminGateway(dry_run=False, backend=FakeGitHubAdminBackend())
    result = gateway.add_collaborator("owner/repo", "alice", "push")
    assert result["success"] is False
    assert result["approval_required"] is True
    assert gateway.get_audit_log()[-1]["status"] == "DENIED_APPROVAL"


def test_mutation_allowed_with_explicit_approval_and_backend_redaction():
    gateway = GitHubAdminGateway(dry_run=False, backend=FakeGitHubAdminBackend())
    approval = GitHubAdminApproval(approved=True, approved_by="operator", ticket_id="T-1")
    result = gateway.set_secret("owner/repo", "API_KEY", "super-secret", approval=approval)
    assert result["success"] is True
    assert result["dry_run"] is False
    assert "super-secret" not in str(result)
    audit = gateway.get_audit_log()[-1]
    assert audit["status"] == "EXECUTED"
    assert "super-secret" not in str(audit)
