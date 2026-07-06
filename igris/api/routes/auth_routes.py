"""Auth API routes — Progressive Interlocutor Enrollment (#1272 PR 3).

Endpoints:
    POST /api/auth/enroll/start     — start enrollment, returns short-lived token
    POST /api/auth/enroll/complete  — complete enrollment with password, creates session
    POST /api/auth/login            — login with password, returns session token
    POST /api/auth/logout           — revoke session
    GET  /api/auth/me               — return profile for authenticated session
    GET  /api/auth/health           — health check for auth subsystem

SAFE BY DEFAULT:
- password raw never logged, never in response
- session token raw returned only at create/login
- enrollment token raw returned only at enroll/start
- no raw tokens in storage
- new users limited only (chat, memory_basic, read_own_profile)
- owner/system username rejected
- generic errors on login failure (no user enumeration)
- no auth escalation
"""
# NOTE: do NOT use `from __future__ import annotations` here —
# FastAPI uses runtime annotation inspection for Pydantic models.

import logging
import re
from typing import Any, Dict, List, Optional

from igris.api.write_auth import _get_auth_root

logger = logging.getLogger(__name__)

# ── Username validation ───────────────────────────────────────────────────────

_USERNAME_RE = re.compile(r'^[a-z0-9_.\-]{2,64}$')
_RESERVED_USERNAMES = frozenset({"owner", "system", "admin", "root", "igris"})

# Fields that must never appear in enrollment request
_FORBIDDEN_ENROLLMENT_FIELDS = frozenset({
    "trust_level", "authorized_scopes", "role",
    "communication_style", "expertise_level",
})


def _validate_username(username: str) -> List[str]:
    errors = []
    normalized = username.lower().strip()
    if not normalized:
        errors.append("username_required")
    elif not _USERNAME_RE.match(normalized):
        errors.append("invalid_username_format")
    if normalized in _RESERVED_USERNAMES:
        errors.append("username_reserved")
    return errors


def _validate_email(email: str) -> List[str]:
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return ["invalid_email"]
    return []


def _validate_phone(phone: str) -> List[str]:
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 6:
        return ["invalid_mobile_phone"]
    return []


