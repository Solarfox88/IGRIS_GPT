"""Chat streaming via SSE + session tier selector.

Provides Server-Sent Events streaming for chat responses and a
tier selector to choose between auto/local/fallback providers.

Inspired by IGRIS_DEVIN SSE streaming and tier selector.
No command execution. No WRITE_FILE. No Vast tier active.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

from igris.core.chat_engine import (
    _build_fallback_response,
    _try_ollama,
    check_ollama_available,
)
from igris.core.chat_personality import (
    IGRIS_SYSTEM_PROMPT,
    detect_intent,
    get_grounded_response,
    get_suggested_actions,
)
from igris.core.safety import redact_secrets
from igris.models.config import CONFIG


# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

AVAILABLE_TIERS = ("auto", "local", "fallback")


@dataclass
class TierConfig:
    """Session tier configuration."""
    tier: str = "auto"  # auto | local | fallback
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "description": self.description,
            "available_tiers": list(AVAILABLE_TIERS),
        }


# Module-level current tier
_current_tier = TierConfig(tier="auto", description="Automatic provider selection")


def get_current_tier() -> TierConfig:
    """Get the current session tier."""
    return _current_tier


def set_tier(tier: str) -> TierConfig:
    """Set the session tier. Returns updated config."""
    global _current_tier
    if tier not in AVAILABLE_TIERS:
        raise ValueError(f"Invalid tier '{tier}'. Must be one of: {AVAILABLE_TIERS}")
    descriptions = {
        "auto": "Automatic provider selection (local → fallback → deterministic)",
        "local": "Force local LLM (Ollama). Fails to deterministic if unavailable.",
        "fallback": "Force fallback provider (OpenAI). Fails to deterministic if unavailable.",
    }
    _current_tier = TierConfig(tier=tier, description=descriptions.get(tier, ""))
    return _current_tier


# ---------------------------------------------------------------------------
# Streaming helpers
# ---------------------------------------------------------------------------

@dataclass
class StreamChunk:
    """A single chunk of a streaming response."""
    type: str = "content"  # content | metadata | done | error
    text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_sse(self) -> str:
        """Format as SSE event."""
        data = json.dumps({"type": self.type, "text": self.text, "metadata": self.metadata})
        return f"data: {data}\n\n"


def chat_stream_sync(
    message: str,
    history: Optional[List[Dict[str, str]]] = None,
    system_prompt: Optional[str] = None,
) -> List[StreamChunk]:
    """Synchronous chat that returns a list of stream chunks.

    For actual SSE streaming, the async generator wraps this.
    The underlying providers don't support true token-level streaming
    yet, so we simulate it by chunking the response.
    """
    if history is None:
        history = []

    tier = _current_tier.tier
    chunks: List[StreamChunk] = []

    t0 = time.monotonic()

    # IGRIS personality: check for known operational intents first
    intent = detect_intent(message)
    if intent is not None:
        grounded = get_grounded_response(intent)
        if grounded is not None:
            latency_ms = int((time.monotonic() - t0) * 1000)
            response_text = redact_secrets(grounded)
            chunk_size = 80
            for i in range(0, len(response_text), chunk_size):
                chunks.append(StreamChunk(type="content", text=response_text[i:i + chunk_size]))
            chunks.append(StreamChunk(
                type="done",
                text="",
                metadata={
                    "provider": "igris_personality",
                    "model": "capability_grounding",
                    "fallback_used": False,
                    "latency_ms": latency_ms,
                    "routing_reason": f"IGRIS-aware grounded response for intent: {intent}",
                    "tier": tier,
                    "intent_detected": intent,
                    "suggested_actions": get_suggested_actions(intent),
                },
            ))
            return chunks

    # Build messages
    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    else:
        messages.append({"role": "system", "content": IGRIS_SYSTEM_PROMPT})
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    provider = CONFIG.local_llm.provider
    model = CONFIG.local_llm.model
    base_url = CONFIG.local_llm.base_url or "http://127.0.0.1:11434"
    fallback_used = False
    routing_reason = ""
    response_text = None

    if tier in ("auto", "local"):
        response_text = _try_ollama(messages, model, base_url)
        if response_text:
            routing_reason = f"local LLM ({tier} tier)"

    if response_text is None and tier in ("auto", "fallback"):
        if CONFIG.fallback_llm.api_key:
            from igris.core.chat_engine import _try_openai_fallback
            response_text = _try_openai_fallback(messages)
            if response_text:
                provider = CONFIG.fallback_llm.provider
                model = CONFIG.fallback_llm.model
                fallback_used = True
                routing_reason = f"{CONFIG.fallback_llm.provider} fallback ({tier} tier)"

    if response_text is None and tier in ("auto", "fallback"):
        if CONFIG.openai_chat_fallback.api_key:
            from igris.core.chat_engine import _try_openai_secondary_fallback
            response_text = _try_openai_secondary_fallback(messages)
            if response_text:
                provider = CONFIG.openai_chat_fallback.provider
                model = CONFIG.openai_chat_fallback.model
                fallback_used = True
                routing_reason = f"OpenAI secondary fallback ({tier} tier)"

    if response_text is None:
        response_text = _build_fallback_response(message)
        provider = "deterministic"
        model = "fallback"
        fallback_used = True
        routing_reason = f"deterministic fallback ({tier} tier)"

    latency_ms = int((time.monotonic() - t0) * 1000)
    response_text = redact_secrets(response_text)

    # Chunk the response into pieces for streaming simulation
    chunk_size = 80
    for i in range(0, len(response_text), chunk_size):
        chunk_text = response_text[i:i + chunk_size]
        chunks.append(StreamChunk(type="content", text=chunk_text))

    # Final metadata chunk
    chunks.append(StreamChunk(
        type="done",
        text="",
        metadata={
            "provider": provider,
            "model": model,
            "fallback_used": fallback_used,
            "latency_ms": latency_ms,
            "routing_reason": routing_reason,
            "tier": tier,
        },
    ))

    return chunks


def get_tier_availability() -> Dict[str, Any]:
    """Check which tiers are actually available."""
    ollama_ok = check_ollama_available()
    has_fallback_key = bool(CONFIG.fallback_llm.api_key)

    return {
        "current_tier": _current_tier.tier,
        "tiers": {
            "auto": {
                "available": True,
                "description": "Automatic: tries local → fallback → deterministic",
            },
            "local": {
                "available": ollama_ok,
                "description": "Local Ollama LLM",
                "status": "online" if ollama_ok else "offline",
            },
            "fallback": {
                "available": has_fallback_key,
                "description": "OpenAI fallback",
                "status": "configured" if has_fallback_key else "no API key",
            },
        },
    }
