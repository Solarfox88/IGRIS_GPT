"""
Safety utilities for IGRIS_GPT.

This module centralizes checks and helpers related to security and
sensitive data handling.  It provides functions to validate
filesystem paths, ensure only allowed commands are executed, detect
secret‑like patterns in text and redact them, and identify files or
directories that should be hidden from the file browser.  By
consolidating these checks here, we avoid duplicating security logic
across different parts of the codebase and make it easier to audit
and harden the behaviour.

Functions implemented here should be lightweight and avoid external
dependencies so they can be used by FastAPI request handlers, test
runners and internal components without side effects.

"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Optional

from igris.layers.execution.safe_commands import ALLOWED_COMMANDS


def check_path_access(path: Path, root: Path) -> bool:
    """Return True if the given path is within the allowed root.

    This function normalizes and resolves the input path and ensures
    that it lies inside the specified root directory.  If resolution
    fails (e.g. due to symlinks pointing outside) it returns False.

    :param path: The user‑supplied path (absolute or relative).
    :param root: The project root directory.
    :returns: True if the path is safe to access.
    """
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
    except Exception:
        return False
    return root_resolved in resolved.parents or resolved == root_resolved


def is_sensitive_filename(name: str) -> bool:
    """Check if a filename likely contains sensitive data.

    Filenames containing substrings like "key", "token" or "secret"
    (case insensitive) are considered sensitive and should be hidden
    from the file browser.  This heuristic helps avoid accidental
    exposure of secrets in configuration files.

    :param name: The filename to check.
    :returns: True if the filename is considered sensitive.
    """
    lowered = name.lower()
    return any(x in lowered for x in ("key", "token", "secret"))


def is_runtime_artifact(path: Path) -> bool:
    """Return True if a path refers to a runtime or temporary artifact.

    Runtime artifacts like virtual environments, cache directories,
    logs, the .igris runtime state and __pycache__ directories should
    not be exposed via the file tree.  This helper identifies such
    paths based on naming conventions.

    :param path: The path to examine (can be file or directory).
    :returns: True if the path should be excluded.
    """
    parts = path.parts
    for part in parts:
        if part in {".git", ".venv", ".venv_linux", "__pycache__", ".pytest_cache", ".ruff_cache"}:
            return True
        if part.startswith("logs") or part == ".igris":
            return True
    return False


def check_command_allowed(command_id: str) -> bool:
    """Return True if the given command ID is in the allowed list.

    The safe terminal API should call this helper rather than
    inspecting ALLOWED_COMMANDS directly.  Centralizing this check
    makes it easier to apply additional policy (e.g. per‑user
    permissions) in the future.

    :param command_id: The identifier of the command.
    :returns: True if the command is allowed to run.
    """
    return command_id in ALLOWED_COMMANDS


_SECRET_PATTERN = re.compile(
    r"""
    (?:(?:sk|ghp|gho|api|token|secret)[A-Za-z0-9_]{8,})
    |(?:[A-Za-z0-9_]{20,})
    """,
    re.VERBOSE,
)


def redact_secrets(text: Optional[str]) -> str:
    """Mask secret‑like sequences in a string.

    This function searches for patterns that resemble API keys, tokens
    or long random strings and replaces them with the placeholder
    "***REDACTED***".  It should be applied to all stdout/stderr
    returned to the user to prevent accidental leakage of secrets.

    :param text: The input string.  If None, returns an empty string.
    :returns: The redacted string.
    """
    if not text:
        return ""
    return _SECRET_PATTERN.sub("***REDACTED***", text)


def detect_secret_like_content(text: str) -> bool:
    """Detect if a string contains secret‑like patterns.

    This can be used to refuse to preview a file if it contains
    sensitive data.  For now it shares the same regex as
    ``redact_secrets`` but returns a boolean.

    :param text: The text to inspect.
    :returns: True if a secret‑like pattern is found.
    """
    return bool(_SECRET_PATTERN.search(text))