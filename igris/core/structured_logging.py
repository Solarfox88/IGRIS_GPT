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
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional


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
            "message": record.getMessage(),
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
            log_entry["extra"] = extra

        # Add exception info if present
        if record.exc_info and record.exc_info[1] is not None:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]),
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
        log_file: Path to JSON log file. Defaults to
            .igris/logs/igris.jsonl under project root. Set to None to
            disable file logging.
        use_json: If True, use JSON formatter. If False, use plain text.

    Returns:
        The root IGRIS logger.
    """
    if level is None:
        level = os.environ.get("IGRIS_LOG_LEVEL", "INFO")

    logger = logging.getLogger("igris")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates on re-configure
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

    # File handler (JSON, with rotation)
    if log_file is None:
        project_root = os.environ.get("IGRIS_PROJECT_ROOT") or os.environ.get("PROJECT_ROOT") or "."
        log_dir = Path(project_root) / ".igris" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = str(log_dir / "igris.jsonl")

    if log_file:
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
