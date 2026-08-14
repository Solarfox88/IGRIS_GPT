"""Tests for #1315 — structured logging.

Verifies:
- StructuredFormatter produces valid JSON
- configure_structured_logging sets up handlers
- get_logger returns a logger with igris prefix
- Log records include ts, level, module, message fields
- Extra fields are included in JSON output
- Log level is configurable via env var
"""
from __future__ import annotations

import io
import json
import logging
import os
from pathlib import Path

import pytest

from igris.core.structured_logging import (
    StructuredFormatter,
    configure_structured_logging,
    get_logger,
)


def test_structured_formatter_produces_valid_json():
    """StructuredFormatter.format() returns valid JSON."""
    formatter = StructuredFormatter()
    record = logging.LogRecord(
        name="igris.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="test message",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert data["level"] == "INFO"
    assert data["message"] == "test message"
    assert "ts" in data
    assert "module" in data


def test_structured_formatter_includes_extra_fields():
    """Extra fields passed via extra={} are included in JSON."""
    formatter = StructuredFormatter()
    record = logging.LogRecord(
        name="igris.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="task completed",
        args=(),
        exc_info=None,
    )
    record.task_id = 42
    record.duration_ms = 150
    output = formatter.format(record)
    data = json.loads(output)
    assert data["extra"]["task_id"] == 42
    assert data["extra"]["duration_ms"] == 150


def test_structured_formatter_includes_exception_info():
    """Exception info is included when present."""
    formatter = StructuredFormatter()
    try:
        raise ValueError("test error")
    except ValueError:
        import sys
        record = logging.LogRecord(
            name="igris.test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="operation failed",
            args=(),
            exc_info=sys.exc_info(),
        )
    output = formatter.format(record)
    data = json.loads(output)
    assert data["exception"]["type"] == "ValueError"
    assert data["exception"]["message"] == "test error"


def test_configure_structured_logging_sets_level():
    """configure_structured_logging sets the log level."""
    logger = configure_structured_logging(level="DEBUG", log_file=None, use_json=False)
    assert logger.level == logging.DEBUG


def test_configure_structured_logging_env_var():
    """Log level is configurable via IGRIS_LOG_LEVEL env var."""
    os.environ["IGRIS_LOG_LEVEL"] = "WARNING"
    try:
        logger = configure_structured_logging(log_file=None, use_json=False)
        assert logger.level == logging.WARNING
    finally:
        del os.environ["IGRIS_LOG_LEVEL"]


def test_get_logger_returns_igris_prefixed():
    """get_logger returns a logger with igris. prefix."""
    logger = get_logger("core.task_engine")
    assert logger.name == "igris.core.task_engine"


def test_get_logger_inherits_level():
    """get_logger loggers inherit level from parent igris logger."""
    configure_structured_logging(level="ERROR", log_file=None, use_json=False)
    logger = get_logger("test")
    # Child loggers don't have their own level — they use effective level
    assert logger.getEffectiveLevel() == logging.ERROR


def test_structured_formatter_handles_non_serializable_extra():
    """Non-serializable extra values are converted to str."""
    formatter = StructuredFormatter()
    record = logging.LogRecord(
        name="igris.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="test",
        args=(),
        exc_info=None,
    )
    record.custom_obj = Path("/some/path")  # Not JSON-serializable
    output = formatter.format(record)
    data = json.loads(output)
    assert data["extra"]["custom_obj"] == "/some/path" or "\\some\\path" in data["extra"]["custom_obj"]


def test_structured_formatter_no_extra_when_none():
    """No 'extra' key in JSON when no extra fields are present."""
    formatter = StructuredFormatter()
    record = logging.LogRecord(
        name="igris.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="simple message",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert "extra" not in data


def test_configure_structured_logging_creates_log_file(tmp_path):
    """configure_structured_logging creates a log file when path is provided."""
    log_file = str(tmp_path / "test.log")
    logger = configure_structured_logging(log_file=log_file, use_json=True)
    logger.info("test message", extra={"test_field": "test_value"})

    # Flush handlers
    for handler in logger.handlers:
        handler.flush()

    # Check log file exists and has content
    assert Path(log_file).exists()
    content = Path(log_file).read_text(encoding="utf-8").strip()
    if content:
        data = json.loads(content.split("\n")[-1] if "\n" in content else content)
        assert data["message"] == "test message"
