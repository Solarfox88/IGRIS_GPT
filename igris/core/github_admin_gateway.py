import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Optional, Dict, Any, Protocol, runtime_checkable
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class GitHubAdminApproval:
    """Explicit approval required for mutating admin operations."""

    approved: bool = False
    approved_by: str = ""
    ticket_id: str = ""
    rationale: str = ""
    approved_at: str = ""

    def is_valid(self) -> bool:
        return bool(self.approved and self.approved_by.strip())


@dataclass
class GitHubAdminPlan:
    """Dry-run proposal for a GitHub admin action."""

    action: str
    target: str
    details: Dict[str, Any] = field(default_factory=dict)
    approval_required: bool = True
    dry_run: bool = True
    status: str = "planned"


@runtime_checkable
class GitHubAdminBackend(Protocol):
    """Optional backend for safe read-only inspection and approved mutations."""

    def inspect_repo(self, repo: str) -> Dict[str, Any]: ...
    def inspect_repo_settings(self, repo: str) -> Dict[str, Any]: ...
    def inspect_branch_protection(self, repo: str, branch: str) -> Dict[str, Any]: ...
    def list_collaborators(self, repo: str) -> list[Dict[str, Any]]: ...
    def inspect_actions_metadata(self, repo: str) -> Dict[str, Any]: ...
    def inspect_secret_variable_metadata(self, repo: str) -> Dict[str, Any]: ...
    def apply_branch_protection(self, repo: str, branch: str, rules: Dict[str, Any]) -> Dict[str, Any]: ...
    def add_collaborator(self, repo: str, username: str, permission: str) -> Dict[str, Any]: ...
    def remove_collaborator(self, repo: str, username: str) -> Dict[str, Any]: ...
    def set_secret(self, repo: str, secret_name: str, secret_value: str) -> Dict[str, Any]: ...
    def create_repo(self, name: str, description: str, private: bool) -> Dict[str, Any]: ...
    def delete_repo(self, repo: str) -> Dict[str, Any]: ...


