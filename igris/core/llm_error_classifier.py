"""Provider-agnostic LLM error classification and retry policy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from igris.core.safety import redact_secrets


@dataclass
class LLMErrorClassification:
    category: str
    retryable: bool
    recommended_action: str
    backoff_seconds: float
    provider_switch_allowed: bool
    severity: str
    reason: str


def _contains(text: str, *patterns: str) -> bool:
    low = text.lower()
    return any(p in low for p in patterns)


def classify_llm_provider_error(
    *,
    exception: Optional[BaseException] = None,
    message: str = "",
    status_code: Optional[int] = None,
    provider_response: Any = None,
) -> LLMErrorClassification:
    raw = " ".join(
        x for x in [str(message or ""), str(exception or ""), str(provider_response or "")] if x
    )
    text = redact_secrets(raw)
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "[REDACTED]", text)

    code = status_code
    if code is None:
        m = re.search(r"\b(?:http\s*error\s*)?(\d{3})\b", text.lower())
        if m:
            try:
                code = int(m.group(1))
            except ValueError:
                code = None

    if _contains(text, "timeout", "timed out"):
        return LLMErrorClassification("timeout", True, "retry_with_backoff", 1.0, True, "warning", text[:240])
    if code == 429 or _contains(text, "rate limit", "too many requests"):
        return LLMErrorClassification("rate_limit", True, "backoff_or_switch_provider", 2.0, True, "warning", text[:240])
    if code in (401, 403) or _contains(text, "unauthorized", "forbidden", "invalid api key", "authentication"):
        return LLMErrorClassification("auth_error", False, "fix_provider_credentials", 0.0, False, "critical", text[:240])
    if code == 402 or _contains(text, "quota", "insufficient_quota", "billing", "credits"):
        return LLMErrorClassification("quota_exceeded", False, "switch_provider_or_refill_quota", 0.0, True, "high", text[:240])
    if code == 413 or _contains(text, "context length", "maximum context", "too many tokens", "token limit"):
        return LLMErrorClassification("context_length", False, "condense_context_and_retry", 0.0, True, "high", text[:240])
    if code == 400 or _contains(text, "invalid request", "bad request", "invalid_argument"):
        return LLMErrorClassification("invalid_request", False, "fix_request_payload", 0.0, False, "high", text[:240])
    if code in (500, 502, 503, 504) or _contains(text, "service unavailable", "gateway", "connection reset", "temporarily unavailable"):
        return LLMErrorClassification("provider_unavailable", True, "retry_or_fallback_provider", 1.5, True, "warning", text[:240])
    if _contains(text, "json", "malformed", "decode", "parse", "unexpected end"):
        return LLMErrorClassification("malformed_response", True, "retry_with_response_repair", 0.5, True, "warning", text[:240])
    if _contains(text, "tool call", "function call", "arguments", "schema"):
        return LLMErrorClassification("tool_call_invalid", False, "repair_tool_call_payload", 0.0, False, "medium", text[:240])

    return LLMErrorClassification(
        "unknown",
        True,
        "limited_retry_then_fallback",
        0.5,
        True,
        "medium",
        text[:240],
    )
