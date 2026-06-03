"""
Interlocutor API routes — identity, delegation keys, proactive, audit (issue #526).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["interlocutor"])

_PROJECT_ROOT = os.environ.get("IGRIS_PROJECT_ROOT", ".")


def _resolver():
    from igris.core.identity_resolver import IdentityResolver
    return IdentityResolver(_PROJECT_ROOT)


def _gate():
    from igris.core.authorization_gate import AuthorizationGate
    return AuthorizationGate(_PROJECT_ROOT)


def _audit():
    from igris.core.interlocutor_audit import InterlocutorAudit
    return InterlocutorAudit()


# ---- Request models ----

class CreateProfileRequest(BaseModel):
    profile_id: str
    display_name: str
    trust_level: str = "untrusted"
    authorized_scopes: List[str] = []
    expertise_level: str = "intermediate"
    communication_style: str = "technical"


class GrantRevokeRequest(BaseModel):
    scope: str


class CreateKeyRequest(BaseModel):
    granted_by: str
    authorized_scopes: List[str]
    raw_passphrase: str
    granted_to: Optional[str] = None
    expires_in_seconds: Optional[float] = None
    single_use: bool = False


class VerifyKeyRequest(BaseModel):
    key_id: str
    raw_passphrase: str
    requested_scopes: List[str]
    bearer: Optional[str] = None


class ScanRequest(BaseModel):
    state_snapshot: Dict[str, Any]
    authorized_scopes: Optional[List[str]] = None
    trust_level: str = "trusted"


# ---- Identity routes ----

@router.get("/identity/profiles")
def list_profiles() -> List[Dict[str, Any]]:
    r = _resolver()
    return [p.to_dict() for p in r.get_all()]


@router.get("/identity/profiles/{profile_id}")
def get_profile(profile_id: str) -> Dict[str, Any]:
    r = _resolver()
    p = r.resolve(profile_id)
    return p.to_dict()


@router.post("/identity/profiles", status_code=201)
def create_profile(req: CreateProfileRequest) -> Dict[str, Any]:
    r = _resolver()
    p = r.create(
        profile_id=req.profile_id,
        display_name=req.display_name,
        trust_level=req.trust_level,
        authorized_scopes=req.authorized_scopes,
        expertise_level=req.expertise_level,
        communication_style=req.communication_style,
    )
    return p.to_dict()


@router.post("/identity/profiles/{profile_id}/scopes/grant")
def grant_scope(profile_id: str, req: GrantRevokeRequest) -> Dict[str, Any]:
    r = _resolver()
    ok = r.grant_scope(profile_id, req.scope)
    if not ok:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"profile_id": profile_id, "scope": req.scope, "action": "granted"}


@router.post("/identity/profiles/{profile_id}/scopes/revoke")
def revoke_scope(profile_id: str, req: GrantRevokeRequest) -> Dict[str, Any]:
    r = _resolver()
    ok = r.revoke_scope(profile_id, req.scope)
    if not ok:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"profile_id": profile_id, "scope": req.scope, "action": "revoked"}


# ---- Delegation key routes ----

@router.post("/delegation-keys", status_code=201)
def create_delegation_key(req: CreateKeyRequest) -> Dict[str, Any]:
    from igris.core.delegation_keys import create_key, load_keys
    try:
        grantor_scopes = ["*"]  # for API-level creation we trust the caller
        # Try to load actual grantor scopes from profile
        try:
            r = _resolver()
            p = r.resolve(req.granted_by)
            if p.trust_level == "admin":
                grantor_scopes = ["*"] + p.authorized_scopes
            else:
                grantor_scopes = list(p.authorized_scopes)
        except Exception:
            pass

        key = create_key(
            project_root=_PROJECT_ROOT,
            granted_by=req.granted_by,
            grantor_scopes=grantor_scopes,
            authorized_scopes=req.authorized_scopes,
            raw_passphrase=req.raw_passphrase,
            granted_to=req.granted_to,
            expires_in_seconds=req.expires_in_seconds,
            single_use=req.single_use,
        )
        return key.to_public_dict()  # never expose passphrase_hash or salt
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/delegation-keys/verify")
def verify_delegation_key(req: VerifyKeyRequest) -> Dict[str, Any]:
    from igris.core.delegation_keys import verify_key
    ok, reason = verify_key(
        project_root=_PROJECT_ROOT,
        key_id=req.key_id,
        raw_passphrase=req.raw_passphrase,
        requested_scopes=req.requested_scopes,
        bearer=req.bearer,
    )
    return {"allowed": ok, "reason": reason}


@router.post("/delegation-keys/{key_id}/revoke")
def revoke_delegation_key(key_id: str) -> Dict[str, Any]:
    from igris.core.delegation_keys import revoke_key
    ok = revoke_key(_PROJECT_ROOT, key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"key_id": key_id, "revoked": True}


@router.get("/delegation-keys")
def list_delegation_keys(granted_by: Optional[str] = None) -> List[Dict[str, Any]]:
    from igris.core.delegation_keys import list_keys
    keys = list_keys(_PROJECT_ROOT, granted_by=granted_by)
    return [k.to_public_dict() for k in keys]  # never expose secrets


# ---- Proactive scan ----

@router.post("/proactive/events/scan")
def proactive_scan(req: ScanRequest) -> Dict[str, Any]:
    from igris.core.proactive_engine import ProactiveEngine
    engine = ProactiveEngine(_PROJECT_ROOT)
    try:
        events = engine.scan(
            state_snapshot=req.state_snapshot,
            authorized_scopes=req.authorized_scopes,
            trust_level=req.trust_level,
        )
        return {"events": [e.__dict__ for e in events], "count": len(events)}
    except Exception as e:
        return {"events": [], "count": 0, "error": str(e)}


# ---- Audit ----

@router.get("/interlocutor/audit/recent")
def audit_recent(n: int = 50) -> Dict[str, Any]:
    a = _audit()
    return {"events": a.recent(n), "count": n}
