"""
Safety utilities for IGRIS_GPT.

This module centralizes checks and helpers related to security and
sensitive data handling.  It provides functions to validate
filesystem paths, ensure only allowed commands are executed, detect
secret-like patterns in text and redact them, and identify files or
directories that should be hidden from the file browser.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

from igris.layers.execution.safe_commands import ALLOWED_COMMANDS

# ---------------------------------------------------------------------------
# SafetyDecision
# ---------------------------------------------------------------------------

@dataclass
class SafetyDecision:
    """Standard result of a safety check."""

    allowed: bool
    reason: str = ""
    redacted: bool = False
    details: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Path access
# ---------------------------------------------------------------------------

_SENSITIVE_NAMES = {
    ".env", ".env.local", ".env.production", ".env.development",
    "id_rsa", "id_ed25519", "credentials.json", "service_account.json",
}

_SENSITIVE_SUBSTRINGS = ("key", "token", "secret", "credential", "password")


def check_path_access(path: Path, root: Path, purpose: str = "read") -> bool:
    """Return True if *path* is within the allowed *root*."""
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
    except Exception:
        return False
    # Block symlinks that escape root
    if path.is_symlink():
        try:
            link_target = path.resolve(strict=False)
            if root_resolved not in link_target.parents and link_target != root_resolved:
                return False
        except Exception:
            return False
    return root_resolved in resolved.parents or resolved == root_resolved


def is_sensitive_filename(name: str) -> bool:
    """Check if a filename likely contains sensitive data."""
    lowered = name.lower()
    if lowered in _SENSITIVE_NAMES:
        return True
    return any(x in lowered for x in _SENSITIVE_SUBSTRINGS)


def is_runtime_artifact(path: Path) -> bool:
    """Return True if a path refers to a runtime or temporary artifact."""
    parts = path.parts
    for part in parts:
        if part in {
            ".git", ".venv", ".venv_linux", "__pycache__",
            ".pytest_cache", ".ruff_cache", "node_modules",
        }:
            return True
        if part.startswith("logs") or part == ".igris":
            return True
    return False


# ---------------------------------------------------------------------------
# Command checks
# ---------------------------------------------------------------------------

def check_command_allowed(command_id: str) -> bool:
    """Return True if the given command ID is in the allowed list."""
    return command_id in ALLOWED_COMMANDS


# ---------------------------------------------------------------------------
# Secret detection & redaction
# ---------------------------------------------------------------------------

_SECRET_PATTERNS = [
    # OpenAI keys
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    # GitHub tokens
    re.compile(r"gh[pos]_[A-Za-z0-9]{10,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    # Bearer tokens
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]{20,}"),
    # AWS-like keys
    re.compile(r"AKIA[A-Z0-9]{16}"),
    # VAST/generic API keys
    re.compile(r"(?:VAST|VASTAI)[A-Za-z0-9_]{8,}"),
    # Generic KEY= / TOKEN= / SECRET= lines
    re.compile(r"(?:API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE_KEY)\s*[=:]\s*\S{8,}", re.IGNORECASE),
    # Long hex-like tokens (40+ chars)
    re.compile(r"[A-Fa-f0-9]{40,}"),
]

# Compiled once for the broader catch-all
_SECRET_CATCHALL = re.compile(
    r"(?:(?:sk|ghp|gho|api|token|secret)[A-Za-z0-9_]{8,})"
    r"|(?:[A-Za-z0-9_]{20,})",
)


def redact_secrets(text: Optional[str]) -> str:
    """Mask secret-like sequences in a string."""
    if not text:
        return ""
    result = text
    for pat in _SECRET_PATTERNS:
        result = pat.sub("***REDACTED***", result)
    return result


def detect_secret_like_content(text: str) -> bool:
    """Detect if a string contains secret-like patterns."""
    for pat in _SECRET_PATTERNS:
        if pat.search(text):
            return True
    return False


def truncate_output(text: str, max_chars: int = 10000) -> str:
    """Truncate text to *max_chars* with a notice."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"


def safe_json_response(data: dict) -> dict:
    """Recursively redact string values that look like secrets."""
    out: dict = {}
    for k, v in data.items():
        if isinstance(v, str):
            out[k] = redact_secrets(v)
        elif isinstance(v, dict):
            out[k] = safe_json_response(v)
        elif isinstance(v, list):
            out[k] = [
                safe_json_response(i) if isinstance(i, dict)
                else redact_secrets(i) if isinstance(i, str)
                else i
                for i in v
            ]
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# File preview safety
# ---------------------------------------------------------------------------

_BLOCKED_EXTENSIONS = {".pem", ".key", ".p12", ".pfx", ".jks"}
_MAX_PREVIEW_SIZE = 50_000


def check_file_preview(path: Path, root: Path) -> SafetyDecision:
    """Full safety check for previewing a file."""
    if not check_path_access(path, root):
        return SafetyDecision(allowed=False, reason="Path escapes project root")
    if path.is_symlink():
        try:
            target = path.resolve(strict=False)
            if root.resolve() not in target.parents and target != root.resolve():
                return SafetyDecision(allowed=False, reason="Symlink escapes root")
        except Exception:
            return SafetyDecision(allowed=False, reason="Cannot resolve symlink")
    if path.name.lower() in _SENSITIVE_NAMES:
        return SafetyDecision(allowed=False, reason="Sensitive filename blocked")
    if is_sensitive_filename(path.name):
        return SafetyDecision(allowed=False, reason="Filename matches sensitive pattern")
    if path.suffix.lower() in _BLOCKED_EXTENSIONS:
        return SafetyDecision(allowed=False, reason="Blocked file extension")
    if is_runtime_artifact(path):
        return SafetyDecision(allowed=False, reason="Runtime artifact")
    if path.exists() and path.stat().st_size > _MAX_PREVIEW_SIZE:
        return SafetyDecision(allowed=False, reason="File too large for preview")
    return SafetyDecision(allowed=True)
