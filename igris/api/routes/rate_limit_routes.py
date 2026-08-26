"""Rate limit status endpoint (#1329).

Provides /api/rate-limit/status for users to check their own rate limit state.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rate-limit", tags=["rate-limit"])


@router.get("/status")
async def rate_limit_status(request: Request) -> JSONResponse:
    """Get the current user's rate limit status.

    Returns:
    - profile_id: the user's profile ID (or 'anonymous')
    - current: current requests in the window
    - limit: max requests per window
    - remaining: remaining requests
    - trust_level: the user's trust level
    - window_seconds: the sliding window duration
    """
    from igris.core.user_rate_limiter import get_user_rate_limiter

    # Try to extract the user's identity from the session token
    profile_id = "anonymous"

    token = _extract_bearer(request)
    if token:
        try:
            from igris.core.interlocutor_auth import AuthSessionManager
            sm = AuthSessionManager(project_root=os.environ.get("PROJECT_ROOT", "."))
            session, resolve_result = sm.resolve_session(token)
            if resolve_result.ok and session is not None:
                profile_id = session.profile_id or "anonymous"
        except (ImportError, OSError, AttributeError, TypeError, ValueError):
            pass

    limiter = get_user_rate_limiter()
    status = limiter.get_status(profile_id)
    return JSONResponse(status_code=200, content=status)


def _extract_bearer(request: Request) -> str:
    """Extract Bearer token from Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()
    return ""
