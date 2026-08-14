"""Structured JSON logging for IGRIS_GPT (#1315).

Provides a StructuredFormatter that emits JSON log records suitable for
machine consumption (ELK, Loki, CloudWatch, etc.).

Usage:
    from igris.core.structured_logging import configure_structured_logging
    configure_structured_logging(level="INFO", log_file=".igris/logs/igris.jsonl")

    logger = logging.getLogger(__name__)
    logger.info("task_completed", extra={"task_id": 42, "duration_ms": 150})
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

from igris.core.safety import redact_secrets as _centralized_redact_secrets


# Redaction patterns for secrets that might appear in log messages.
# These are kept for backward compatibility but the actual redaction is
# delegated to the centralized safety.redact_secrets function (#1313).
# The formatter-level redaction is a defense-in-depth layer: even if a
# caller forgets to redact before logging, the formatter catches it.
_SECRET_PATTERNS = [
    re.compile(r'(token|passphrase|password|secret|api[_\s]?key|bearer)\s*[=:]\s*\S+', re.IGNORECASE),
    re.compile(r'Authorization:\s*Bearer\s+\S+', re.IGNORECASE),
    re.compile(r'Authorization:\s*Basic\s+\S+', re.IGNORECASE),
    re.compile(r'gh[ps]_[A-Za-z0-9]{20,}'),  # GitHub tokens
    re.compile(r'sk-[A-Za-z0-9_-]{20,}'),  # OpenAI-style API keys
]
_REDACTED = '<REDACTED>'


def _redact_message(msg: str) -> str:
    """Redact secrets from a log message string.

    Uses the centralized safety.redact_secrets as the primary redaction
    mechanism, with formatter-level patterns as defense-in-depth.
    """
    if not msg:
        return msg
    # Primary: centralized redaction from safety module
    msg = _centralized_redact_secrets(msg)
    # Defense-in-depth: formatter-level patterns for any remaining secrets
    for pattern in _SECRET_PATTERNS:
        msg = pattern.sub(_REDACTED, msg)
    return msg


def _redact_extra(extra: Dict[str, Any]) -> Dict[str, Any]:
    """Redact secrets from extra fields."""
    redacted: Dict[str, Any] = {}
    for k, v in extra.items():
        key_lower = k.lower()
        if any(s in key_lower for s in ('token', 'password', 'secret', 'api_key', 'apikey', 'authorization', 'cookie', 'bearer')):
            redacted[k] = _REDACTED
        elif isinstance(v, str):
            redacted[k] = _redact_message(v)
        else:
            redacted[k] = v
    return redacted


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging.

    Emits one JSON object per log record, with fields:
    - ts: ISO timestamp
    - level: log level name
    - module: module name
    - func: function name
    - line: line number
    - message: log message
    - extra: any extra fields passed via extra={}
    - exc_info: exception info if present
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.created * 1000) % 1000:03d}Z",
            "level": record.levelname,
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
            "message": _redact_message(record.getMessage()),
        }

        # Add extra fields (anything not in standard LogRecord attributes)
        standard_attrs = {
            "name", "msg", "args", "created", "relativeCreated",
            "exc_info", "exc_text", "stack_info", "levelname", "levelno",
            "pathname", "filename", "module", "exc_info", "funcName",
            "lineno", "message", "thread", "threadName", "processName",
            "process", "msecs", "asctime", "getMessage", "taskName",
        }
        extra = {k: v for k, v in record.__dict__.items() if k not in standard_attrs}
        if extra:
            # Sanitize — convert non-serializable to str
            for k, v in extra.items():
                if not isinstance(v, (str, int, float, bool, type(None), list, dict)):
                    extra[k] = str(v)
            # Redact secrets from extra fields
            extra = _redact_extra(extra)
            log_entry["extra"] = extra

        # Add exception info if present (with redaction)
        if record.exc_info and record.exc_info[1] is not None:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": _redact_message(str(record.exc_info[1])),
            }

        return json.dumps(log_entry, ensure_ascii=False, default=str)


def configure_structured_logging(
    level: Optional[str] = None,
    log_file: Optional[str] = None,
    *,
    use_json: bool = True,
) -> logging.Logger:
    """Configure structured logging for IGRIS.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR). Defaults to env
            IGRIS_LOG_LEVEL or "INFO".
        log_file: Path to JSON log file. If None (default), file logging is
            disabled unless IGRIS_LOG_FILE env var is set. Set
            IGRIS_LOG_FILE=none to explicitly disable file logging.
        use_json: If True, use JSON formatter. If False, use plain text.

    Returns:
        The root IGRIS logger.
    """
    if level is None:
        level = os.environ.get("IGRIS_LOG_LEVEL", "INFO")

    logger = logging.getLogger("igris")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Close and remove existing handlers to avoid duplicates and file handle leaks
    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()

    # Console handler (plain text for readability)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    if use_json:
        console_handler.setFormatter(StructuredFormatter())
    else:
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
    logger.addHandler(console_handler)

    # File handler (JSON, with rotation) — opt-in via IGRIS_LOG_FILE env var
    # or explicit log_file parameter. Default: console-only (no file handler)
    # to avoid Windows file-lock issues in tests. Production deployments should
    # set IGRIS_LOG_FILE=/path/to/igris.jsonl or pass log_file= explicitly.
    env_log_file = os.environ.get("IGRIS_LOG_FILE")
    if log_file is None and env_log_file and env_log_file.lower() not in ("none", "off", "disabled"):
        log_file = env_log_file

    if log_file and (not env_log_file or env_log_file.lower() not in ("none", "off", "disabled")):
        try:
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,  # 10 MB
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
            file_handler.setFormatter(StructuredFormatter())
            logger.addHandler(file_handler)
        except (OSError, PermissionError) as exc:
            # Don't crash if log file can't be created
            logger.warning("Could not create log file %s: %s", log_file, exc)

    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a structured logger for the given module name."""
    return logging.getLogger(f"igris.{name}")