def _extract_bearer_token(request) -> str:
    """Extract token from Authorization header or fallback body field."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()
    # Cookie fallback
    cookie = request.cookies.get("igris_session", "")
    if cookie:
        return cookie
    return ""


def _make_router():
    try:
        from fastapi import APIRouter, Request
        from pydantic import BaseModel
    except ImportError:
        return None

    router = APIRouter(prefix="/api/auth", tags=["auth"])

    # ── Request models ────────────────────────────────────────────────────────

    class EnrollStartRequest(BaseModel):
        username: str
        first_name: str
        last_name: str
        email: str
        mobile_phone: str
        # Explicitly declared optional with None — if present, we return error
        trust_level: Optional[str] = None
        authorized_scopes: Optional[List[str]] = None
        role: Optional[str] = None
        communication_style: Optional[str] = None
        expertise_level: Optional[str] = None

    class EnrollCompleteRequest(BaseModel):
        enrollment_token: str
        password: str
        confirm_password: str

    class LoginRequest(BaseModel):
        username: str
        password: str

    class LogoutRequest(BaseModel):
        session_token: Optional[str] = None  # body fallback for tests

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _cred_store():
        from igris.core.interlocutor_auth import AuthCredentialStore
        return AuthCredentialStore(project_root=_get_auth_root())

    def _sess_mgr():
        from igris.core.interlocutor_auth import AuthSessionManager
        return AuthSessionManager(project_root=_get_auth_root())

    def _enroll_store():
        from igris.core.interlocutor_auth import EnrollmentStore
        return EnrollmentStore(project_root=_get_auth_root())

    def _resolver():
        from igris.core.identity_resolver import IdentityResolver
        return IdentityResolver(_get_auth_root())

    # ── POST /api/auth/enroll/start ───────────────────────────────────────────

    @router.post("/enroll/start")
    async def enroll_start(req: EnrollStartRequest):
        # Check forbidden fields
        forbidden_present = []
        for f in _FORBIDDEN_ENROLLMENT_FIELDS:
            if getattr(req, f, None) is not None:
                forbidden_present.append(f)
        if forbidden_present:
            return {"ok": False, "error": "forbidden_field",
                    "forbidden_fields": forbidden_present}

        username = req.username.lower().strip()
        errors = _validate_username(username)
        errors += _validate_email(req.email)
        errors += _validate_phone(req.mobile_phone)
        if not req.first_name or not req.first_name.strip():
            errors.append("first_name_required")
        if not req.last_name or not req.last_name.strip():
            errors.append("last_name_required")
        if errors:
            return {"ok": False, "error": "validation_failed", "details": errors}

        # Check for duplicates in IdentityResolver
        try:
            ir = _resolver()
            existing = ir._load()
            from igris.core.identity_resolver import BUILTIN_PROFILES
            if username in existing or username in BUILTIN_PROFILES:
                return {"ok": False, "error": "username_taken"}
        except Exception as exc:
            logger.warning("enroll_start: identity check failed: %s", exc)
            return {"ok": False, "error": "internal_error"}

        # Check for duplicates in AuthCredentialStore
        try:
            cs = _cred_store()
            if cs.get_credential(username) is not None:
                return {"ok": False, "error": "username_taken"}
        except Exception as exc:
            logger.warning("enroll_start: credential check failed: %s", exc)
            return {"ok": False, "error": "internal_error"}

        # Check for pending (not yet completed) enrollment for same username
        try:
            import datetime
            es_check = _enroll_store()
            for e in es_check._enrollments.values():
                if (
                    e.profile_id == username
                    and not e.used
                    and e.expires_at > datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()
                ):
                    return {"ok": False, "error": "username_taken"}
        except Exception as exc:
            logger.warning("enroll_start: pending enrollment check failed: %s", exc)

        # Create pending enrollment
        try:
            es = _enroll_store()
            r = es.create_pending(
                profile_id=username,
                first_name=req.first_name.strip(),
                last_name=req.last_name.strip(),
                email=req.email,
                mobile_phone=req.mobile_phone,
            )
        except Exception as exc:
            logger.warning("enroll_start: create_pending failed: %s", exc)
            return {"ok": False, "error": "internal_error"}

        if not r.ok:
            return {"ok": False, "error": "enrollment_create_failed",
                    "details": r.errors}

        logger.info("enroll_start: pending enrollment created for profile_id=%s", username)
        return {
            "ok": True,
            "enrollment_token": r.session_token,  # raw token, returned once
            "expires_at": r.expires_at,
            "profile_id": username,
        }

    # ── POST /api/auth/enroll/complete ────────────────────────────────────────

    @router.post("/enroll/complete")
    async def enroll_complete(req: EnrollCompleteRequest):
        # Extract raw values early (before any early-return, before del req)
        raw_enrollment_token = req.enrollment_token
        raw_password = req.password

        # Validate password match first (before any storage access)
        if raw_password != req.confirm_password:
            return {"ok": False, "error": "password_mismatch"}

        # Resolve enrollment token
        try:
            es = _enroll_store()
            enrollment, resolve_r = es.resolve_token(raw_enrollment_token)
        except Exception as exc:
            logger.warning("enroll_complete: resolve_token failed: %s", exc)
            return {"ok": False, "error": "invalid_enrollment_token"}

        if not resolve_r.ok or enrollment is None:
            err = resolve_r.errors[0] if resolve_r.errors else "invalid_enrollment_token"
            if "expired" in err:
                return {"ok": False, "error": "expired_enrollment_token"}
            return {"ok": False, "error": "invalid_enrollment_token"}

        profile_id = enrollment.profile_id

        # Create InterlocutorProfile (limited)
        try:
            ir = _resolver()
            ir.create_enrolled_limited_profile(
                profile_id=profile_id,
                first_name=enrollment.first_name,
                last_name=enrollment.last_name,
            )
        except Exception as exc:
            logger.warning("enroll_complete: create_profile failed for %s: %s", profile_id, exc)
            return {"ok": False, "error": "create_failed"}

        # Create AuthCredential (password consumed here)
        try:
            cs = _cred_store()
            cred_r = cs.create_credential(
                profile_id=profile_id,
                email=enrollment.email,
                mobile_phone=enrollment.mobile_phone,
                raw_password=raw_password,
            )
        except Exception as exc:
            logger.warning("enroll_complete: create_credential failed for %s: %s", profile_id, exc)
            return {"ok": False, "error": "create_failed"}

        if not cred_r.ok:
            err = cred_r.errors[0] if cred_r.errors else "create_failed"
            return {"ok": False, "error": err}

        # Mark enrollment token as used (best-effort; token expires naturally too)
        try:
            es.mark_used(raw_enrollment_token)
        except Exception as exc:
            logger.debug("enroll_complete: mark_used best-effort failed: %s", exc)

        # Create session
        try:
            sm = _sess_mgr()
            sess_r = sm.create_session(profile_id=profile_id)
        except Exception as exc:
            logger.warning("enroll_complete: create_session failed for %s: %s", profile_id, exc)
            return {"ok": False, "error": "session_create_failed"}

        if not sess_r.ok:
            return {"ok": False, "error": "session_create_failed", "details": sess_r.errors}

        logger.info("enroll_complete: enrollment complete for profile_id=%s", profile_id)
        return {
            "ok": True,
            "profile_id": profile_id,
            "session_token": sess_r.session_token,  # raw token, returned once
            "expires_at": sess_r.expires_at,
        }

    # ── POST /api/auth/login ──────────────────────────────────────────────────

    @router.post("/login")
    async def login(req: LoginRequest):
        username = req.username.lower().strip()
        logger.info("auth login attempt for profile_id=%s", username)

        try:
            cs = _cred_store()
            verify_r = cs.verify_login(username, req.password)
        except Exception as exc:
            logger.warning("login: verify_login error for %s: %s", username, exc)
            return {"ok": False, "error": "invalid_credentials"}

        if not verify_r.ok:
            return {"ok": False, "error": "invalid_credentials"}

        try:
            sm = _sess_mgr()
            sess_r = sm.create_session(profile_id=username)
        except Exception as exc:
            logger.warning("login: create_session failed for %s: %s", username, exc)
            return {"ok": False, "error": "session_create_failed"}

        if not sess_r.ok:
            return {"ok": False, "error": "session_create_failed"}

        logger.info("auth login success for profile_id=%s", username)
        return {
            "ok": True,
            "profile_id": username,
            "session_token": sess_r.session_token,  # raw token, returned once
            "expires_at": sess_r.expires_at,
        }

    # ── POST /api/auth/logout ─────────────────────────────────────────────────

    @router.post("/logout")
    async def logout(request: Request, body: LogoutRequest = None):
        token = _extract_bearer_token(request)
        if not token and body and body.session_token:
            token = body.session_token
        if not token:
            return {"ok": False, "error": "invalid_session"}

        try:
            sm = _sess_mgr()
            r = sm.revoke_session(token)
        except Exception as exc:
            logger.warning("logout: revoke_session failed: %s", exc)
            return {"ok": False, "error": "invalid_session"}

        if not r.ok:
            return {"ok": False, "error": "invalid_session"}
        return {"ok": True}

    # ── GET /api/auth/me ──────────────────────────────────────────────────────

    @router.get("/me")
    async def me(request: Request):
        token = _extract_bearer_token(request)
        if not token:
            return {"ok": False, "error": "authentication_required"}

        try:
            sm = _sess_mgr()
            session, resolve_r = sm.resolve_session(token)
        except Exception as exc:
            logger.warning("me: resolve_session failed: %s", exc)
            return {"ok": False, "error": "invalid_session"}

        if not resolve_r.ok or session is None:
            return {"ok": False, "error": "invalid_session"}

        try:
            ir = _resolver()
            profile = ir.resolve(session.profile_id)
        except Exception as exc:
            logger.warning("me: resolve profile failed for %s: %s", session.profile_id, exc)
            return {"ok": False, "error": "profile_not_found"}

        return {
            "ok": True,
            "profile": {
                "profile_id": profile.profile_id,
                "display_name": profile.display_name,
                "first_name": profile.first_name,
                "last_name": profile.last_name,
                "trust_level": profile.trust_level,
                "authorized_scopes": list(profile.authorized_scopes),
                "communication_style": profile.communication_style,
                "expertise_level": profile.expertise_level,
            },
        }

    # ── GET /api/auth/health ──────────────────────────────────────────────────

    @router.get("/health")
    async def auth_health():
        try:
            cs = _cred_store()
            sm = _sess_mgr()
            es = _enroll_store()
            return {
                "ok": True,
                "credentials": cs.healthcheck(),
                "sessions": sm.healthcheck(),
                "enrollments": es.healthcheck(),
            }
        except Exception as exc:
            logger.warning("auth_health failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    return router


router = _make_router()
