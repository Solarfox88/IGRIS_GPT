"""Conversation memory API routes (#1240)."""
from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/memory", tags=["memory"])

_PROJECT_ROOT = os.environ.get("IGRIS_PROJECT_ROOT", ".")


def _retriever():
    from igris.core.conversation_memory import ConversationRetriever
    return ConversationRetriever(project_root=_PROJECT_ROOT)


def _summary_mgr():
    from igris.core.conversation_memory import ConversationSummaryManager
    return ConversationSummaryManager(project_root=_PROJECT_ROOT)


@router.get("/conversation/recent")
def get_recent_episodes(
    interlocutor_id: str = Query(default="unknown"),
    trust_level: str = Query(default="untrusted"),
    limit: int = Query(default=10, ge=1, le=100),
) -> List[Dict[str, Any]]:
    """Return recent conversation episodes for a given interlocutor (safe fields only)."""
    try:
        ret = _retriever()
        return ret.get_recent_episodes_safe(interlocutor_id, trust_level, limit=limit)
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
        summary = mgr.get_summary(interlocutor_id, trust_level)
        return {"interlocutor_id": interlocutor_id, "summary": summary}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/status")
def get_memory_status() -> Dict[str, Any]:
    """Return memory system health status."""
    status: Dict[str, Any] = {"enabled": False, "status": "unknown", "error": None}
    try:
        from igris.core.long_term_memory import LongTermMemory
        from igris.core.conversation_memory import (
            ConversationMemoryStore, ConversationRetriever, ConversationSummaryManager,
        )
        # Quick instantiation check
        ltm = LongTermMemory(base_path=None)  # uses default path — read-only check
        status["enabled"] = True
        status["status"] = "ok"
        status["modules"] = {
            "LongTermMemory": "ok",
            "ConversationMemoryStore": "ok",
            "ConversationRetriever": "ok",
            "ConversationSummaryManager": "ok",
        }
    except Exception as exc:
        status["enabled"] = False
        status["status"] = "error"
        status["error"] = str(exc)
    return status
