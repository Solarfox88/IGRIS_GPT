"""TTS synthesis API route — safe, degraded if model unavailable."""
from __future__ import annotations
from typing import Any
import logging

logger = logging.getLogger(__name__)

def _make_router():
    try:
        from fastapi import APIRouter
        router = APIRouter(prefix="/api/tts", tags=["tts"])
    except ImportError:
        return None

    @router.post("/synthesize")
    async def synthesize(body: dict) -> dict:
        text = (body.get("text") or "").strip()
        if not text:
            return {"success": False, "error": "text required"}
        if len(text) > 4096:
            return {"success": False, "error": "text too long (max 4096 chars)"}
        try:
            import os
            from igris.core.tts_engine import TTSEngine
            project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            engine = TTSEngine(project_root)
            available = engine.is_available() if hasattr(engine, "is_available") else True
            if not available:
                return {"success": False, "degraded": True, "reason": "model not available"}
            result = engine.synthesize(text)
            if result is None:
                return {"success": False, "degraded": True, "reason": "model not available"}
            # Return length info, never raw audio bytes in JSON
            return {"success": True, "artifact": "audio/wav", "size_bytes": len(result)}
        except Exception as e:
            logger.warning("TTS synthesize error: %s", e)
            return {"success": False, "degraded": True, "reason": str(e)}

    @router.get("/status")
    async def status() -> dict:
        try:
            import os
            from igris.core.tts_engine import TTSEngine
            project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            engine = TTSEngine(project_root)
            if hasattr(engine, "get_status"):
                return {"available": engine.is_available(), **engine.get_status()}
            available = engine.is_available() if hasattr(engine, "is_available") else True
            return {"available": available}
        except Exception as e:
            return {"available": False, "reason": str(e)}

    return router

router = _make_router()
