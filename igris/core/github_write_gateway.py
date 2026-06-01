"""
GitHub Write Gateway — gated GitHub write operations.

Authorization: AuthorizationGate (deny-by-default, issue #526)
Advisory:      JudgmentLayer (advisory-only, never blocks, issue #526)
Default:       dry_run=True for safety; all destructive actions require explicit opt-in.

Hardening (#1128):
- GitHubWriteApproval required for destructive actions when dry_run=False.
- merge_pr checks CI green + expected_head_sha.
- Persistent audit log (JSONL file on disk).
"""
import json
import logging
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from igris.core.authorization_gate import AuthorizationGate, AuthResult
from igris.core.identity_resolver import InterlocutorProfile
from igris.core.judgment_layer import Advisory, JudgmentLayer, OperationalContext
from igris.core.safety import redact_secrets

logger = logging.getLogger(__name__)

# Default supervisor profile used when IGRIS calls GitHub on its own behalf
_SUPERVISOR_PROFILE = InterlocutorProfile(
    profile_id="igris-supervisor",
    display_name="IGRIS Supervisor",
    trust_level="admin",
    authorized_scopes=[
        "github_write",
        "github_write_comment",
        "github_write_label",
        "github_write_issue_create",
        "github_write_issue_close",
        "github_write_pr_merge",
        "github_write_actions_trigger",
        "github_admin",
    ],
)


# ---------------------------------------------------------------------------
# Approval model (#1128)
# ---------------------------------------------------------------------------

@dataclass
class GitHubWriteApproval:
    """Explicit approval object for destructive GitHub write actions."""
    approved_by: str
    reason: str
    action: str
    target: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expected_head_sha: str = ""  # required for merge_pr


