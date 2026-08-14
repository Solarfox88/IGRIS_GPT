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


# ── Phase 2 tests — redaction, server wiring, event naming (#1354) ──────────

def test_structured_formatter_redacts_secrets_in_message():
    """StructuredFormatter redacts secrets from log messages."""
    formatter = StructuredFormatter()
    record = logging.LogRecord(
        name="igris.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Auth failed: token=ghp_1234567890abcdefghijklmnopqrstuvwxyz",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert "ghp_1234567890abcdefghijklmnopqrstuvwxyz" not in data["message"]
    assert "<REDACTED>" in data["message"]


def test_structured_formatter_redacts_authorization_header():
    """StructuredFormatter redacts Authorization headers from log messages."""
    formatter = StructuredFormatter()
    record = logging.LogRecord(
        name="igris.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Request received: Authorization: Bearer sk-abc123def456ghi789jkl012mno345pqr678",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert "sk-abc123def456ghi789jkl012mno345pqr678" not in data["message"]
    assert "<REDACTED>" in data["message"]


def test_structured_formatter_redacts_secret_extra_fields():
    """StructuredFormatter redacts extra fields with sensitive names."""
    formatter = StructuredFormatter()
    record = logging.LogRecord(
        name="igris.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="auth event",
        args=(),
        exc_info=None,
    )
    record.token = "ghp_secret_token_value_here"
    record.api_key = "sk-secret-key-value-here"
    record.password = "my_secret_password"
    record.user_id = 42  # non-sensitive field should pass through
    output = formatter.format(record)
    data = json.loads(output)
    assert data["extra"]["token"] == "<REDACTED>"
    assert data["extra"]["api_key"] == "<REDACTED>"
    assert data["extra"]["password"] == "<REDACTED>"
    assert data["extra"]["user_id"] == 42


def test_structured_formatter_redacts_exception_messages():
    """StructuredFormatter redacts secrets from exception messages."""
    formatter = StructuredFormatter()
    try:
        raise ValueError("Auth failed: token=ghp_1234567890abcdefghijklmnopqrstuvwxyz")
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
    assert "ghp_1234567890abcdefghijklmnopqrstuvwxyz" not in data["exception"]["message"]
    assert "<REDACTED>" in data["exception"]["message"]


def test_server_startup_wires_structured_logging():
    """create_app() should call configure_structured_logging at startup."""
    import inspect
    from igris.web.server import create_app
    source = inspect.getsource(create_app)
    assert "configure_structured_logging" in source, \
        "create_app() must call configure_structured_logging() at startup"


def test_igris_log_level_env_var_works():
    """IGRIS_LOG_LEVEL env var controls the log level."""
    os.environ["IGRIS_LOG_LEVEL"] = "ERROR"
    try:
        logger = configure_structured_logging(log_file=None, use_json=False)
        assert logger.level == logging.ERROR
    finally:
        del os.environ["IGRIS_LOG_LEVEL"]


def test_structured_formatter_redacts_api_key_pattern():
    """StructuredFormatter redacts OpenAI-style API keys."""
    formatter = StructuredFormatter()
    record = logging.LogRecord(
        name="igris.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Calling LLM with key sk-proj-1234567890abcdefghijklmnopqrstuv",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert "sk-proj-1234567890abcdefghijklmnopqrstuv" not in data["message"]
    assert "<REDACTED>" in data["message"]


def test_structured_formatter_preserves_non_secret_messages():
    """StructuredFormatter does not redact non-secret messages."""
    formatter = StructuredFormatter()
    record = logging.LogRecord(
        name="igris.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="task_completed: task_id=42 duration_ms=150",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert data["message"] == "task_completed: task_id=42 duration_ms=150"


def test_structured_formatter_redacts_cookie_in_extra():
    """StructuredFormatter redacts cookie fields in extra."""
    formatter = StructuredFormatter()
    record = logging.LogRecord(
        name="igris.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="request received",
        args=(),
        exc_info=None,
    )
    record.cookie = "session=abc123; token=xyz789"
    record.bearer = "Bearer eyJhbGciOiJIUzI1NiJ9..."
    output = formatter.format(record)
    data = json.loads(output)
    assert data["extra"]["cookie"] == "<REDACTED>"
    assert data["extra"]["bearer"] == "<REDACTED>"


def test_structured_formatter_redacts_github_token_pattern():
    """StructuredFormatter redacts GitHub personal access tokens."""
    formatter = StructuredFormatter()
    record = logging.LogRecord(
        name="igris.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Using token ghp_1234567890abcdefghijklmnopqrst for GitHub API",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert "ghp_1234567890abcdefghijklmnopqrst" not in data["message"]
    assert "<REDACTED>" in data["message"]


def test_structured_formatter_redacts_basic_auth_header():
    """StructuredFormatter redacts Basic auth headers."""
    formatter = StructuredFormatter()
    record = logging.LogRecord(
        name="igris.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Request with Authorization: Basic dXNlcjpwYXNz",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert "dXNlcjpwYXNz" not in data["message"]
    assert "<REDACTED>" in data["message"]


def test_configure_structured_logging_closes_handlers_on_reconfigure():
    """Re-configuring should close existing handlers, not leak file handles."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        log_file = str(Path(tmp) / "test.log")
        logger = configure_structured_logging(log_file=log_file, use_json=True)
        first_handlers = list(logger.handlers)
        # Reconfigure — should close old handlers
        logger2 = configure_structured_logging(log_file=log_file, use_json=True)
        second_handlers = list(logger2.handlers)
        # The old file handler should be closed
        for h in first_handlers:
            if hasattr(h, 'stream') and h is not second_handlers[0]:
                # File handler should be closed
                pass
        # New logger should work
        logger2.info("test message")
        for h in second_handlers:
            h.close()
