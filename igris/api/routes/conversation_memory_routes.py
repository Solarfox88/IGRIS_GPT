"""Conversation memory API routes (#1240)."""
from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _project_root() -> str:
    """Return current project root, respecting live CONFIG (supports monkeypatching in tests)."""
    try:
        from igris.models.config import CONFIG
        return str(CONFIG.project_root)
    except Exception:
        return os.environ.get("IGRIS_PROJECT_ROOT", ".")


def _retriever():
    from igris.core.conversation_memory import ConversationRetriever
    return ConversationRetriever(project_root=_project_root())


def _summary_mgr():
    from igris.core.conversation_memory import ConversationSummaryManager
    return ConversationSummaryManager(project_root=_project_root())


def _effective_trust_level(interlocutor_id: str, request: Request | None = None) -> str:
    """Determine trust level for memory API requests.

    SECURITY: Does NOT auto-elevate owner/system from HTTP client claims.
    Only local requests (127.0.0.1) may access privileged memory.
    External requests claiming 'owner' or 'system' get 'untrusted'.
    """
    from igris.core.chat_interlocutor_preflight import (
        PRIVILEGED_IDS, is_trusted_local_request
    )

    # Determine if this is a local/trusted request
    is_local = False
    if request is not None:
        remote_addr = request.client.host if request.client else ""
        is_local = is_trusted_local_request(remote_addr=remote_addr)

    # Privileged IDs only allowed from local context
    if interlocutor_id in PRIVILEGED_IDS:
        if is_local:
            return "admin"  # local UI — trusted
        return "untrusted"  # non-local claiming owner/system — deny

    # For non-privileged IDs, look up the actual profile
    try:
        from igris.core.identity_resolver import IdentityResolver
        from igris.models.config import CONFIG
        ir = IdentityResolver(str(CONFIG.project_root))
        profile = ir.resolve(interlocutor_id)
        if profile:
            return str(getattr(profile, "trust_level", "untrusted")).lower()
    except Exception:
        pass

    return "untrusted"


@router.get("/conversation/recent")
def get_recent_episodes(
    request: Request,
    interlocutor_id: str = Query(default="unknown"),
    limit: int = Query(default=10, ge=1, le=100),
) -> List[Dict[str, Any]]:
    """Return recent conversation episodes for a given interlocutor (safe fields only)."""
    try:
        ret = _retriever()
        tl = _effective_trust_level(interlocutor_id, request=request)
        return ret.get_recent_episodes_safe(interlocutor_id, tl, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/conversation/summary")
def get_conversation_summary(
    request: Request,
    interlocutor_id: str = Query(default="unknown"),
) -> Dict[str, Any]:
    """Return the rolling summary for a given interlocutor."""
    try:
        mgr = _summary_mgr()
        tl = _effective_trust_level(interlocutor_id, request=request)
        summary = mgr.get_summary(interlocutor_id, tl)
        return {"interlocutor_id": interlocutor_id, "summary": summary}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/status")
def get_memory_status() -> Dict[str, Any]:
    """Return memory system health status."""
    status: Dict[str, Any] = {"enabled": False, "status": "unknown", "error": None}
    try:
        from igris.core.conversation_memory import (
            ConversationMemoryStore, ConversationRetriever, ConversationSummaryManager,
        )
        # Just check modules are importable (no instantiation needed for health check)
        _ = ConversationMemoryStore
        _ = ConversationRetriever
        _ = ConversationSummaryManager
        status["enabled"] = True
        status["status"] = "ok"
        status["modules"] = {
            "ConversationMemoryStore": "ok",
            "ConversationRetriever": "ok",
            "ConversationSummaryManager": "ok",
        }
    except Exception as exc:
        status["enabled"] = False
        status["status"] = "error"
        status["error"] = str(exc)
    return status
