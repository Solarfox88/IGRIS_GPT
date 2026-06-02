"""GitHub administrative API routes.

Triple-gated: requires 'admin' scope, goes through GitHubAdminGateway
(which enforces check_authorization + judgment_layer + require_human_approval),
and all mutating operations default to dry_run=True.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from igris.core.authorization import get_current_user, require_scope
from igris.core.github_admin_gateway import GitHubAdminApproval, GitHubAdminGateway

router = APIRouter(prefix="/api/github/admin", tags=["github-admin"])
gateway = GitHubAdminGateway(dry_run=True)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CollaboratorRequest(BaseModel):
    repo: str
    username: str
    permission: str = "push"
    dry_run: bool = True
    approval: Optional[Dict[str, Any]] = None


class BranchProtectionRequest(BaseModel):
    repo: str
    branch: str = "main"
    required_reviews: int = 1
    dismiss_stale_reviews: bool = True
    require_code_owner_reviews: bool = False
    enforce_for_admins: bool = True
    dry_run: bool = True
    approval: Optional[Dict[str, Any]] = None


class SecretRequest(BaseModel):
    repo: str
    name: str
    value: str
    dry_run: bool = True
    approval: Optional[Dict[str, Any]] = None


class RepoCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    private: bool = False
    dry_run: bool = True
    approval: Optional[Dict[str, Any]] = None


class RepoDeleteRequest(BaseModel):
    repo: str
    dry_run: bool = True
    approval: Optional[Dict[str, Any]] = None


class RepoInspectionRequest(BaseModel):
    repo: str
    branch: str = "main"


class AdminPlanRequest(BaseModel):
    repo: str
    branch: Optional[str] = None
    setting: Optional[str] = None
    value: Optional[Any] = None
    username: Optional[str] = None
    permission: Optional[str] = None
    operation: Optional[str] = None
    approval: Optional[Dict[str, Any]] = None


def _approval_from_payload(payload: Optional[Dict[str, Any]]) -> Optional[GitHubAdminApproval]:
    if not payload:
        return None
    return GitHubAdminApproval(
        approved=bool(payload.get("approved", False)),
        approved_by=str(payload.get("approved_by", "")),
        ticket_id=str(payload.get("ticket_id", "")),
        rationale=str(payload.get("rationale", "")),
        approved_at=str(payload.get("approved_at", "")),
    )


# ---------------------------------------------------------------------------
# Endpoints (all mutating ops are dry_run by default; admin scope required)
# ---------------------------------------------------------------------------

@router.post("/collaborator/add")
async def add_collaborator(
    req: CollaboratorRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_scope("admin")),
) -> Dict[str, Any]:
    """Add a collaborator. Requires admin scope; dry_run=True by default."""
    if req.dry_run:
        proposal = gateway.propose_collaborator_change(req.repo, req.username, req.permission, operation="add")
        return {"status": "dry_run", "message": f"Would add {req.username} to {req.repo} with {req.permission}", "proposal": proposal.get("proposal", proposal)}
    return gateway.add_collaborator(req.repo, req.username, req.permission, approval=_approval_from_payload(req.approval))


@router.post("/collaborator/remove")
async def remove_collaborator(
    req: CollaboratorRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_scope("admin")),
) -> Dict[str, Any]:
    """Remove a collaborator. Requires admin scope; dry_run=True by default."""
    if req.dry_run:
        proposal = gateway.propose_collaborator_change(req.repo, req.username, operation="remove")
        return {"status": "dry_run", "message": f"Would remove {req.username} from {req.repo}", "proposal": proposal.get("proposal", proposal)}
    return gateway.remove_collaborator(req.repo, req.username, approval=_approval_from_payload(req.approval))


@router.post("/branch-protection/set")
async def set_branch_protection(
    req: BranchProtectionRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_scope("admin")),
) -> Dict[str, Any]:
    """Set branch protection rules. Requires admin scope; dry_run=True by default."""
    if req.dry_run:
        rules = {
            "required_reviews": req.required_reviews,
            "dismiss_stale_reviews": req.dismiss_stale_reviews,
            "require_code_owner_reviews": req.require_code_owner_reviews,
            "enforce_for_admins": req.enforce_for_admins,
        }
        proposal = gateway.propose_branch_protection_change(req.repo, req.branch, rules)
        return {"status": "dry_run", "message": f"Would set branch protection on {req.repo}/{req.branch}", "proposal": proposal.get("proposal", proposal)}
    rules = {
        "required_reviews": req.required_reviews,
        "dismiss_stale_reviews": req.dismiss_stale_reviews,
        "require_code_owner_reviews": req.require_code_owner_reviews,
        "enforce_for_admins": req.enforce_for_admins,
    }
    return gateway.set_branch_protection(req.repo, req.branch, rules, approval=_approval_from_payload(req.approval))


@router.post("/secret/set")
async def set_secret(
    req: SecretRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_scope("admin")),
) -> Dict[str, Any]:
    """Set a repository secret. Write-only: value never returned. Requires admin scope."""
    if req.dry_run:
        proposal = gateway.propose_repo_setting_change(req.repo, "secret", {"name": req.name})
        return {"status": "dry_run", "message": f"Would set secret {req.name} on {req.repo}", "proposal": proposal.get("proposal", proposal)}
    return gateway.set_secret(req.repo, req.name, req.value, approval=_approval_from_payload(req.approval))


@router.get("/repo/info")
async def get_repo_info(
    repo: str,
    user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_scope("admin")),
) -> Dict[str, Any]:
    """Get repository metadata. Read-only; does not return secrets."""
    return gateway.get_repo_info(repo)


@router.post("/repo/create")
async def create_repo(
    req: RepoCreateRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_scope("admin")),
) -> Dict[str, Any]:
    """Create a new repository. Requires admin scope; dry_run=True by default."""
    if req.dry_run:
        proposal = gateway.propose_repo_setting_change(req.name, "repo.create", {"description": req.description or "", "private": req.private})
        return {"status": "dry_run", "message": f"Would create repo {req.name}", "proposal": proposal.get("proposal", proposal)}
    return gateway.create_repo(req.name, req.description or "", req.private, approval=_approval_from_payload(req.approval))


@router.post("/repo/delete")
async def delete_repo(
    req: RepoDeleteRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_scope("admin")),
) -> Dict[str, Any]:
    """Delete a repository. Requires admin scope and double confirmation; dry_run=True by default."""
    if req.dry_run:
        proposal = gateway.propose_repo_setting_change(req.repo, "repo.delete", {"double_confirm": True})
        return {"status": "dry_run", "message": f"Would delete repo {req.repo}", "proposal": proposal.get("proposal", proposal)}
    return gateway.delete_repo(req.repo, double_confirm=True, approval=_approval_from_payload(req.approval))


@router.get("/repo/settings")
async def get_repo_settings(
    repo: str,
    user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_scope("admin")),
) -> Dict[str, Any]:
    return gateway.inspect_repo_settings(repo)


@router.get("/branch-protection")
async def get_branch_protection(
    repo: str,
    branch: str = "main",
    user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_scope("admin")),
) -> Dict[str, Any]:
    return gateway.inspect_branch_protection(repo, branch=branch)


@router.get("/collaborators")
async def get_collaborators(
    repo: str,
    user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_scope("admin")),
) -> Dict[str, Any]:
    return gateway.inspect_collaborators(repo)


@router.get("/actions-metadata")
async def get_actions_metadata(
    repo: str,
    user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_scope("admin")),
) -> Dict[str, Any]:
    return gateway.inspect_actions_metadata(repo)


@router.get("/secret-variable-metadata")
async def get_secret_variable_metadata(
    repo: str,
    user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_scope("admin")),
) -> Dict[str, Any]:
    return gateway.inspect_secret_variable_metadata(repo)


@router.post("/proposals/branch-protection")
async def propose_branch_protection(
    req: BranchProtectionRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_scope("admin")),
) -> Dict[str, Any]:
    rules = {
        "required_reviews": req.required_reviews,
        "dismiss_stale_reviews": req.dismiss_stale_reviews,
        "require_code_owner_reviews": req.require_code_owner_reviews,
        "enforce_for_admins": req.enforce_for_admins,
    }
    return gateway.propose_branch_protection_change(req.repo, req.branch, rules, approval=_approval_from_payload(req.approval))


@router.post("/proposals/collaborator")
async def propose_collaborator(
    req: CollaboratorRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_scope("admin")),
) -> Dict[str, Any]:
    return gateway.propose_collaborator_change(
        req.repo,
        req.username,
        req.permission,
        operation="add",
        approval=_approval_from_payload(req.approval),
    )


@router.post("/proposals/repo-setting")
async def propose_repo_setting(
    req: AdminPlanRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_scope("admin")),
) -> Dict[str, Any]:
    if not req.setting:
        raise HTTPException(status_code=400, detail="setting is required")
    return gateway.propose_repo_setting_change(req.repo, req.setting, req.value, approval=_approval_from_payload(req.approval))


@router.get("/audit-log")
async def get_audit_log(
    user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_scope("admin")),
) -> Dict[str, Any]:
    """Return the gateway audit trail. Requires admin scope."""
    return {"audit_log": gateway.get_audit_log()}
