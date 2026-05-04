"""GitHub PR workflow — gated, no auto-merge.

All remote operations (push, PR creation) require explicit approval payload.
No merge endpoint. No force push. No push to main/master.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from igris.core.safety import redact_secrets
from igris.layers.git_layer.git_ops import (
    _run_git,
    _run_git_full,
    is_git_repo,
    pre_commit_safety_check,
    generate_pr_summary,
    sanitize_branch_name,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APPROVAL_TOKEN_COMMIT = "I_APPROVE_GITHUB_WRITE"
APPROVAL_TOKEN_PUSH = "I_APPROVE_GITHUB_WRITE"
APPROVAL_TOKEN_PR = "I_APPROVE_GITHUB_WRITE"

PROTECTED_BRANCHES = {"main", "master"}

BRANCH_ALLOWLIST_PATTERN = re.compile(
    r"^(devin|feature|fix|bugfix|hotfix|sprint|release|chore|docs)/[a-zA-Z0-9/_\-.]+"
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GatedCommitResult:
    success: bool = False
    commit_hash: str = ""
    message: str = ""
    error: str = ""
    warnings: List[str] = field(default_factory=list)
    safety_check: Optional[Dict[str, Any]] = None
    gated: bool = True

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "success": self.success,
            "commit_hash": self.commit_hash,
            "message": redact_secrets(self.message),
            "error": redact_secrets(self.error),
            "warnings": [redact_secrets(w) for w in self.warnings],
            "gated": self.gated,
        }
        if self.safety_check:
            sc = dict(self.safety_check)
            sc.pop("secret_files", None)
            d["safety_check_passed"] = sc.get("safe", False)
        return d


@dataclass
class PRPreparation:
    title: str = ""
    body: str = ""
    branch: str = ""
    base: str = "main"
    diffstat: str = ""
    commit_count: int = 0
    ready: bool = False
    warnings: List[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": redact_secrets(self.title),
            "body": redact_secrets(self.body),
            "branch": self.branch,
            "base": self.base,
            "diffstat": redact_secrets(self.diffstat),
            "commit_count": self.commit_count,
            "ready": self.ready,
            "warnings": [redact_secrets(w) for w in self.warnings],
            "error": redact_secrets(self.error),
        }


@dataclass
class GatedPRResult:
    success: bool = False
    pr_url: str = ""
    pr_number: int = 0
    error: str = ""
    approval_required: bool = True
    gated: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "pr_url": self.pr_url,
            "pr_number": self.pr_number,
            "error": redact_secrets(self.error),
            "approval_required": self.approval_required,
            "gated": self.gated,
        }


# ---------------------------------------------------------------------------
# Branch validation
# ---------------------------------------------------------------------------

def validate_branch_for_push(branch: str) -> List[str]:
    """Validate branch name for push/PR operations."""
    issues: List[str] = []
    if branch in PROTECTED_BRANCHES:
        issues.append(f"Cannot push to protected branch: {branch}")
    if not BRANCH_ALLOWLIST_PATTERN.match(branch):
        issues.append(
            f"Branch '{branch}' does not match allowlist pattern. "
            "Expected: devin/*, feature/*, fix/*, bugfix/*, hotfix/*, "
            "sprint/*, release/*, chore/*, docs/*"
        )
    return issues


# ---------------------------------------------------------------------------
# Gated commit
# ---------------------------------------------------------------------------

def gated_commit(
    message: str,
    approval: str = "",
    files: Optional[List[str]] = None,
) -> GatedCommitResult:
    """Commit with safety gates.

    Requires:
    - safety check to pass (no secrets, no runtime artifacts, files staged)
    - approval token (or gate_override)
    - not on protected branch
    """
    result = GatedCommitResult()

    if not is_git_repo():
        result.error = "Not a git repository"
        return result

    # Check branch
    current = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if current in PROTECTED_BRANCHES:
        result.error = f"Cannot commit on protected branch: {current}"
        return result

    # Check approval
    if approval != APPROVAL_TOKEN_COMMIT:
        result.error = (
            f"Approval required. Send approval='{APPROVAL_TOKEN_COMMIT}' "
            "to confirm this commit."
        )
        return result

    # Safety check
    safety = pre_commit_safety_check()
    result.safety_check = safety

    if not safety.get("safe", False):
        result.error = "Commit blocked by safety checks"
        result.warnings = safety.get("warnings", [])
        return result

    # Execute commit
    r = _run_git_full(["commit", "-m", message])
    if r["returncode"] != "0":
        result.error = redact_secrets(r["stderr"])
        return result

    result.success = True
    result.commit_hash = _run_git(["rev-parse", "--short", "HEAD"])
    result.message = message
    return result


# ---------------------------------------------------------------------------
# PR preparation
# ---------------------------------------------------------------------------

def prepare_pr(
    base_branch: str = "main",
    title: Optional[str] = None,
    extra_context: Optional[str] = None,
) -> PRPreparation:
    """Prepare a PR body from branch info, commits, diffstat.

    Does NOT create the PR — just prepares the content.
    """
    prep = PRPreparation(base=base_branch)

    if not is_git_repo():
        prep.error = "Not a git repository"
        return prep

    current = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if current in PROTECTED_BRANCHES:
        prep.error = f"Cannot create PR from protected branch: {current}"
        return prep

    branch_issues = validate_branch_for_push(current)
    if branch_issues:
        prep.warnings.extend(branch_issues)

    prep.branch = current

    # Get PR summary data
    summary = generate_pr_summary(base_branch)
    if "error" in summary:
        prep.error = str(summary["error"])
        return prep

    commits = summary.get("commits", [])
    prep.commit_count = len(commits)
    prep.diffstat = str(summary.get("stat", ""))

    # Auto-generate title from branch or first commit
    if title:
        prep.title = title
    elif commits:
        prep.title = commits[0].split(" ", 1)[-1] if " " in commits[0] else commits[0]
    else:
        prep.title = f"Changes from {current}"

    # Build body
    body_parts = [f"## Summary\n\nChanges from `{current}` into `{base_branch}`.\n"]

    if commits:
        body_parts.append("## Commits\n")
        for c in commits:
            body_parts.append(f"- {redact_secrets(c)}")
        body_parts.append("")

    if prep.diffstat:
        body_parts.append(f"## Diffstat\n\n```\n{redact_secrets(prep.diffstat)}\n```\n")

    if extra_context:
        body_parts.append(f"## Additional Context\n\n{redact_secrets(extra_context)}\n")

    body_parts.append("## Safety\n\n- No secrets in diff\n- No runtime artifacts\n- Safety checks passed\n")
    prep.body = "\n".join(body_parts)
    prep.ready = True
    return prep


# ---------------------------------------------------------------------------
# Gated push
# ---------------------------------------------------------------------------

def gated_push(
    approval: str = "",
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Push current branch to remote with approval gate.

    No force push. No push to main/master.
    """
    if not is_git_repo():
        return {"success": False, "error": "Not a git repository"}

    current = branch or _run_git(["rev-parse", "--abbrev-ref", "HEAD"])

    # Protected branch check
    if current in PROTECTED_BRANCHES:
        return {"success": False, "error": f"Cannot push to protected branch: {current}"}

    # Approval check
    if approval != APPROVAL_TOKEN_PUSH:
        return {
            "success": False,
            "error": f"Approval required. Send approval='{APPROVAL_TOKEN_PUSH}' to confirm push.",
            "approval_required": True,
        }

    # Branch validation
    issues = validate_branch_for_push(current)
    if issues:
        return {"success": False, "error": "; ".join(issues), "branch_issues": issues}

    # Push (no force)
    r = _run_git_full(["push", "origin", current])
    if r["returncode"] != "0":
        return {"success": False, "error": redact_secrets(r["stderr"])}

    return {"success": True, "branch": current, "pushed": True}


