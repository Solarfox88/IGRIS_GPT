#!/usr/bin/env python3
"""
IGRIS API Helper — external advisory escalation script.

Called by the SelfRepairSupervisor when IGRIS_API_HELPER_COMMAND is configured
and allow_api_escalation=True.  Reads a sanitized escalation packet from stdin,
calls the configured helper model API, and returns structured JSON advice.

The output is ADVISORY ONLY.  The supervisor uses it as additional context for
repair planning — it never bypasses safety gates, tests, or CI.

Input (stdin): JSON object
  {
    "model":      str,   # e.g. "claude-haiku-4-5-20251001"
    "max_tokens": int,
    "packet":     dict   # sanitized escalation context from supervisor
  }

Output (stdout): JSON object
  {
    "ok":                            bool,
    "model":                         str,
    "summary":                       str,
    "diagnosis":                     str,
    "likely_supervisor_gap":         str,
    "suggested_repair_strategy":     str,
    "suggested_tests":               list[str],
    "risk":                          str,   # "low"|"medium"|"high"
    "risk_notes":                    list[str],
    "do_not_do":                     list[str],
    "confidence":                    float,  # 0.0–1.0
    "requires_human_or_codex_audit": bool,
    "must_not_complete_product_manually": bool,
    "estimated_cost_usd":            float
  }

On any error the script prints a safe JSON error object to stdout and exits 1.
Secrets are never printed or logged.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{3,}[A-Za-z0-9]{10,}", re.ASCII),
    re.compile(r"anthropic[_-]?api[_-]?key\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"openai[_-]?api[_-]?key\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}", re.ASCII),
]


def _redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _safe_error(msg: str, exit_code: int = 1) -> None:
    """Emit a safe JSON error to stdout and exit."""
    payload = {
        "ok": False,
        "model": "",
        "summary": "",
        "diagnosis": _redact(str(msg)),
        "likely_supervisor_gap": "",
        "suggested_repair_strategy": "",
        "suggested_tests": [],
        "risk": "unknown",
        "risk_notes": [],
        "do_not_do": [],
        "confidence": 0.0,
        "requires_human_or_codex_audit": True,
        "must_not_complete_product_manually": True,
        "estimated_cost_usd": 0.0,
        "error": _redact(str(msg)),
    }
    print(json.dumps(payload))
    sys.exit(exit_code)


# ---------------------------------------------------------------------------
# API key resolution — never print the key
# ---------------------------------------------------------------------------

def _resolve_key() -> Tuple[str, str]:
    """Return (provider, key) or raise RuntimeError."""
    # Anthropic
    for var in ("IGRIS_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"):
        key = os.environ.get(var, "").strip()
        if key:
            return "anthropic", key
    # OpenAI
    for var in ("IGRIS_OPENAI_API_KEY", "OPENAI_API_KEY"):
        key = os.environ.get(var, "").strip()
        if key:
            return "openai", key
    raise RuntimeError(
        "No API key configured. Set ANTHROPIC_API_KEY, IGRIS_ANTHROPIC_API_KEY, "
        "OPENAI_API_KEY, or IGRIS_OPENAI_API_KEY."
    )


def _resolve_model(requested: str, provider: str) -> str:
    """Use IGRIS_API_HELPER_MODEL override if set, otherwise use requested or provider default."""
    override = os.environ.get("IGRIS_API_HELPER_MODEL", "").strip()
    if override:
        return override
    if requested and requested != "gpt-5.4-mini":
        return requested
    # Sensible defaults per provider
    return "claude-haiku-4-5-20251001" if provider == "anthropic" else "gpt-4o-mini"


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an advisory assistant for IGRIS, an autonomous coding agent.
IGRIS's supervisor is blocked on a repair task and is asking for diagnostic advice.

Your role is ADVISORY ONLY. You must never:
- Claim to have executed code or tests
- Bypass any safety, test, or CI requirement
- Complete the product manually or generate final code
- Override the supervisor's authority

Respond ONLY with a valid JSON object containing exactly these fields:
{
  "ok": true,
  "summary": "<one sentence summary>",
  "diagnosis": "<what is likely wrong>",
  "likely_supervisor_gap": "<what the supervisor may be missing>",
  "suggested_repair_strategy": "<concrete next step for the supervisor>",
  "suggested_tests": ["<test 1>", "<test 2>"],
  "risk": "<low|medium|high>",
  "risk_notes": ["<risk note>"],
  "do_not_do": ["<thing to avoid>"],
  "confidence": 0.7,
  "requires_human_or_codex_audit": false,
  "must_not_complete_product_manually": true,
  "estimated_cost_usd": 0.001
}

Output ONLY the JSON. No markdown, no explanation outside the JSON."""


# ---------------------------------------------------------------------------
# Anthropic call
# ---------------------------------------------------------------------------

def _call_anthropic(key: str, model: str, max_tokens: int, context: str, timeout: int) -> Tuple[str, float]:
    try:
        import anthropic as _anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")

    client = _anthropic.Anthropic(api_key=key, timeout=float(timeout))
    msg = client.messages.create(
        model=model,
        max_tokens=max(64, min(max_tokens, 4096)),
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}],
    )
    text = "".join(
        block.text for block in msg.content if hasattr(block, "text")
    )
    # Estimate cost (rough: $0.25/M input + $1.25/M output for Haiku)
    input_tokens = getattr(msg.usage, "input_tokens", 0)
    output_tokens = getattr(msg.usage, "output_tokens", 0)
    cost = (input_tokens * 0.25 + output_tokens * 1.25) / 1_000_000
    return text, cost


