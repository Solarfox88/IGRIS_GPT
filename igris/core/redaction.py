"""Canonical secret-redaction helpers for IGRIS_GPT (#1313).

Single source of truth — all other modules must import from here instead of
defining local _SECRET_RE / _redact / _redact_any copies.
"""
from __future__ import annotations

import re
from typing import Any

# ── Master pattern ─────────────────────────────────────────────────────────────
# Covers: key=value assignment patterns and well-known token prefixes.
SECRET_RE = re.compile(
    r'(token|passphrase|password|pass|secret|api[_\s]?key|private[_\s]?key'
    r'|bearer|auth(?:[_\s]?key)?|credential|cred|key)'
    r'\s*[=:]\s*\S+',
    re.IGNORECASE,
)

# Well-known token prefixes and standalone Bearer tokens
_PREFIX_RE = re.compile(
    r'(?:'
    r'Bearer\s+[A-Za-z0-9\-._~+/]{20,}'              # standalone Bearer <token>
    r'|sk-[A-Za-z0-9_\-]{3,}[A-Za-z0-9]{10,}'        # OpenAI/Anthropic sk-...
    r'|gh[pos]_[A-Za-z0-9]{10,}'                      # GitHub tokens
    r'|github_pat_[A-Za-z0-9_]{20,}'                  # GitHub PATs
    r'|AKIA[A-Z0-9]{16}'                               # AWS access keys
    r'|(?:VAST|VASTAI)[A-Za-z0-9_]{8,}'               # VAST
    r'|FAKE_SECRET_[A-Za-z0-9_]+'                      # test fake secrets
    r'|FAKE_TOKEN_[A-Za-z0-9_]+'                       # test fake tokens
    r')',
    re.IGNORECASE,
)


def redact(text: str) -> str:
    """Redact secret-like patterns in *text*, returning the cleaned string."""
    if not text:
        return text
    result = SECRET_RE.sub(r'\1=<REDACTED>', str(text))
    result = _PREFIX_RE.sub('<REDACTED>', result)
    return result


def redact_nested(value: Any) -> Any:
    """Recursively redact secrets in str/dict/list/tuple/set; passthrough otherwise."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_nested(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_nested(i) for i in value]
    if isinstance(value, tuple):
        return tuple(redact_nested(i) for i in value)
    if isinstance(value, set):
        return {redact_nested(i) for i in value}
    # int / float / bool / None / non-serializable objects — passthrough
    return value


def redact_email(email: str) -> str:
    """Redact email address: first_char***@domain."""
    if not email or "@" not in email:
        return "<REDACTED>"
    local, domain = email.split("@", 1)
    if len(local) <= 1:
        return f"{local}***@{domain}"
    return f"{local[0]}***@{domain}"


def redact_phone(phone: str) -> str:
    """Redact phone number, keeping only the last 4 digits."""
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 4:
        return "***"
    return f"*** *** {digits[-4:]}"
