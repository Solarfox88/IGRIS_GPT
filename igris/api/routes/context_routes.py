"""Context Aggregator API routes (#1244)."""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


def _make_router():
    try:
        from fastapi import APIRouter, Request
        router = APIRouter(prefix="/api/os", tags=["context"])
    except ImportError:
        return None

    @router.post("/brief")
    async def get_brief(request: Request) -> dict:
        try:
            body = await request.json()
        except Exception:
            body = {}

        query = body.get("query", "")
        interlocutor_id = body.get("interlocutor_id", "unknown")
        trust_level = body.get("trust_level", "untrusted")

        # Anti-spoofing: apply same rule as #1239
        try:
            from igris.core.chat_interlocutor_preflight import (
                PRIVILEGED_IDS, is_trusted_local_request,
            )
            remote_addr = request.client.host if request.client else ""
            is_local = is_trusted_local_request(remote_addr=remote_addr)
            if interlocutor_id in PRIVILEGED_IDS and not is_local:
                interlocutor_id = "unknown"
                trust_level = "untrusted"
        except Exception as e:
            logger.debug("Context API: preflight check skipped: %s", e)

        try:
            from igris.core.context_aggregator import ContextAggregator
            from igris.models.config import CONFIG
            agg = ContextAggregator(project_root=str(CONFIG.project_root))
            brief = agg.build_context(
                query=query,
                interlocutor_id=interlocutor_id,
                trust_level=trust_level,
                include_rank=False,
            )
            return brief.to_dict()
        except Exception as e:
            logger.warning("Context API error: %s", e)
            return {
                "ok": False,
                "degraded": True,
                "error": str(e),
                "brief_text": "",
                "sections": [],
                "warnings": [str(e)],
            }

    @router.get("/brief")
    async def get_brief_get(request: Request) -> dict:
        """Simple GET for dashboard health check."""
        try:
            from igris.core.context_aggregator import ContextAggregator
            from igris.models.config import CONFIG
            agg = ContextAggregator(project_root=str(CONFIG.project_root))
            h = agg.healthcheck()
            return {"ok": h.get("ok"), "backends": h.get("backends", {}), "warnings": h.get("warnings", [])}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return router


router = _make_router()
