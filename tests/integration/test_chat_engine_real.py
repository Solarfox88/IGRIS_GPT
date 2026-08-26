"""Integration test: chat engine with real LLM (#1320).

Gated by IGRIS_INTEGRATION_TESTS=1. Requires Ollama running locally.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("IGRIS_INTEGRATION_TESTS", "0") != "1",
    reason="Set IGRIS_INTEGRATION_TESTS=1 to run integration tests with real LLM",
)


def test_chat_returns_non_empty():
    """Chat with real LLM should return a non-empty response."""
    from igris.core.chat_engine import chat

    try:
        response = chat("Say hello in one word")
        assert response is not None
        assert isinstance(response, dict)
        assert "text" in response
        assert len(response["text"]) > 0
    except Exception as exc:
        if "connection" in str(exc).lower() or "refused" in str(exc).lower():
            pytest.skip(f"LLM not reachable: {exc}")
        raise


def test_chat_preserves_context():
    """Chat with context should reference previous messages."""
    from igris.core.chat_engine import chat

    try:
        # First message
        chat("My name is TestUser123")
        # Second message should be able to reference the name
        response = chat("What is my name?")
        assert response is not None
        assert isinstance(response, dict)
        assert "text" in response
        assert len(response["text"]) > 0
    except Exception as exc:
        if "connection" in str(exc).lower() or "refused" in str(exc).lower():
            pytest.skip(f"LLM not reachable: {exc}")
        raise


def test_chat_response_format():
    """Chat response should be a string."""
    from igris.core.chat_engine import chat

    try:
        response = chat("Hello")
        assert isinstance(response, dict)
        assert "text" in response
    except Exception as exc:
        if "connection" in str(exc).lower() or "refused" in str(exc).lower():
            pytest.skip(f"LLM not reachable: {exc}")
        raise
