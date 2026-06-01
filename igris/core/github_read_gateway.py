"""
GitHub Read Gateway

Provides gated, audited read access to GitHub resources:
issues, pull requests, files on remote branches, Actions workflow status,
and release information.

Each operation:
- Logs access with resource type, identifier, timestamp (audit trail)
- Supports dry-run mode (simulated access without real execution)
- Returns normalized data (not raw API)

Hardening (#1127):
- Secret-path denylist blocks reads of sensitive files.
- Persistent audit log (JSONL file on disk).
- Content redaction via redact_secrets.
"""

import base64
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from igris.core.authorization_gate import AuthorizationGate
from igris.core.identity_resolver import InterlocutorProfile
from igris.core.safety import redact_secrets

logger = logging.getLogger(__name__)

_SUPERVISOR_READ_PROFILE = InterlocutorProfile(
    profile_id="igris-supervisor-read",
    display_name="IGRIS Supervisor Read",
    trust_level="trusted",
    authorized_scopes=[
        "github_read",
        "github_read_issue",
        "github_read_pr",
        "github_read_issues",
        "github_read_file",
        "github_read_actions",
    ],
)


# ---------------------------------------------------------------------------
# Secret-path denylist (#1127)
# ---------------------------------------------------------------------------

_SECRET_PATH_PATTERNS: List[str] = [
    ".env",
    ".env.",           # .env.local, .env.production, etc.
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    ".pem",
    "credentials",
    "secrets",
    "private_key",
    "service_account",
    ".p12",
    ".pfx",
    ".key",
    "token",
    ".htpasswd",
]

_SECRET_EXACT_NAMES = {
    ".env",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".docker/config.json",
    ".kube/config",
    ".ssh/config",
    ".ssh/authorized_keys",
    ".git-credentials",
}


def _is_secret_path(path: str) -> bool:
    """Check if a file path looks like a secret/credential file."""
    p = path.strip().lower()
    basename = p.rsplit("/", 1)[-1] if "/" in p else p
    if basename in _SECRET_EXACT_NAMES or p in _SECRET_EXACT_NAMES:
        return True
    for pattern in _SECRET_PATH_PATTERNS:
        if pattern in basename:
            return True
    return False


