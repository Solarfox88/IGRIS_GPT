"""Write endpoint authentication gate — P0 fix #1293.

All endpoints with side effects MUST call require_write_auth_or_raise(request)
before performing any action.

Policy:
  No token / invalid token  -> HTTP 401
  Valid limited user         -> HTTP 403
  Valid admin/owner          -> allowed
"""
from __future__ import annotations
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)
_WRITE_ALLOWED_TRUST_LEVELS = frozenset({"admin", "owner", "system"})


def _get_auth_root() -> str:
    """Return the auth-store project root, resolved lazily at call time.

    Reads IGRIS_PROJECT_ROOT from the live environment so that env changes
    after module import (e.g. in tests) are always respected.
    Fallback: "." (current working directory).
    """
    return os.environ.get("IGRIS_PROJECT_ROOT") or "."


@dataclass
class WriteAuthResult:
    allowed: bool
    trust_level: str = "untrusted"
    username: Optional[str] = None
    error_code: str = ""
    error_message: str = ""
    http_status: int = 200

    def as_http_exception(self):
        from fastapi import HTTPException
        return HTTPException(
            status_code=self.http_status,
            detail={"ok": False, "error": self.error_code, "message": self.error_message},
        )


def _extract_bearer(request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()
    return ""


async def require_write_auth(request) -> "WriteAuthResult":
    token = _extract_bearer(request)
    if not token:
        return WriteAuthResult(
            allowed=False, trust_level="untrusted",
            error_code="authentication_required",
            error_message="Authentication required. Include Authorization: Bearer <token>.",
            http_status=401,
        )

    project_root = _get_auth_root()
    try:
        from igris.core.interlocutor_auth import AuthSessionManager
        sm = AuthSessionManager(project_root=project_root)
        session, resolve_result = sm.resolve_session(token)
        if not resolve_result.ok or session is None:
            return WriteAuthResult(
                allowed=False, trust_level="untrusted",
                error_code="authentication_required",
                error_message="Session not found or expired.",
                http_status=401,
            )
        username = resolve_result.profile_id or session.profile_id or ""
    except Exception as exc:
        logger.warning("write_auth session error: %s", exc)
        return WriteAuthResult(
            allowed=False, trust_level="untrusted",
            error_code="authentication_required",
            error_message="Session validation failed.",
            http_status=401,
        )

    trust_level = "untrusted"
    try:
        from igris.core.identity_resolver import IdentityResolver
        ir = IdentityResolver(project_root=project_root)
        profile = ir.resolve(username)
        trust_level = str(getattr(profile, "trust_level", "untrusted")).lower()
    except Exception as exc:
        logger.warning("write_auth identity error for %s: %s", username, exc)
        trust_level = "limited"

    if trust_level not in _WRITE_ALLOWED_TRUST_LEVELS:
        return WriteAuthResult(
            allowed=False, trust_level=trust_level, username=username,
            error_code="scope_denied",
            error_message=(
                "User '{}' (trust={}) cannot perform write operations. "
                "Required: admin or owner."
            ).format(username, trust_level),
            http_status=403,
        )

    return WriteAuthResult(allowed=True, trust_level=trust_level, username=username)


async def require_write_auth_or_raise(request) -> "WriteAuthResult":
    result = await require_write_auth(request)
    if not result.allowed:
        raise result.as_http_exception()
    return result
