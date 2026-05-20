"""Tests for the chat engine — Ollama is always mocked."""
from unittest.mock import patch

import pytest

from igris.core.chat_engine import chat, _build_fallback_response, check_ollama_available


@pytest.fixture(autouse=True)
def _mock_ollama(monkeypatch):
    """Prevent any real Ollama calls in this test module."""
    monkeypatch.setattr(
        "igris.core.chat_engine._try_ollama",
        lambda *a, **kw: None,  # always simulate Ollama unavailable
    )


def test_chat_without_ollama_does_not_crash():
    """Chat must return a response even when Ollama is not running."""
    result = chat("hello")
    assert "text" in result
    assert "provider" in result
    assert "fallback_used" in result
    assert "latency_ms" in result
    assert result["text"]  # non-empty


def test_chat_response_has_routing_metadata():
    result = chat("what can you do?")
    assert result["provider"] in ("ollama", "deterministic", "openai", "deepseek",
                                  "igris_personality", "deterministic")
    assert isinstance(result["latency_ms"], int)
    assert "routing_reason" in result


def test_fallback_response_is_contextual():
    assert "status" in _build_fallback_response("show me the status").lower() or            "/api/" in _build_fallback_response("show me the status")
    assert "task" in _build_fallback_response("create a task").lower() or            "/api/tasks" in _build_fallback_response("create a task")
    assert "test" in _build_fallback_response("run tests").lower() or            "runner" in _build_fallback_response("run tests").lower()


def test_no_secrets_in_fallback_response():
    from igris.core.safety import detect_secret_like_content
    result = chat("tell me about safety")
    assert not detect_secret_like_content(result["text"])


def test_check_ollama_available_returns_bool():
    # Uses real network check (fast — just a tags endpoint ping)
    result = check_ollama_available()
    assert isinstance(result, bool)