class GitHubAdminGateway:
    """
    Triple-gated gateway for GitHub administrative operations.

    All operations require:
    1. AuthorizationGate: scope 'admin' required
    2. JudgmentLayer: operation must be approved by risk assessment
    3. HumanApproval: explicit out-of-band confirmation

    Every attempt (successful or denied) is logged.
    Dry-run is the default mode.
    """

    def __init__(
        self,
        dry_run: bool = True,
        backend: Optional[GitHubAdminBackend] = None,
        audit_path: str = ".igris/github_admin_audit.jsonl",
    ):
        self.dry_run = dry_run
        self.backend = backend
        self.audit_log: list[dict] = []
        self.audit_path = Path(audit_path)

    def _log(self, action: str, target: str, status: str, details: dict = None):
        """Record an audit entry for every attempt."""
        entry = {
            "id": str(uuid4())[:8],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "target": target,
            "status": status,
            "details": self._redact(details or {}),
            "dry_run": self.dry_run,
        }
        self.audit_log.append(entry)
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            logger.warning("GitHubAdminGateway audit write failed for %s", action)
        logger.info(f"AUDIT: {entry}")
        return entry

    @staticmethod
    def _redact(value: Any) -> Any:
        if isinstance(value, dict):
            out: Dict[str, Any] = {}
            for key, raw in value.items():
                key_str = str(key).lower()
                if any(token in key_str for token in ("secret", "token", "password", "private_key", "ssh_key", "value")):
                    out[str(key)] = "[REDACTED]"
                else:
                    out[str(key)] = GitHubAdminGateway._redact(raw)
            return out
        if isinstance(value, list):
            return [GitHubAdminGateway._redact(item) for item in value]
        return value

    def _approval_is_valid(self, approval: Optional[GitHubAdminApproval]) -> bool:
        return bool(approval and approval.is_valid())

    def _require_mutation_approval(self, action: str, target: str, approval: Optional[GitHubAdminApproval]) -> Optional[dict]:
        if self.dry_run:
            return None
        if not self._approval_is_valid(approval):
            self._log(action, target, "DENIED_APPROVAL", {"approval_required": True})
            return {"success": False, "reason": "Approval required", "approval_required": True, "dry_run": False}
        return None

    def _backend_call(self, method_name: str, *args: Any, fallback: Any = None, **kwargs: Any) -> Any:
        fn = getattr(self.backend, method_name, None)
        if callable(fn):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.warning("GitHubAdminGateway backend %s failed: %s", method_name, exc)
        return fallback

    # ------------------------------------------------------------------
    # Authorization & Approval gates (stubs for integration)
    # ------------------------------------------------------------------
    def check_authorization(self, scope: str) -> bool:
        """Verify the caller holds the required scope."""
        # Placeholder: real implementation will check JWT / token
        return scope == "admin"

    def judgment_layer(self, action: str, target: str) -> bool:
        """Risk assessment: allow or deny."""
        # Placeholder: integrate with risk engine
        return True

    def require_human_approval(self, ticket_id: str) -> bool:
        """Block until human operator approves out-of-band."""
        # Placeholder: actual implementation sends Slack/email and waits
        return True

    # ------------------------------------------------------------------
    # Operations – all require triple gate
    # ------------------------------------------------------------------
    def _triple_gate(self, action: str, target: str) -> bool:
        """Run authorization, judgment, and approval."""
        if not self.check_authorization("admin"):
            self._log(action, target, "DENIED_AUTH")
            return False
        if not self.judgment_layer(action, target):
            self._log(action, target, "DENIED_JUDGMENT")
            return False
        if not self.require_human_approval(f"admin-{action}-{target}"):
            self._log(action, target, "DENIED_APPROVAL")
            return False
        return True

    # ------------------------------------------------------------------
    # Read-only inspection
    # ------------------------------------------------------------------
    def inspect_repo(self, repo: str, branch: str = "main") -> dict:
        """Read-only repo inspection with safe redaction and fallback metadata."""
        action = "repo.inspect"
        if not self._triple_gate(action, repo):
            return {"success": False, "reason": "Gate denied"}
        if self.dry_run:
            payload = {
                "repo": repo,
                "repo_settings": {"status": "unavailable", "reason": "dry_run"},
                "branch_protection": {"branch": branch, "status": "unavailable", "reason": "dry_run"},
                "collaborators": {"status": "unavailable", "reason": "dry_run"},
                "actions_metadata": {"status": "unavailable", "reason": "dry_run"},
                "secrets_variables_metadata": {"status": "unavailable", "reason": "dry_run"},
            }
            self._log(action, repo, "DRY_RUN", payload)
            return {"success": True, "dry_run": True, "report": payload}
        report = {
            "repo": repo,
            "repo_settings": self._redact(self._backend_call("inspect_repo_settings", repo, fallback={"status": "unavailable"})),
            "branch_protection": self._redact(self._backend_call("inspect_branch_protection", repo, branch, fallback={"branch": branch, "status": "unavailable"})),
            "collaborators": self._redact(self._backend_call("list_collaborators", repo, fallback={"status": "unavailable"})),
            "actions_metadata": self._redact(self._backend_call("inspect_actions_metadata", repo, fallback={"status": "unavailable"})),
            "secrets_variables_metadata": self._redact(self._backend_call("inspect_secret_variable_metadata", repo, fallback={"status": "unavailable"})),
        }
        self._log(action, repo, "INSPECTED", report)
        return {"success": True, "dry_run": False, "report": report}

    def inspect_repo_settings(self, repo: str) -> dict:
        action = "repo.settings.inspect"
        if not self._triple_gate(action, repo):
            return {"success": False, "reason": "Gate denied"}
        if self.dry_run:
            payload = {"repo": repo, "status": "dry_run", "reason": "dry_run"}
            self._log(action, repo, "DRY_RUN", payload)
            return {"success": True, "dry_run": True, "report": payload}
        report = self._redact(self._backend_call("inspect_repo_settings", repo, fallback={"status": "unavailable"}))
        self._log(action, repo, "INSPECTED", report)
        return {"success": True, "dry_run": False, "report": report}

    def inspect_branch_protection(self, repo: str, branch: str = "main") -> dict:
        action = "branch.protection.inspect"
        if not self._triple_gate(action, repo):
            return {"success": False, "reason": "Gate denied"}
        if self.dry_run:
            payload = {"repo": repo, "branch": branch, "status": "dry_run", "reason": "dry_run"}
            self._log(action, repo, "DRY_RUN", payload)
            return {"success": True, "dry_run": True, "report": payload}
        report = self._redact(self._backend_call("inspect_branch_protection", repo, branch, fallback={"branch": branch, "status": "unavailable"}))
        self._log(action, repo, "INSPECTED", report)
        return {"success": True, "dry_run": False, "report": report}

    def inspect_collaborators(self, repo: str) -> dict:
        action = "collaborators.inspect"
        if not self._triple_gate(action, repo):
            return {"success": False, "reason": "Gate denied"}
        if self.dry_run:
            payload = {"repo": repo, "status": "dry_run", "reason": "dry_run"}
            self._log(action, repo, "DRY_RUN", payload)
            return {"success": True, "dry_run": True, "report": payload}
        report = self._redact(self._backend_call("list_collaborators", repo, fallback={"status": "unavailable"}))
        self._log(action, repo, "INSPECTED", report)
        return {"success": True, "dry_run": False, "report": report}

    def inspect_actions_metadata(self, repo: str) -> dict:
        action = "actions.metadata.inspect"
        if not self._triple_gate(action, repo):
            return {"success": False, "reason": "Gate denied"}
        if self.dry_run:
            payload = {"repo": repo, "status": "dry_run", "reason": "dry_run"}
            self._log(action, repo, "DRY_RUN", payload)
            return {"success": True, "dry_run": True, "report": payload}
        report = self._redact(self._backend_call("inspect_actions_metadata", repo, fallback={"status": "unavailable"}))
        self._log(action, repo, "INSPECTED", report)
        return {"success": True, "dry_run": False, "report": report}

    def inspect_secret_variable_metadata(self, repo: str) -> dict:
        action = "secrets.variables.inspect"
        if not self._triple_gate(action, repo):
            return {"success": False, "reason": "Gate denied"}
        if self.dry_run:
            payload = {"repo": repo, "status": "dry_run", "reason": "dry_run"}
            self._log(action, repo, "DRY_RUN", payload)
            return {"success": True, "dry_run": True, "report": payload}
        report = self._redact(self._backend_call("inspect_secret_variable_metadata", repo, fallback={"status": "unavailable"}))
        self._log(action, repo, "INSPECTED", report)
        return {"success": True, "dry_run": False, "report": report}

    def propose_branch_protection_change(self, repo: str, branch: str, rules: Dict[str, Any], approval: Optional[GitHubAdminApproval] = None) -> dict:
        action = "branch-protection.propose"
        proposal = {
            "repo": repo,
            "branch": branch,
            "rules": self._redact(rules),
            "approval_required": True,
        }
        if self.dry_run:
            self._log(action, repo, "DRY_RUN", proposal)
            return {"success": True, "dry_run": True, "proposal": proposal}
        blocked = self._require_mutation_approval(action, repo, approval)
        if blocked is not None:
            return blocked
        if self.backend and hasattr(self.backend, "apply_branch_protection"):
            result = self.backend.apply_branch_protection(repo, branch, rules)
            self._log(action, repo, "EXECUTED", result)
            return {"success": True, "dry_run": False, "result": self._redact(result)}
        self._log(action, repo, "BLOCKED_BACKEND_MISSING", proposal)
        return {"success": False, "reason": "Mutation backend not configured", "approval_required": True, "dry_run": False}

    def propose_collaborator_change(self, repo: str, username: str, permission: str = "push", operation: str = "add", approval: Optional[GitHubAdminApproval] = None) -> dict:
        action = f"collaborator.{operation}.propose"
        proposal = {
            "repo": repo,
            "username": username,
            "permission": permission,
            "operation": operation,
            "approval_required": True,
        }
        if self.dry_run:
            self._log(action, repo, "DRY_RUN", proposal)
            return {"success": True, "dry_run": True, "proposal": proposal}
        blocked = self._require_mutation_approval(action, repo, approval)
        if blocked is not None:
            return blocked
        if self.backend and hasattr(self.backend, "add_collaborator") and operation == "add":
            result = self.backend.add_collaborator(repo, username, permission)
            self._log(action, repo, "EXECUTED", result)
            return {"success": True, "dry_run": False, "result": self._redact(result)}
        if self.backend and hasattr(self.backend, "remove_collaborator") and operation == "remove":
            result = self.backend.remove_collaborator(repo, username)
            self._log(action, repo, "EXECUTED", result)
            return {"success": True, "dry_run": False, "result": self._redact(result)}
        self._log(action, repo, "BLOCKED_BACKEND_MISSING", proposal)
        return {"success": False, "reason": "Mutation backend not configured", "approval_required": True, "dry_run": False}

    def propose_repo_setting_change(self, repo: str, setting: str, value: Any, approval: Optional[GitHubAdminApproval] = None) -> dict:
        action = "repo.setting.propose"
        proposal = {"repo": repo, "setting": setting, "value": self._redact(value), "approval_required": True}
        if self.dry_run:
            self._log(action, repo, "DRY_RUN", proposal)
            return {"success": True, "dry_run": True, "proposal": proposal}
        blocked = self._require_mutation_approval(action, repo, approval)
        if blocked is not None:
            return blocked
        self._log(action, repo, "BLOCKED_BACKEND_MISSING", proposal)
        return {"success": False, "reason": "Mutation backend not configured", "approval_required": True, "dry_run": False}

    def add_collaborator(self, repo: str, username: str, permission: str = "push", approval: Optional[GitHubAdminApproval] = None) -> dict:
        """Add a collaborator to a repository."""
        action = "collaborator.add"
        if not self._triple_gate(action, repo):
            return {"success": False, "reason": "Gate denied"}
        if self.dry_run:
            self._log(action, repo, "DRY_RUN", {"username": username, "permission": permission})
            return {"success": True, "dry_run": True, "changes": {"add": {"username": username, "permission": permission}}}
        blocked = self._require_mutation_approval(action, repo, approval)
        if blocked is not None:
            return blocked
        if self.backend and hasattr(self.backend, "add_collaborator"):
            result = self.backend.add_collaborator(repo, username, permission)
            self._log(action, repo, "EXECUTED", result)
            return {"success": True, "dry_run": False, "result": self._redact(result)}
        self._log(action, repo, "BLOCKED_BACKEND_MISSING", {"username": username, "permission": permission})
        return {"success": False, "reason": "Mutation backend not configured", "approval_required": True, "dry_run": False}

    def remove_collaborator(self, repo: str, username: str, approval: Optional[GitHubAdminApproval] = None) -> dict:
        """Remove a collaborator from a repository."""
        action = "collaborator.remove"
        if not self._triple_gate(action, repo):
            return {"success": False, "reason": "Gate denied"}
        if self.dry_run:
            self._log(action, repo, "DRY_RUN", {"username": username})
            return {"success": True, "dry_run": True, "changes": {"remove": {"username": username}}}
        blocked = self._require_mutation_approval(action, repo, approval)
        if blocked is not None:
            return blocked
        if self.backend and hasattr(self.backend, "remove_collaborator"):
            result = self.backend.remove_collaborator(repo, username)
            self._log(action, repo, "EXECUTED", result)
            return {"success": True, "dry_run": False, "result": self._redact(result)}
        self._log(action, repo, "BLOCKED_BACKEND_MISSING", {"username": username})
        return {"success": False, "reason": "Mutation backend not configured", "approval_required": True, "dry_run": False}

    def set_branch_protection(self, repo: str, branch: str, rules: dict, approval: Optional[GitHubAdminApproval] = None) -> dict:
        """Configure branch protection rules."""
        action = "branch-protection.set"
        if not self._triple_gate(action, repo):
            return {"success": False, "reason": "Gate denied"}
        if self.dry_run:
            self._log(action, repo, "DRY_RUN", {"branch": branch, "rules": rules})
            return {"success": True, "dry_run": True, "changes": {"branch": branch, "rules": rules}}
        blocked = self._require_mutation_approval(action, repo, approval)
        if blocked is not None:
            return blocked
        if self.backend and hasattr(self.backend, "apply_branch_protection"):
            result = self.backend.apply_branch_protection(repo, branch, rules)
            self._log(action, repo, "EXECUTED", result)
            return {"success": True, "dry_run": False, "result": self._redact(result)}
        self._log(action, repo, "BLOCKED_BACKEND_MISSING", {"branch": branch, "rules": rules})
        return {"success": False, "reason": "Mutation backend not configured", "approval_required": True, "dry_run": False}

    def set_secret(self, repo: str, secret_name: str, secret_value: str, approval: Optional[GitHubAdminApproval] = None) -> dict:
        """Set a repository secret. Write-only: never returns the value."""
        action = "secret.set"
        if not self._triple_gate(action, repo):
            return {"success": False, "reason": "Gate denied"}
        # Hashing for audit trail – never store plaintext
        import hashlib
        secret_hash = hashlib.sha256(secret_value.encode()).hexdigest()
        if self.dry_run:
            self._log(action, repo, "DRY_RUN", {"secret_name": secret_name, "secret_hash": secret_hash})
            return {"success": True, "dry_run": True, "changes": {"set": {"secret_name": secret_name}}}
        blocked = self._require_mutation_approval(action, repo, approval)
        if blocked is not None:
            return blocked
        if self.backend and hasattr(self.backend, "set_secret"):
            result = self.backend.set_secret(repo, secret_name, secret_value)
            self._log(action, repo, "EXECUTED", {"secret_name": secret_name, "secret_hash": secret_hash})
            return {"success": True, "dry_run": False, "result": self._redact(result)}
        self._log(action, repo, "BLOCKED_BACKEND_MISSING", {"secret_name": secret_name, "secret_hash": secret_hash})
        return {"success": False, "reason": "Mutation backend not configured", "approval_required": True, "dry_run": False}

    def get_repo_info(self, repo: str) -> dict:
        """Read repository metadata (no secrets)."""
        action = "repo.info"
        if not self._triple_gate(action, repo):
            return {"success": False, "reason": "Gate denied"}
        return self.inspect_repo(repo)

    def create_repo(self, name: str, description: str = "", private: bool = True, approval: Optional[GitHubAdminApproval] = None) -> dict:
        """Create a new GitHub repository."""
        action = "repo.create"
        if not self._triple_gate(action, name):
            return {"success": False, "reason": "Gate denied"}
        if self.dry_run:
            self._log(action, name, "DRY_RUN", {"description": description, "private": private})
            return {"success": True, "dry_run": True, "changes": {"create": {"name": name, "private": private}}}
        blocked = self._require_mutation_approval(action, name, approval)
        if blocked is not None:
            return blocked
        if self.backend and hasattr(self.backend, "create_repo"):
            result = self.backend.create_repo(name, description, private)
            self._log(action, name, "EXECUTED", result)
            return {"success": True, "dry_run": False, "result": self._redact(result)}
        self._log(action, name, "BLOCKED_BACKEND_MISSING", {"private": private})
        return {"success": False, "reason": "Mutation backend not configured", "approval_required": True, "dry_run": False}

    def delete_repo(self, repo: str, double_confirm: bool = False, approval: Optional[GitHubAdminApproval] = None) -> dict:
        """Delete a repository. Requires double confirmation."""
        action = "repo.delete"
        if not double_confirm:
            self._log(action, repo, "DENIED_DOUBLE_CONFIRM")
            return {"success": False, "reason": "Double confirmation required", "double_confirm_required": True}
        if not self._triple_gate(action, repo):
            return {"success": False, "reason": "Gate denied"}
        if self.dry_run:
            self._log(action, repo, "DRY_RUN")
            return {"success": True, "dry_run": True, "changes": {"delete": {"repo": repo}}}
        blocked = self._require_mutation_approval(action, repo, approval)
        if blocked is not None:
            return blocked
        if self.backend and hasattr(self.backend, "delete_repo"):
            result = self.backend.delete_repo(repo)
            self._log(action, repo, "EXECUTED", result)
            return {"success": True, "dry_run": False, "result": self._redact(result)}
        self._log(action, repo, "BLOCKED_BACKEND_MISSING")
        return {"success": False, "reason": "Mutation backend not configured", "approval_required": True, "dry_run": False}

    def get_audit_log(self) -> list:
        """Return all audit log entries."""
        return self.audit_log.copy()
