"""
Patch proposal engine for IGRIS_GPT.

Manages safe, controlled code modification proposals with validation,
diff preview, and guarded application.
"""

from __future__ import annotations

import difflib
import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

from igris.core.safety import (
    check_path_access,
    is_sensitive_filename,
    is_runtime_artifact,
    detect_secret_like_content,
    redact_secrets,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PATCHES_DIR = ".igris/patches"
_MAX_FILE_SIZE = 500_000  # 500 KB max for patch content
_BLOCKED_EXTENSIONS = {
    ".pem", ".key", ".p12", ".pfx", ".jks", ".pyc", ".pyo",
    ".so", ".dll", ".exe", ".bin", ".whl", ".tar", ".gz", ".zip",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
}
_BLOCKED_DIRS = {
    ".env", ".git", ".igris", "logs", "__pycache__", ".pytest_cache",
    ".ruff_cache", ".venv", ".venv_linux", "node_modules",
}

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class PatchFileChange:
    path: str
    action: str  # create | modify | delete
    before: Optional[str] = None
    after: Optional[str] = None
    diff: str = ""
    reason: str = ""


@dataclass
class PatchValidationResult:
    valid: bool = True
    reasons: List[str] = field(default_factory=list)
    blocked_paths: List[str] = field(default_factory=list)
    secret_findings: List[str] = field(default_factory=list)
    risk: str = "low"


@dataclass
class PatchProposal:
    id: str = ""
    title: str = ""
    description: str = ""
    task_id: Optional[str] = None
    status: str = "proposed"  # proposed | validated | applied | rejected
    risk: str = "low"  # low | medium | high
    files: List[PatchFileChange] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    validation: Optional[PatchValidationResult] = None
    safety_notes: str = ""
    rollback_notes: str = ""
    reject_reason: str = ""


# ---------------------------------------------------------------------------
# Diff generation
# ---------------------------------------------------------------------------


def generate_unified_diff(before: str, after: str, path: str) -> str:
    """Generate a unified diff between two strings."""
    before_lines = (before or "").splitlines(keepends=True)
    after_lines = (after or "").splitlines(keepends=True)
    diff = difflib.unified_diff(
        before_lines, after_lines,
        fromfile=f"a/{path}", tofile=f"b/{path}",
        lineterm="",
    )
    return "\n".join(diff)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _patches_dir(project_root: str = ".") -> Path:
    d = Path(project_root) / _PATCHES_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_proposal(proposal: PatchProposal, project_root: str = ".") -> None:
    d = _patches_dir(project_root)
    data = _proposal_to_dict(proposal)
    (d / f"{proposal.id}.json").write_text(json.dumps(data, indent=2))


def _proposal_to_dict(proposal: PatchProposal) -> dict:
    d = {
        "id": proposal.id,
        "title": proposal.title,
        "description": proposal.description,
        "task_id": proposal.task_id,
        "status": proposal.status,
        "risk": proposal.risk,
        "files": [
            {
                "path": f.path,
                "action": f.action,
                "before": f.before,
                "after": f.after,
                "diff": f.diff,
                "reason": f.reason,
            }
            for f in proposal.files
        ],
        "created_at": proposal.created_at,
        "updated_at": proposal.updated_at,
        "validation": asdict(proposal.validation) if proposal.validation else None,
        "safety_notes": proposal.safety_notes,
        "rollback_notes": proposal.rollback_notes,
        "reject_reason": proposal.reject_reason,
    }
    return d


def _dict_to_proposal(d: dict) -> PatchProposal:
    files = [
        PatchFileChange(
            path=f["path"],
            action=f["action"],
            before=f.get("before"),
            after=f.get("after"),
            diff=f.get("diff", ""),
            reason=f.get("reason", ""),
        )
        for f in d.get("files", [])
    ]
    validation = None
    if d.get("validation"):
        v = d["validation"]
        validation = PatchValidationResult(
            valid=v.get("valid", False),
            reasons=v.get("reasons", []),
            blocked_paths=v.get("blocked_paths", []),
            secret_findings=v.get("secret_findings", []),
            risk=v.get("risk", "low"),
        )
    return PatchProposal(
        id=d["id"],
        title=d.get("title", ""),
        description=d.get("description", ""),
        task_id=d.get("task_id"),
        status=d.get("status", "proposed"),
        risk=d.get("risk", "low"),
        files=files,
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
        validation=validation,
        safety_notes=d.get("safety_notes", ""),
        rollback_notes=d.get("rollback_notes", ""),
        reject_reason=d.get("reject_reason", ""),
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def create_patch_proposal(
    title: str,
    description: str,
    files: List[Dict],
    task_id: Optional[str] = None,
    project_root: str = ".",
) -> PatchProposal:
    """Create a new patch proposal."""
    proposal = PatchProposal(
        id=str(uuid.uuid4())[:12],
        title=title,
        description=description,
        task_id=task_id,
        status="proposed",
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        updated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )

    root = Path(project_root).resolve()
    for fc in files:
        path = fc.get("path", "")
        action = fc.get("action", "modify")
        after = fc.get("after", "")
        before = fc.get("before")

        # Read current content for modify
        if action == "modify" and before is None:
            target = root / path
            if target.exists() and target.is_file():
                try:
                    before = target.read_text(errors="replace")
                except Exception:
                    before = ""

        diff = generate_unified_diff(before or "", after or "", path)

        proposal.files.append(PatchFileChange(
            path=path,
            action=action,
            before=before,
            after=after,
            diff=diff,
            reason=fc.get("reason", ""),
        ))

    _save_proposal(proposal, project_root)
    return proposal


def list_patch_proposals(project_root: str = ".") -> List[Dict]:
    """List all patch proposals."""
    d = _patches_dir(project_root)
    proposals = []
    for f in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text())
            proposals.append({
                "id": data["id"],
                "title": data.get("title", ""),
                "status": data.get("status", "proposed"),
                "risk": data.get("risk", "low"),
                "file_count": len(data.get("files", [])),
                "created_at": data.get("created_at", ""),
                "task_id": data.get("task_id"),
            })
        except Exception:
            continue
    return proposals


def load_patch_proposal(proposal_id: str, project_root: str = ".") -> Optional[PatchProposal]:
    """Load a single patch proposal."""
    d = _patches_dir(project_root)
    path = d / f"{proposal_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return _dict_to_proposal(data)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _check_path_safety(file_path: str, project_root: str) -> List[str]:
    """Check a single file path for safety issues."""
    issues = []
    root = Path(project_root).resolve()
    target = (root / file_path).resolve()

    # Path traversal
    if not check_path_access(target, root):
        issues.append(f"Path traversal: {file_path}")

    # Blocked directories
    parts = Path(file_path).parts
    for part in parts:
        if part in _BLOCKED_DIRS:
            issues.append(f"Blocked directory: {part} in {file_path}")
        if part.endswith(".egg-info"):
            issues.append(f"Blocked directory: {part} in {file_path}")

    # Sensitive filename
    name = Path(file_path).name
    if is_sensitive_filename(name):
        issues.append(f"Sensitive filename: {name}")

    # Blocked extension
    ext = Path(file_path).suffix.lower()
    if ext in _BLOCKED_EXTENSIONS:
        issues.append(f"Blocked extension: {ext} in {file_path}")

    # Runtime artifact
    if is_runtime_artifact(Path(file_path)):
        issues.append(f"Runtime artifact: {file_path}")

    return issues


def _check_content_safety(content: str, file_path: str) -> List[str]:
    """Check content for secrets and safety issues."""
    issues = []
    if not content:
        return issues

    if len(content) > _MAX_FILE_SIZE:
        issues.append(f"Content too large: {len(content)} bytes (max {_MAX_FILE_SIZE})")

    if detect_secret_like_content(content):
        issues.append(f"Secret-like content detected in {file_path}")

    return issues


def validate_patch_proposal(
    proposal: PatchProposal,
    project_root: str = ".",
) -> PatchValidationResult:
    """Validate a patch proposal against safety rules."""
    result = PatchValidationResult(valid=True, risk="low")

    for fc in proposal.files:
        # Check path safety
        path_issues = _check_path_safety(fc.path, project_root)
        for issue in path_issues:
            result.reasons.append(issue)
            result.blocked_paths.append(fc.path)
            result.valid = False

        # Delete action is blocked / high-risk
        if fc.action == "delete":
            result.reasons.append(f"Delete action not allowed: {fc.path}")
            result.blocked_paths.append(fc.path)
            result.valid = False
            result.risk = "high"

        # Check content for secrets
        if fc.after:
            content_issues = _check_content_safety(fc.after, fc.path)
            for issue in content_issues:
                if "Secret" in issue:
                    result.secret_findings.append(issue)
                result.reasons.append(issue)
                result.valid = False
                result.risk = "high"

        # Unknown action
        if fc.action not in ("create", "modify", "delete"):
            result.reasons.append(f"Unknown action: {fc.action} for {fc.path}")
            result.valid = False

    # Assess overall risk
    if result.secret_findings:
        result.risk = "high"
    elif result.blocked_paths:
        result.risk = "high"
    elif len(proposal.files) > 5:
        result.risk = "medium"

    # Update proposal
    proposal.validation = result
    proposal.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if result.valid:
        proposal.status = "validated"
        proposal.safety_notes = "All safety checks passed"
    else:
        proposal.status = "proposed"
        proposal.safety_notes = f"Validation failed: {len(result.reasons)} issue(s)"

    _save_proposal(proposal, project_root)
    return result


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_patch_proposal(
    proposal_id: str,
    project_root: str = ".",
) -> Dict:
    """Apply a validated patch proposal. Returns result dict."""
    proposal = load_patch_proposal(proposal_id, project_root)
    if proposal is None:
        return {"success": False, "error": "Proposal not found"}

    if proposal.status == "applied":
        return {"success": False, "error": "Proposal already applied"}

    if proposal.status == "rejected":
        return {"success": False, "error": "Proposal was rejected"}

    if not proposal.validation or not proposal.validation.valid:
        return {"success": False, "error": "Proposal not validated or validation failed. Run validate first."}

    root = Path(project_root).resolve()
    applied_files = []
    rollback_info = []

    for fc in proposal.files:
        target = root / fc.path
        if fc.action == "delete":
            return {"success": False, "error": f"Delete action not allowed: {fc.path}"}

        if fc.action == "create":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(fc.after or "")
            applied_files.append({"path": fc.path, "action": "create"})
            rollback_info.append(f"Delete {fc.path}")

        elif fc.action == "modify":
            if target.exists():
                rollback_info.append(f"Restore {fc.path} from before content")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(fc.after or "")
            applied_files.append({"path": fc.path, "action": "modify"})

    proposal.status = "applied"
    proposal.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    proposal.rollback_notes = "; ".join(rollback_info) if rollback_info else "No rollback needed"
    _save_proposal(proposal, project_root)

    return {
        "success": True,
        "applied_files": applied_files,
        "rollback_notes": proposal.rollback_notes,
    }


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------


def reject_patch_proposal(
    proposal_id: str,
    reason: str = "",
    project_root: str = ".",
) -> Dict:
    """Reject a patch proposal."""
    proposal = load_patch_proposal(proposal_id, project_root)
    if proposal is None:
        return {"success": False, "error": "Proposal not found"}

    if proposal.status == "applied":
        return {"success": False, "error": "Cannot reject an applied proposal"}

    proposal.status = "rejected"
    proposal.reject_reason = reason
    proposal.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _save_proposal(proposal, project_root)
    return {"success": True, "status": "rejected", "reason": reason}