class GitHubReadGateway:
    """Gated reader for GitHub resources."""

    def __init__(
        self,
        auth_gate: AuthorizationGate,
        repo: str = ".",
        profile: Optional[InterlocutorProfile] = None,
        protected_branches: Optional[List[str]] = None,
        audit_dir: Optional[str] = None,
    ):
        self._auth = auth_gate
        self._repo = repo
        self._profile = profile or _SUPERVISOR_READ_PROFILE
        self._protected_branches = {b.lower() for b in (protected_branches or [])}
        self._audit_log: List[Dict[str, Any]] = []
        # Persistent audit (#1127)
        self._audit_dir: Optional[Path] = None
        if audit_dir:
            self._audit_dir = Path(audit_dir)
            self._audit_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def read_issue(
        self,
        issue_number: int,
        dry_run: bool = False,
        mission_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Read a single issue by number."""
        self._ensure_authorized("github_read_issue", f"issue/{issue_number}")
        self._log_audit("issue", str(issue_number), dry_run=dry_run, mission_id=mission_id, run_id=run_id)
        if dry_run:
            return self._dry_run_response("issue", issue_number)

        result = self._gh(
            "issue", "view", str(issue_number),
            "--json", "number,title,state,body,labels,assignees,url,createdAt,updatedAt,comments"
        )
        return self._normalize_issue(json.loads(result))

    def read_pr(
        self,
        pr_number: int,
        dry_run: bool = False,
        mission_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Read a pull request by number."""
        self._ensure_authorized("github_read_pr", f"pr/{pr_number}")
        self._log_audit("pr", str(pr_number), dry_run=dry_run, mission_id=mission_id, run_id=run_id)
        if dry_run:
            return self._dry_run_response("pr", pr_number)

        result = self._gh(
            "pr", "view", str(pr_number),
            "--json", "number,title,state,body,headRefName,baseRefName,commits,statusCheckRollup,url"
        )
        return self._normalize_pr(json.loads(result))

    def list_issues(
        self,
        state: Optional[str] = None,
        label: Optional[str] = None,
        assignee: Optional[str] = None,
        limit: int = 30,
        dry_run: bool = False,
        mission_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List issues with optional filters."""
        self._ensure_authorized("github_read_issues", "issues/list")
        self._log_audit("issues", "list", dry_run=dry_run, mission_id=mission_id, run_id=run_id)
        if dry_run:
            return [{"dry_run": True, "resource": "issues",
                     "filters": {"state": state, "label": label, "limit": limit}}]

        args = ["issue", "list", "--limit", str(limit)]
        if state:
            args += ["--state", state]
        if label:
            args += ["--label", label]
        if assignee:
            args += ["--assignee", assignee]
        args += ["--json", "number,title,state,labels,url,createdAt,assignees"]

        raw = self._gh(*args)
        issues = json.loads(raw)
        return [self._normalize_issue(item) for item in issues]

    def read_file(
        self,
        path: str,
        branch: str = "main",
        dry_run: bool = False,
        mission_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Read a file from a remote branch.

        Hardening (#1127): blocks reads of secret-path files.
        """
        # Secret-path denylist (#1127)
        if _is_secret_path(path):
            self._log_audit(
                "file", f"{branch}:{path}", dry_run=dry_run,
                mission_id=mission_id, run_id=run_id, blocked=True,
                blocked_reason="secret_path_denied",
            )
            raise PermissionError(f"Secret-path read blocked: {path}")

        branch_norm = (branch or "main").strip().lower()
        scope = "github_read_file_protected" if branch_norm in self._protected_branches else "github_read_file"
        self._ensure_authorized(scope, f"file/{branch}:{path}")
        self._log_audit("file", f"{branch}:{path}", dry_run=dry_run, mission_id=mission_id, run_id=run_id)
        if dry_run:
            return self._dry_run_response("file", f"{branch}:{path}")

        result = self._gh(
            "api", f"repos/{{owner}}/{{repo}}/contents/{path}?ref={branch}"
        )
        return self._normalize_file(json.loads(result))

    def read_actions(
        self, workflow_name: Optional[str] = None,
        status: Optional[str] = None,
        dry_run: bool = False,
        mission_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Read latest Actions workflow run(s)."""
        self._ensure_authorized("github_read_actions", f"actions/{workflow_name or 'all'}")
        self._log_audit("actions", workflow_name or "all", dry_run=dry_run, mission_id=mission_id, run_id=run_id)
        if dry_run:
            return [self._dry_run_response("actions", workflow_name or "all")]

        args = ["run", "list", "--limit", "10"]
        if workflow_name:
            args += ["--workflow", workflow_name]
        if status:
            args += ["--status", status]
        args += ["--json", "databaseId,name,status,conclusion,headBranch,createdAt,url,event,runNumber"]

        result = self._gh(*args)
        runs = json.loads(result)
        return [self._normalize_actions_run(r) for r in runs]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _ensure_authorized(self, scope: str, target: str) -> None:
        base = self._auth.check(
            profile=self._profile,
            action_type="github_read",
            target_resource="github_read",
        )
        if not base.allowed:
            raise PermissionError(f"Scope violation: {base.reason} for github_read")
        op = self._auth.check(
            profile=self._profile,
            action_type="github_read",
            target_resource=scope,
        )
        if not op.allowed:
            raise PermissionError(f"Scope violation: {op.reason} for {scope} on {target}")


    def _gh(self, *args: str) -> str:
        """Run a gh CLI command and return stdout."""
        cmd = ["gh", *args]
        if self._repo and self._repo != ".":
            cmd += ["--repo", self._repo]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"gh command failed: {' '.join(cmd)}\nstderr: {proc.stderr}"
            )
        return proc.stdout.strip()

    def _dry_run_response(self, resource: str, identifier: Any) -> Dict[str, Any]:
        resp = {
            "dry_run": True,
            "resource": resource,
            "identifier": str(identifier),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return resp

    def _log_audit(
        self,
        resource_type: str,
        identifier: str,
        authorized: bool = True,
        dry_run: bool = False,
        mission_id: Optional[str] = None,
        run_id: Optional[str] = None,
        blocked: bool = False,
        blocked_reason: str = "",
    ) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "resource": f"{resource_type}/{identifier}",
            "authorized": authorized,
            "dry_run": dry_run,
            "mission_id": mission_id,
            "run_id": run_id,
        }
        if blocked:
            entry["blocked"] = True
            entry["blocked_reason"] = blocked_reason
        self._audit_log.append(entry)
        logger.info("GitHubReadGateway audit: %s", entry)
        if self._audit_dir:
            self._persist_audit(entry)

    def _persist_audit(self, entry: Dict[str, Any]) -> None:
        """Append audit entry as JSONL to persistent file (#1127)."""
        try:
            audit_file = self._audit_dir / "github_read_audit.jsonl"  # type: ignore[union-attr]
            with open(audit_file, "a") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist read audit: %s", exc)

    # ------------------------------------------------------------------
    # Normalizers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_issue(raw: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "number": raw.get("number"),
            "title": raw.get("title"),
            "state": raw.get("state"),
            "body": redact_secrets((raw.get("body") or "")[:5000]),
            "labels": [lbl["name"] if isinstance(lbl, dict) else lbl
                       for lbl in raw.get("labels", [])],
            "assignees": [a["login"] if isinstance(a, dict) else a
                          for a in raw.get("assignees", [])],
            "url": raw.get("url"),
            "created_at": raw.get("createdAt"),
            "updated_at": raw.get("updatedAt"),
        }

    @staticmethod
    def _normalize_pr(raw: Dict[str, Any]) -> Dict[str, Any]:
        ci_checks = raw.get("statusCheckRollup") or []
        ci_status = [
            {"context": c.get("context", c.get("name", "")),
             "state": c.get("conclusion") or c.get("state", "")}
            for c in ci_checks
        ] if ci_checks else None

        commits = raw.get("commits", [])
        return {
            "number": raw.get("number"),
            "title": raw.get("title"),
            "state": raw.get("state"),
            "body": redact_secrets((raw.get("body") or "")[:5000]),
            "head": raw.get("headRefName"),
            "base": raw.get("baseRefName"),
            "commits": len(commits),
            "ci_status": ci_status,
            "url": raw.get("url"),
        }

    @staticmethod
    def _normalize_file(raw: Dict[str, Any]) -> Dict[str, Any]:
        content = raw.get("content", "")
        try:
            decoded = base64.b64decode(content).decode("utf-8")
        except Exception:
            decoded = "[binary or undecodable content]"
        # Size limit post-decode
        truncated = decoded[:10000]
        # Redact any secret-like content in file body
        safe_content = redact_secrets(truncated)
        return {
            "path": raw.get("path"),
            "sha": raw.get("sha"),
            "size": raw.get("size", 0),
            "encoding": "utf-8",
            "content": safe_content,
        }

    @staticmethod
    def _normalize_actions_run(raw: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": raw.get("databaseId"),
            "name": raw.get("name"),
            "status": raw.get("status"),
            "conclusion": raw.get("conclusion"),
            "head_branch": raw.get("headBranch"),
            "event": raw.get("event"),
            "run_number": raw.get("runNumber"),
            "created_at": raw.get("createdAt"),
            "url": raw.get("url"),
        }
