"""
TTS API routes — synthesize speech and check status (issue #530).

Endpoints:
  GET  /api/tts/status    — engine status, hardware info, model config
  POST /api/tts/synthesize — synthesize text → base64 WAV audio

All operations are degraded-safe: if the TTS engine is unavailable, the
endpoint returns {"success": False, "degraded": True} rather than 500.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/tts", tags=["tts"])
logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.environ.get("IGRIS_PROJECT_ROOT", ".")


def _engine():
    from igris.core.tts_engine import TTSEngine
    return TTSEngine(_PROJECT_ROOT)


# ---- Request models ----

class SynthesizeRequest(BaseModel):
    text: str
    voice: Optional[str] = None  # voice profile name (optional)
    trigger: str = "chat_response"


# ---- Routes ----

@router.get("/status")
def tts_status() -> Dict[str, Any]:
    """Return TTS engine availability and hardware info."""
    try:
        engine = _engine()
        status = engine.get_status()
        return {"available": status.get("enabled", False), **status}
    except Exception as exc:
        logger.warning("TTS status check failed: %s", exc)
        return {"available": False, "error": str(exc)}


@router.post("/synthesize")
def tts_synthesize(req: SynthesizeRequest) -> Dict[str, Any]:
    """Synthesize text to audio. Returns base64-encoded WAV on success."""
    if not req.text or not req.text.strip():
        return {"success": False, "error": "text is required and must not be empty"}

    try:
        engine = _engine()
        audio_bytes = engine.synthesize(req.text)
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        return {
            "success": True,
            "audio_base64": audio_b64,
            "format": "wav",
            "text_length": len(req.text),
        }
    except Exception as exc:
        logger.warning("TTS synthesis failed: %s", exc)
        return {"success": False, "degraded": True, "error": str(exc)}
