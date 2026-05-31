"""GitHub backend abstraction — PR 1 DeliveryWorkflow hardening.

Provides a testable interface for all GitHub/gh CLI operations used
by DeliveryWorkflow and CIRepairLoop.

Classes:
    GitHubBackend       — abstract base
    SubprocessGitHubBackend — real implementation using gh CLI + git
    FakeGitHubBackend   — in-memory fake for unit tests

Usage:
    # Production
    backend = SubprocessGitHubBackend(project_root="/path/to/repo")

    # Tests
    backend = FakeGitHubBackend()
    backend.set_ci_result("green")
    backend.set_pr_log("FAILED tests/test_foo.py::test_bar")
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_log = logging.getLogger("igris.github_backend")


# ---------------------------------------------------------------------------
# Data classes returned by backend methods
# ---------------------------------------------------------------------------

@dataclass
class PRCheckResult:
    """Status of all checks for a PR."""
    status: str          # green | red | pending | unknown
    failed_jobs: List[str] = field(default_factory=list)
    pending_jobs: List[str] = field(default_factory=list)
    succeeded_jobs: List[str] = field(default_factory=list)


@dataclass
class PRInfo:
    """Basic PR metadata."""
    pr_number: int
    title: str = ""
    state: str = ""          # open | closed | merged
    is_draft: bool = False
    head_sha: str = ""
    base: str = "main"
    branch: str = ""


@dataclass
class CommitResult:
    """Result of a commit + push operation."""
    committed: bool
    pushed: bool
    sha: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class GitHubBackend(ABC):
    """Abstract interface for GitHub operations.

    All methods return typed dataclasses so callers are decoupled from
    subprocess/gh details.  The FakeGitHubBackend implements the same
    interface for tests.
    """

    @abstractmethod
    def list_pr_checks(self, pr_number: int) -> PRCheckResult:
        """Return CI check status for a PR."""

    @abstractmethod
    def fetch_failed_logs(self, pr_number: int, max_chars: int = 6000) -> str:
        """Fetch the failure logs for the most recent failed run on a PR."""

    @abstractmethod
    def commit_changes(self, message: str, files: Optional[List[str]] = None) -> CommitResult:
        """Stage *files* (or all modified if None) and commit."""

    @abstractmethod
    def push_branch(self) -> bool:
        """Push the current branch to origin."""

    @abstractmethod
    def create_pr(
        self,
        title: str,
        body: str,
        branch: str,
        base: str = "main",
        draft: bool = False,
    ) -> int:
        """Create a PR and return its number (0 on failure)."""

    @abstractmethod
    def merge_pr(self, pr_number: int, method: str = "squash") -> bool:
        """Merge a PR. Returns True on success."""

    @abstractmethod
    def fetch_changed_files(self, branch: str, base: str = "main") -> List[str]:
        """Return list of files changed relative to base."""

    @abstractmethod
    def get_pr_info(self, pr_number: int) -> Optional[PRInfo]:
        """Return PR metadata or None if not found."""

    @abstractmethod
    def delete_branch(self, branch: str, remote: bool = True) -> bool:
        """Delete a branch (local and/or remote)."""


# ---------------------------------------------------------------------------
# Real subprocess implementation
# ---------------------------------------------------------------------------

class SubprocessGitHubBackend(GitHubBackend):
    """Real GitHub backend using gh CLI + git subprocess calls."""

    def __init__(self, project_root: str) -> None:
        self.project_root = project_root

    def _run(self, cmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd, cwd=self.project_root,
            capture_output=True, text=True, timeout=timeout,
        )

    def list_pr_checks(self, pr_number: int) -> PRCheckResult:
        try:
            r = self._run(
                ["gh", "pr", "checks", str(pr_number),
                 "--json", "name,status,conclusion"],
            )
            if r.returncode != 0:
                return PRCheckResult(status="unknown")
            checks = json.loads(r.stdout or "[]")
            if not checks:
                return PRCheckResult(status="pending")
            pending = [c["name"] for c in checks if c.get("status") != "completed"]
            if pending:
                return PRCheckResult(status="pending", pending_jobs=pending)
            failed = [
                c["name"] for c in checks
                if c.get("conclusion") not in ("success", "skipped", "neutral")
            ]
            succeeded = [
                c["name"] for c in checks
                if c.get("conclusion") in ("success", "skipped", "neutral")
            ]
            if failed:
                return PRCheckResult(status="red", failed_jobs=failed, succeeded_jobs=succeeded)
            return PRCheckResult(status="green", succeeded_jobs=succeeded)
        except Exception as exc:
            _log.warning("list_pr_checks(%d): %s", pr_number, exc)
            return PRCheckResult(status="unknown")

    def fetch_failed_logs(self, pr_number: int, max_chars: int = 6000) -> str:
        try:
            r = self._run(
                ["gh", "run", "list", "--json", "databaseId,conclusion",
                 "--pr", str(pr_number), "--limit", "1"],
            )
            if r.returncode != 0:
                return ""
            runs = json.loads(r.stdout or "[]")
            if not runs:
                return ""
            run_id = runs[0].get("databaseId")
            if not run_id:
                return ""
            log_r = self._run(
                ["gh", "run", "view", str(run_id), "--log-failed"],
                timeout=60,
            )
            text = (log_r.stdout or "") + (log_r.stderr or "")
            return text[:max_chars]
        except Exception as exc:
            _log.warning("fetch_failed_logs(%d): %s", pr_number, exc)
            return ""

    def commit_changes(self, message: str, files: Optional[List[str]] = None) -> CommitResult:
        try:
            if files:
                for f in files:
                    self._run(["git", "add", f])
            else:
                self._run(["git", "add", "-u"])
            r = self._run(["git", "commit", "-m", message])
            if r.returncode != 0:
                return CommitResult(committed=False, pushed=False, error=r.stderr[:300])
            sha_r = self._run(["git", "rev-parse", "HEAD"])
            sha = sha_r.stdout.strip() if sha_r.returncode == 0 else ""
            return CommitResult(committed=True, pushed=False, sha=sha)
        except Exception as exc:
            return CommitResult(committed=False, pushed=False, error=str(exc)[:200])

    def push_branch(self) -> bool:
        try:
            r = self._run(["git", "push"], timeout=60)
            return r.returncode == 0
        except Exception as exc:
            _log.warning("push_branch: %s", exc)
            return False

    def create_pr(
        self,
        title: str,
        body: str,
        branch: str,
        base: str = "main",
        draft: bool = False,
    ) -> int:
        cmd = ["gh", "pr", "create", "--title", title, "--body", body,
               "--head", branch, "--base", base]
        if draft:
            cmd.append("--draft")
        try:
            r = self._run(cmd, timeout=30)
            if r.returncode != 0:
                _log.warning("create_pr failed: %s", r.stderr[:300])
                return 0
            # Extract PR number from URL
            url = r.stdout.strip()
            parts = url.rstrip("/").split("/")
            return int(parts[-1]) if parts and parts[-1].isdigit() else 0
        except Exception as exc:
            _log.warning("create_pr: %s", exc)
            return 0

    def merge_pr(self, pr_number: int, method: str = "squash") -> bool:
        try:
            r = self._run(
                ["gh", "pr", "merge", str(pr_number), f"--{method}", "--auto"],
                timeout=30,
            )
            return r.returncode == 0
        except Exception as exc:
            _log.warning("merge_pr(%d): %s", pr_number, exc)
            return False

    def fetch_changed_files(self, branch: str, base: str = "main") -> List[str]:
        try:
            r = self._run(
                ["git", "diff", "--name-only", f"{base}...{branch}"],
                timeout=15,
            )
            if r.returncode != 0:
                return []
            return [f.strip() for f in r.stdout.splitlines() if f.strip()]
        except Exception as exc:
            _log.warning("fetch_changed_files(%s): %s", branch, exc)
            return []

    def get_pr_info(self, pr_number: int) -> Optional[PRInfo]:
        try:
            r = self._run(
                ["gh", "pr", "view", str(pr_number),
                 "--json", "number,title,state,isDraft,headRefOid,baseRefName,headRefName"],
            )
            if r.returncode != 0:
                return None
            d = json.loads(r.stdout or "{}")
            return PRInfo(
                pr_number=d.get("number", pr_number),
                title=d.get("title", ""),
                state=d.get("state", "").lower(),
                is_draft=bool(d.get("isDraft", False)),
                head_sha=d.get("headRefOid", ""),
                base=d.get("baseRefName", "main"),
                branch=d.get("headRefName", ""),
            )
        except Exception as exc:
            _log.warning("get_pr_info(%d): %s", pr_number, exc)
            return None

    def delete_branch(self, branch: str, remote: bool = True) -> bool:
        ok = True
        if remote:
            try:
                r = self._run(["git", "push", "origin", "--delete", branch], timeout=30)
                if r.returncode != 0 and "remote ref does not exist" not in r.stderr:
                    ok = False
            except Exception:
                ok = False
        try:
            self._run(["git", "branch", "-d", branch], timeout=10)
        except Exception:
            pass
        return ok


# ---------------------------------------------------------------------------
# Fake backend for tests
# ---------------------------------------------------------------------------

class FakeGitHubBackend(GitHubBackend):
    """In-memory fake GitHub backend for unit tests.

    Configure before use:
        fake = FakeGitHubBackend()
        fake.set_ci_status("red", failed_jobs=["pytest"])
        fake.set_pr_logs("FAILED tests/test_foo.py::test_bar\\nAssertionError")
        fake.set_pr_info(PRInfo(pr_number=42, state="open"))
    """

    def __init__(self) -> None:
        # Configurable state
        self._ci_status: str = "green"
        self._failed_jobs: List[str] = []
        self._pr_logs: str = ""
        self._commit_should_fail: bool = False
        self._push_should_fail: bool = False
        self._merge_should_fail: bool = False
        self._pr_info: Optional[PRInfo] = None
        self._changed_files: List[str] = []
        self._next_pr_number: int = 1

        # Recorded calls for assertions
        self.commits: List[Dict[str, Any]] = []
        self.pushes: int = 0
        self.merges: List[int] = []
        self.branch_deletes: List[str] = []
        self.created_prs: List[Dict[str, Any]] = []

    # -- Configuration helpers --

    def set_ci_status(
        self,
        status: str,
        failed_jobs: Optional[List[str]] = None,
    ) -> None:
        """Set what list_pr_checks() returns."""
        self._ci_status = status
        self._failed_jobs = failed_jobs or []

    def set_pr_logs(self, log_text: str) -> None:
        """Set what fetch_failed_logs() returns."""
        self._pr_logs = log_text

    def set_commit_fails(self, fails: bool = True) -> None:
        self._commit_should_fail = fails

    def set_push_fails(self, fails: bool = True) -> None:
        self._push_should_fail = fails

    def set_merge_fails(self, fails: bool = True) -> None:
        self._merge_should_fail = fails

    def set_pr_info(self, info: PRInfo) -> None:
        self._pr_info = info

    def set_changed_files(self, files: List[str]) -> None:
        self._changed_files = files

    # -- GitHubBackend interface --

    def list_pr_checks(self, pr_number: int) -> PRCheckResult:
        return PRCheckResult(
            status=self._ci_status,
            failed_jobs=list(self._failed_jobs),
            succeeded_jobs=[] if self._ci_status != "green" else ["pytest"],
        )

    def fetch_failed_logs(self, pr_number: int, max_chars: int = 6000) -> str:
        return self._pr_logs[:max_chars]

    def commit_changes(self, message: str, files: Optional[List[str]] = None) -> CommitResult:
        self.commits.append({"message": message, "files": files, "ts": time.time()})
        if self._commit_should_fail:
            return CommitResult(committed=False, pushed=False, error="fake commit failure")
        return CommitResult(committed=True, pushed=False, sha="fake_sha_" + str(len(self.commits)))

    def push_branch(self) -> bool:
        self.pushes += 1
        return not self._push_should_fail

    def create_pr(
        self,
        title: str,
        body: str,
        branch: str,
        base: str = "main",
        draft: bool = False,
    ) -> int:
        pr_num = self._next_pr_number
        self._next_pr_number += 1
        self.created_prs.append(
            {"number": pr_num, "title": title, "branch": branch, "draft": draft}
        )
        return pr_num

    def merge_pr(self, pr_number: int, method: str = "squash") -> bool:
        self.merges.append(pr_number)
        return not self._merge_should_fail

    def fetch_changed_files(self, branch: str, base: str = "main") -> List[str]:
        return list(self._changed_files)

    def get_pr_info(self, pr_number: int) -> Optional[PRInfo]:
        if self._pr_info:
            return self._pr_info
        return PRInfo(pr_number=pr_number, state="open", is_draft=False)

    def delete_branch(self, branch: str, remote: bool = True) -> bool:
        self.branch_deletes.append(branch)
        return True