# ---------------------------------------------------------------------------
# OpenAI call
# ---------------------------------------------------------------------------

def _call_openai(key: str, model: str, max_tokens: int, context: str, timeout: int) -> Tuple[str, float]:
    try:
        import openai as _openai
    except ImportError:
        raise RuntimeError("openai package not installed. Run: pip install openai")

    client = _openai.OpenAI(api_key=key, timeout=float(timeout))
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max(64, min(max_tokens, 4096)),
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ],
    )
    text = resp.choices[0].message.content or ""
    usage = resp.usage
    input_tokens = getattr(usage, "prompt_tokens", 0)
    output_tokens = getattr(usage, "completion_tokens", 0)
    cost = (input_tokens * 0.15 + output_tokens * 0.60) / 1_000_000
    return text, cost


# ---------------------------------------------------------------------------
# Parse and validate response
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = (
    "diagnosis",
    "likely_supervisor_gap",
    "suggested_repair_strategy",
    "suggested_tests",
    "risk",
    "confidence",
    "requires_human_or_codex_audit",
    "must_not_complete_product_manually",
)


def _parse_response(raw: str, model: str, cost: float) -> Dict[str, Any]:
    text = _redact(raw.strip())
    # Extract JSON from response (model might wrap in markdown)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {
            "ok": False,
            "model": model,
            "error": "helper returned no JSON object",
            "summary": "",
            "diagnosis": f"Could not parse helper response: {text[:200]}",
            "likely_supervisor_gap": "",
            "suggested_repair_strategy": "",
            "suggested_tests": [],
            "risk": "unknown",
            "risk_notes": [],
            "do_not_do": [],
            "confidence": 0.0,
            "requires_human_or_codex_audit": True,
            "must_not_complete_product_manually": True,
            "estimated_cost_usd": cost,
        }
    try:
        payload = json.loads(match.group())
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "model": model,
            "error": f"JSON parse error: {exc}",
            "summary": "",
            "diagnosis": "",
            "likely_supervisor_gap": "",
            "suggested_repair_strategy": "",
            "suggested_tests": [],
            "risk": "unknown",
            "risk_notes": [],
            "do_not_do": [],
            "confidence": 0.0,
            "requires_human_or_codex_audit": True,
            "must_not_complete_product_manually": True,
            "estimated_cost_usd": cost,
        }
    missing = [f for f in REQUIRED_FIELDS if f not in payload]
    result: Dict[str, Any] = {
        "ok": len(missing) == 0,
        "model": model,
        "summary": str(payload.get("summary", "")),
        "diagnosis": str(payload.get("diagnosis", "")),
        "likely_supervisor_gap": str(payload.get("likely_supervisor_gap", "")),
        "suggested_repair_strategy": str(payload.get("suggested_repair_strategy", "")),
        "suggested_tests": list(payload.get("suggested_tests") or []),
        "risk": str(payload.get("risk", "unknown")),
        "risk_notes": list(payload.get("risk_notes") or []),
        "do_not_do": list(payload.get("do_not_do") or []),
        "confidence": float(payload.get("confidence", 0.0)),
        "requires_human_or_codex_audit": bool(payload.get("requires_human_or_codex_audit", False)),
        "must_not_complete_product_manually": bool(payload.get("must_not_complete_product_manually", True)),
        "estimated_cost_usd": float(payload.get("estimated_cost_usd", cost)),
    }
    if missing:
        result["error"] = f"missing fields: {', '.join(missing)}"
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Read stdin
    try:
        raw_input = sys.stdin.read()
    except Exception as exc:
        _safe_error(f"failed to read stdin: {exc}")

    # Parse input
    try:
        data = json.loads(raw_input)
    except json.JSONDecodeError as exc:
        _safe_error(f"invalid JSON on stdin: {exc}")

    model_requested = str(data.get("model", "")).strip()
    max_tokens = int(data.get("max_tokens", 600))
    packet = data.get("packet", {})
    timeout = int(os.environ.get("IGRIS_HELPER_TIMEOUT", "45"))

    # Build context (never include raw secrets)
    context_parts = [
        f"failure_class: {packet.get('failure_class', 'unknown')}",
        f"goal: {_redact(str(packet.get('goal', ''))[:500])}",
        f"repair_cycles_used: {packet.get('repair_cycles_used', 0)}",
        f"capability_signals: {packet.get('capability_signals', {})}",
    ]
    if packet.get("events"):
        recent = packet["events"][-5:]
        context_parts.append(
            "recent_events: " + json.dumps([
                {k: _redact(str(v)) for k, v in e.items()
                 if k in ("phase", "status", "detail")}
                for e in recent
            ])
        )
    context = "\n".join(context_parts)

    # Resolve API key and provider
    try:
        provider, api_key = _resolve_key()
    except RuntimeError as exc:
        _safe_error(str(exc))

    model = _resolve_model(model_requested, provider)

    # Call API
    try:
        if provider == "anthropic":
            raw_response, cost = _call_anthropic(api_key, model, max_tokens, context, timeout)
        else:
            raw_response, cost = _call_openai(api_key, model, max_tokens, context, timeout)
    except Exception as exc:
        _safe_error(f"API call failed: {_redact(str(exc))}")

    result = _parse_response(raw_response, model, cost)
    print(json.dumps(result))
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