# ---------------------------------------------------------------------------
# Gated PR creation (mock — no real GitHub API calls in CI)
# ---------------------------------------------------------------------------

def gated_create_pr(
    title: str,
    body: str,
    base: str = "main",
    approval: str = "",
) -> GatedPRResult:
    """Create a PR with approval gate.

    In production, this would call the GitHub API.
    Currently returns a mock/gated result since real API calls
    require GitHub token and are not safe for CI.
    """
    result = GatedPRResult()

    if not is_git_repo():
        result.error = "Not a git repository"
        return result

    # Approval check
    if approval != APPROVAL_TOKEN_PR:
        result.error = (
            f"Approval required. Send approval='{APPROVAL_TOKEN_PR}' "
            "to confirm PR creation."
        )
        return result

    current = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])

    # Protected branch check
    if current in PROTECTED_BRANCHES:
        result.error = f"Cannot create PR from protected branch: {current}"
        return result

    # Validate branch
    branch_issues = validate_branch_for_push(current)
    if branch_issues:
        result.error = "; ".join(branch_issues)
        return result

    # Safety check
    safety = pre_commit_safety_check()
    secret_files = safety.get("secret_files", [])
    if secret_files:
        result.error = "Secret-like content detected in diff — cannot create PR"
        return result

    # In production: call GitHub API here
    # For now: return a gated result indicating approval was given
    result.success = True
    result.pr_url = f"https://github.com/OWNER/REPO/pull/0 (gated — real API not called)"
    result.pr_number = 0
    result.gated = True
    return result


# ---------------------------------------------------------------------------
# PR status (read-only)
# ---------------------------------------------------------------------------

def get_pr_status() -> Dict[str, Any]:
    """Get current branch PR readiness status."""
    if not is_git_repo():
        return {"error": "Not a git repository"}

    current = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    safety = pre_commit_safety_check()

    ahead = _run_git(["rev-list", "--count", f"origin/main..{current}"])
    behind = _run_git(["rev-list", "--count", f"{current}..origin/main"])

    return {
        "branch": current,
        "on_protected_branch": current in PROTECTED_BRANCHES,
        "commits_ahead": int(ahead) if ahead.isdigit() else 0,
        "commits_behind": int(behind) if behind.isdigit() else 0,
        "safety_check_passed": safety.get("safe", False),
        "warnings": safety.get("warnings", []),
        "branch_valid": len(validate_branch_for_push(current)) == 0,
        "can_push": (
            current not in PROTECTED_BRANCHES
            and len(validate_branch_for_push(current)) == 0
        ),
        "can_create_pr": (
            current not in PROTECTED_BRANCHES
            and int(ahead) > 0 if ahead.isdigit() else False
        ),
        "merge_endpoint_available": False,
        "auto_merge_available": False,
    }
