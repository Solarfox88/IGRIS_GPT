"""Conversation memory API routes (#1240)."""
from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

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


def _effective_trust_level(interlocutor_id: str, trust_level: str) -> str:
    """Resolve effective trust level — 'owner' and 'system' are implicitly admin."""
    if trust_level not in ("untrusted", "unknown", ""):
        return trust_level
    if interlocutor_id in ("owner", "system"):
        return "admin"
    return trust_level


@router.get("/conversation/recent")
def get_recent_episodes(
    interlocutor_id: str = Query(default="unknown"),
    trust_level: str = Query(default="untrusted"),
    limit: int = Query(default=10, ge=1, le=100),
) -> List[Dict[str, Any]]:
    """Return recent conversation episodes for a given interlocutor (safe fields only)."""
    try:
        ret = _retriever()
        tl = _effective_trust_level(interlocutor_id, trust_level)
        return ret.get_recent_episodes_safe(interlocutor_id, tl, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/conversation/summary")
def get_conversation_summary(
    interlocutor_id: str = Query(default="unknown"),
    trust_level: str = Query(default="untrusted"),
) -> Dict[str, Any]:
    """Return the rolling summary for a given interlocutor."""
    try:
        mgr = _summary_mgr()
        tl = _effective_trust_level(interlocutor_id, trust_level)
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
