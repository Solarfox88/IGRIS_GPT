"""
Chat engine with Ollama local LLM support and deterministic fallback.

Attempts to use the configured local LLM provider (Ollama by default).
If the LLM is unavailable, returns a contextual deterministic response
so that the application never crashes.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from igris.models.config import CONFIG
from igris.core.chat_personality import (
    IGRIS_SYSTEM_PROMPT,
    detect_intent,
    get_grounded_response,
    get_suggested_actions,
)

# Keyword-based contextual fallback responses
_FALLBACK_HINTS: list[tuple[list[str], str]] = [
    (["status", "stato", "health", "salute"],
     "Check the system status via /api/status, /api/health and /api/readiness endpoints."),
    (["task", "tasks", "compito"],
     "You can manage tasks via /api/tasks (GET to list, POST to create). "
     "Complete with /api/tasks/{id}/complete and block with /api/tasks/{id}/block."),
    (["test", "tests", "pytest"],
     "Run tests through the Terminal tab using the run_tests command, "
     "or call POST /api/tests/run. Results are stored in /api/reports/recent."),
    (["safety", "security", "sicurezza"],
     "IGRIS_GPT uses a safety-first approach: only command_id execution is allowed, "
     "file preview blocks .env and path traversal, and all output is secret-redacted."),
    (["a2a", "agent card", "agent-card"],
     "The A2A agent card is at /.well-known/agent-card.json. "
     "Create A2A tasks via POST /api/a2a/tasks. Capabilities at /api/a2a/capabilities."),
    (["install", "installazione", "setup"],
     "Install IGRIS_GPT: bash scripts/install_ubuntu.sh, then cp .env.example .env, "
     "then bash scripts/start_igris.sh. See README.md for details."),
    (["file", "files", "browse"],
     "Browse files via /api/files/tree and preview with /api/files/preview?path=filename."),
    (["git"],
     "Git status is available at /api/git/status (read-only)."),
    (["cost", "routing", "provider"],
     "Routing info at /api/routing/explain, history at /api/routing/history, "
     "cost summary at /api/cost/summary."),
    (["teacher", "remediation", "governance"],
     "Teacher governance validates agent assignments. "
     "Use POST /api/teacher/remediate to propose remediation tasks."),
    (["timeline", "agent", "events"],
     "Agent timeline events at /api/agent/timeline. "
     "Each action (task, test, command) is recorded."),
    (["help", "aiuto", "cosa puoi fare", "what can you do"],
     "I am IGRIS_GPT, your AI engineering agent. I can manage tasks, run tests, "
     "browse files, track costs, and communicate via the A2A protocol. "
     "Use the tabs in the console to interact with different capabilities."),
]

_DEFAULT_FALLBACK = (
    "I'm IGRIS_GPT, your AI engineering agent. I'm currently running in "
    "deterministic fallback mode because the local LLM is not available. "
    "You can still use all agent capabilities through the console tabs. "
    "Set up Ollama with: bash scripts/setup_ollama.sh"
)


def _build_fallback_response(message: str) -> str:
    """Generate a contextual fallback response based on keywords."""
    lower = message.lower()
    for keywords, response in _FALLBACK_HINTS:
        for kw in keywords:
            if kw in lower:
                return response
    return _DEFAULT_FALLBACK


def _try_ollama(messages: list[dict[str, str]], model: str, base_url: str,
                timeout: float = 10.0) -> Optional[str]:
    """Attempt to get a response from the Ollama API."""
    import urllib.request
    import urllib.error
    import json

    url = f"{base_url.rstrip('/')}/api/chat"
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data.get("message", {}).get("content", "")
            return content if content else None
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError,
            TimeoutError, ConnectionError):
        return None


def chat(
    message: str,
    history: Optional[list[dict[str, str]]] = None,
    system_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Send a chat message and return a response with metadata.

    Returns a dict with:
    - text: the response text
    - provider: which provider was used
    - model: which model
    - fallback_used: whether fallback was used
    - latency_ms: response latency in milliseconds
    - routing_reason: why this provider was chosen
    """
    if history is None:
        history = []

    t0 = time.monotonic()

    # Check if the message matches a known operational intent
    # If so, return a grounded response directly (IGRIS-aware, not generic)
    intent = detect_intent(message)
    if intent is not None:
        grounded = get_grounded_response(intent)
        if grounded is not None:
            latency_ms = int((time.monotonic() - t0) * 1000)
            return {
                "text": grounded,
                "provider": "igris_personality",
                "model": "capability_grounding",
                "fallback_used": False,
                "latency_ms": latency_ms,
                "routing_reason": f"IGRIS-aware grounded response for intent: {intent}",
                "intent_detected": intent,
                "suggested_actions": get_suggested_actions(intent),
            }

    messages: list[dict[str, str]] = []
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
    routing_reason = "local LLM available"

    # Try local Ollama
    response_text = _try_ollama(messages, model, base_url)

    if response_text is None:
        # Try primary cloud fallback (DeepSeek by default)
        if CONFIG.fallback_llm.api_key:
            fallback_text = _try_openai_fallback(messages)
            if fallback_text:
                response_text = fallback_text
                provider = CONFIG.fallback_llm.provider
                model = CONFIG.fallback_llm.model
                fallback_used = True
                routing_reason = f"local LLM unavailable, using {CONFIG.fallback_llm.provider} fallback"

    if response_text is None:
        # Try secondary OpenAI fallback when DeepSeek is also unreachable
        if CONFIG.openai_chat_fallback.api_key:
            secondary_text = _try_openai_secondary_fallback(messages)
            if secondary_text:
                response_text = secondary_text
                provider = CONFIG.openai_chat_fallback.provider
                model = CONFIG.openai_chat_fallback.model
                fallback_used = True
                routing_reason = "primary cloud unavailable, using OpenAI secondary fallback"

    if response_text is None:
        response_text = _build_fallback_response(message)
        provider = "deterministic"
        model = "fallback"
        fallback_used = True
        routing_reason = "LLM unavailable, using deterministic fallback"

    latency_ms = int((time.monotonic() - t0) * 1000)

    return {
        "text": response_text,
        "provider": provider,
        "model": model,
        "fallback_used": fallback_used,
        "latency_ms": latency_ms,
        "routing_reason": routing_reason,
    }