@dataclass
class GitHubWriteResult:
    success: bool
    action_type: str
    target: str
    dry_run: bool
    authorized: bool
    advisory: Optional[Advisory] = None
    approval: Optional[GitHubWriteApproval] = None
    output: Optional[str] = None
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class GitHubWriteGateway:
    """Gated GitHub write operations: auth gate + judgment advisory + dry-run + audit log."""

    def __init__(
        self,
        project_root: str = ".",
        dry_run: bool = True,
        repo_path: str = ".",
        profile: Optional[InterlocutorProfile] = None,
        audit_dir: Optional[str] = None,
    ):
        self.auth_gate = AuthorizationGate(project_root=project_root)
        self.judgment = JudgmentLayer()
        self.dry_run = dry_run
        self.repo_path = repo_path
        self.profile = profile or _SUPERVISOR_PROFILE
        self.audit_log: List[Dict[str, Any]] = []
        # Persistent audit (#1128)
        self._audit_dir: Optional[Path] = None
        if audit_dir:
            self._audit_dir = Path(audit_dir)
            self._audit_dir.mkdir(parents=True, exist_ok=True)

    def _record_audit(self, entry: Dict[str, Any]) -> None:
        """Append to in-memory list AND persist to disk if audit_dir set."""
        safe = dict(entry)
        for key in ("output", "error", "reason"):
            if key in safe and safe[key]:
                safe[key] = redact_secrets(str(safe[key]))
        self.audit_log.append(safe)
        logger.info("AUDIT: %s", json.dumps(safe, default=str))
        if self._audit_dir:
            self._persist_audit(safe)

    def _persist_audit(self, entry: Dict[str, Any]) -> None:
        """Append audit entry as JSONL to persistent file (#1128)."""
        try:
            audit_file = self._audit_dir / "github_write_audit.jsonl"  # type: ignore[union-attr]
            with open(audit_file, "a") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist audit: %s", exc)

    def _execute(
        self,
        action_type: str,
        required_scope: str,
        target: str,
        gh_args: List[str],
        context: Optional[dict] = None,
        destructive: bool = False,
        approval: Optional[GitHubWriteApproval] = None,
    ) -> GitHubWriteResult:
        context = context or {}

        # Destructive actions require explicit approval when not dry-run (#1128)
        if destructive and not self.dry_run and approval is None:
            self._record_audit({
                "action": action_type, "target": target,
                "mission_id": context.get("mission_id"),
                "run_id": context.get("run_id"),
                "outcome": "denied_no_approval",
                "reason": "destructive action requires explicit GitHubWriteApproval",
                "dry_run": self.dry_run, "destructive": True,
            })
            return GitHubWriteResult(
                success=False, action_type=action_type, target=target,
                dry_run=False, authorized=False,
                error="Destructive action requires explicit GitHubWriteApproval object",
            )

        # Authorization check
        base_auth: AuthResult = self.auth_gate.check(
            profile=self.profile,
            action_type="github_write",
            target_resource="github_write",
        )
        if not base_auth.allowed:
            self._record_audit({
                "action": action_type,
                "target": target,
                "mission_id": context.get("mission_id"),
                "run_id": context.get("run_id"),
                "outcome": "denied",
                "reason": base_auth.reason,
                "dry_run": self.dry_run,
            })
            return GitHubWriteResult(
                success=False, action_type=action_type, target=target,
                dry_run=self.dry_run, authorized=False,
                error=f"Authorization denied: {base_auth.reason}",
            )

        auth: AuthResult = self.auth_gate.check(
            profile=self.profile,
            action_type="github_write",
            target_resource=required_scope,
        )
        if not auth.allowed:
            self._record_audit({
                "action": action_type, "target": target,
                "mission_id": context.get("mission_id"),
                "run_id": context.get("run_id"),
                "outcome": "denied", "reason": auth.reason, "dry_run": self.dry_run,
            })
            return GitHubWriteResult(
                success=False, action_type=action_type, target=target,
                dry_run=self.dry_run, authorized=False,
                error=f"Authorization denied: {auth.reason}",
            )

        # Advisory judgment (never blocks)
        op_ctx = OperationalContext(run_in_progress=bool(context.get("run_id")))
        advisory: Advisory = self.judgment.advise(
            action_type=action_type,
            target_resource=target,
            context=op_ctx,
            trust_level=self.profile.trust_level,
        )
        if not advisory.should_proceed:
            logger.warning("Advisory caution on %s for %s: %s", action_type, target, advisory.message)

        if self.dry_run:
            self._record_audit({
                "action": action_type, "target": target, "outcome": "dry_run",
                "advisory": advisory.message, "dry_run": True,
                "mission_id": context.get("mission_id"),
                "run_id": context.get("run_id"),
                "destructive": destructive,
            })
            return GitHubWriteResult(
                success=True, action_type=action_type, target=target,
                dry_run=True, authorized=True, advisory=advisory,
                approval=approval,
                output=f"[DRY RUN] Would execute: gh {' '.join(gh_args)}",
            )

        try:
            proc = subprocess.run(
                ["gh"] + gh_args,
                capture_output=True, text=True, check=False, cwd=self.repo_path,
            )
            success = proc.returncode == 0
            self._record_audit({
                "action": action_type, "target": target,
                "outcome": "success" if success else "failure",
                "advisory": advisory.message, "dry_run": False,
                "mission_id": context.get("mission_id"),
                "run_id": context.get("run_id"),
                "destructive": destructive,
                "output": proc.stdout.strip(), "error": proc.stderr.strip(),
            })
            return GitHubWriteResult(
                success=success, action_type=action_type, target=target,
                dry_run=False, authorized=True, advisory=advisory,
                approval=approval,
                output=proc.stdout.strip() if success else None,
                error=proc.stderr.strip() if not success else None,
            )
        except Exception as exc:
            self._record_audit({
                "action": action_type, "target": target, "outcome": "exception",
                "error": str(exc), "dry_run": False,
                "mission_id": context.get("mission_id"),
                "run_id": context.get("run_id"),
                "destructive": destructive,
            })
            return GitHubWriteResult(
                success=False, action_type=action_type, target=target,
                dry_run=False, authorized=True, advisory=advisory,
                approval=approval,
                error=f"Exception: {exc}",
            )

    # --- Public operations ---

    def comment(self, issue_url: str, body: str, context: dict = None) -> GitHubWriteResult:
        """Add a comment to an issue or PR."""
        return self._execute(
            "comment", "github_write_comment", issue_url,
            ["issue", "comment", issue_url, "--body", body],
            context=context,
        )

    def add_label(self, issue_url: str, labels: List[str], context: dict = None) -> GitHubWriteResult:
        """Add labels to an issue/PR."""
        args = ["issue", "edit", issue_url] + [f"--add-label={lbl}" for lbl in labels]
        return self._execute("label", "github_write_label", issue_url, args, context=context)

    def remove_label(self, issue_url: str, labels: List[str], context: dict = None) -> GitHubWriteResult:
        """Remove labels from an issue/PR."""
        args = ["issue", "edit", issue_url] + [f"--remove-label={lbl}" for lbl in labels]
        return self._execute("label", "github_write_label", issue_url, args, context=context)

    def close_issue(
        self,
        issue_url: str,
        comment: str = "",
        context: dict = None,
        approval: Optional[GitHubWriteApproval] = None,
    ) -> GitHubWriteResult:
        """Close an issue with optional comment (destructive — requires approval)."""
        args = ["issue", "close", issue_url]
        if comment:
            args += ["--comment", comment]
        return self._execute(
            "issue/close",
            "github_write_issue_close",
            issue_url,
            args,
            context=context,
            destructive=True,
            approval=approval,
        )

    def create_issue(
        self,
        title: str,
        body: str,
        labels: List[str] = None,
        assignees: List[str] = None,
        context: dict = None,
    ) -> GitHubWriteResult:
        """Create a new issue."""
        args = ["issue", "create", "--title", title, "--body", body]
        if labels:
            args += [f"--label={','.join(labels)}"]
        if assignees:
            args += [f"--assignee={','.join(assignees)}"]
        return self._execute("issue/create", "github_write_issue_create", title, args, context=context)

    def merge_pr(
        self,
        pr_url: str,
        method: str = "merge",
        context: dict = None,
        approval: Optional[GitHubWriteApproval] = None,
        ci_status: Optional[str] = None,
        expected_head_sha: Optional[str] = None,
    ) -> GitHubWriteResult:
        """Merge a pull request (destructive — requires approval + CI green).

        Hardening (#1128):
        - ci_status must be 'success' or 'passed' unless dry_run.
        - expected_head_sha must match approval.expected_head_sha if both present.
        """
        if not self.dry_run:
            ci = (ci_status or "").lower().strip()
            if ci not in ("success", "passed"):
                self._record_audit({
                    "action": "pr/merge", "target": pr_url,
                    "mission_id": (context or {}).get("mission_id"),
                    "run_id": (context or {}).get("run_id"),
                    "outcome": "blocked_ci",
                    "reason": f"CI status '{ci_status}' is not green",
                    "dry_run": False, "destructive": True,
                })
                return GitHubWriteResult(
                    success=False, action_type="pr/merge", target=pr_url,
                    dry_run=False, authorized=True,
                    error=f"Merge blocked: CI status '{ci_status}' is not green",
                )
            if approval and approval.expected_head_sha and expected_head_sha:
                if approval.expected_head_sha != expected_head_sha:
                    self._record_audit({
                        "action": "pr/merge", "target": pr_url,
                        "mission_id": (context or {}).get("mission_id"),
                        "run_id": (context or {}).get("run_id"),
                        "outcome": "blocked_head_mismatch",
                        "reason": f"head SHA mismatch: approval={approval.expected_head_sha} current={expected_head_sha}",
                        "dry_run": False, "destructive": True,
                    })
                    return GitHubWriteResult(
                        success=False, action_type="pr/merge", target=pr_url,
                        dry_run=False, authorized=True,
                        error="Merge blocked: expected_head_sha mismatch",
                    )
        args = ["pr", "merge", pr_url, f"--{method}"]
        return self._execute(
            "pr/merge",
            "github_write_pr_merge",
            pr_url,
            args,
            context=context,
            destructive=True,
            approval=approval,
        )

    def trigger_action(
        self,
        workflow: str,
        ref: str = "main",
        inputs: dict = None,
        context: dict = None,
    ) -> GitHubWriteResult:
        """Trigger a GitHub Actions workflow."""
        args = ["workflow", "run", workflow, "--ref", ref]
        if inputs:
            for k, v in inputs.items():
                args += [f"-f{k}={v}"]
        return self._execute(
            "actions/trigger",
            "github_write_actions_trigger",
            workflow,
            args,
            context=context,
        )