def _try_openai_fallback(messages: list[dict[str, str]]) -> Optional[str]:
    """Attempt to get a response from the primary cloud fallback (DeepSeek by default)."""
    import urllib.request
    import urllib.error
    import json

    api_key = CONFIG.fallback_llm.api_key
    if not api_key:
        return None

    base_url = CONFIG.fallback_llm.base_url or "https://api.openai.com/v1"
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = json.dumps({
        "model": CONFIG.fallback_llm.model,
        "messages": messages,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("choices", [{}])[0].get("message", {}).get("content")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError,
            TimeoutError, ConnectionError):
        return None


def _try_openai_secondary_fallback(messages: list[dict[str, str]]) -> Optional[str]:
    """Attempt to get a response from secondary OpenAI fallback (behind DeepSeek)."""
    import urllib.request
    import urllib.error
    import json

    api_key = CONFIG.openai_chat_fallback.api_key
    if not api_key:
        return None

    url = "https://api.openai.com/v1/chat/completions"
    payload = json.dumps({
        "model": CONFIG.openai_chat_fallback.model,
        "messages": messages,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("choices", [{}])[0].get("message", {}).get("content")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError,
            TimeoutError, ConnectionError):
        return None


def check_ollama_available() -> bool:
    """Check if the Ollama service is reachable."""
    import urllib.request
    import urllib.error

    base_url = CONFIG.local_llm.base_url or "http://127.0.0.1:11434"
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=3):
            return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError,
            TimeoutError, ConnectionError):
        return False
