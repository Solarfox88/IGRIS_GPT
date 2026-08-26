"""Integration test: reasoning loop with real Ollama (#1320).

Gated by IGRIS_INTEGRATION_TESTS=1. Requires Ollama running locally.
"""
import os

import pytest

# Gate: skip all tests in this module unless IGRIS_INTEGRATION_TESTS=1
pytestmark = pytest.mark.skipif(
    os.environ.get("IGRIS_INTEGRATION_TESTS", "0") != "1",
    reason="Set IGRIS_INTEGRATION_TESTS=1 to run integration tests with real LLM",
)


def test_ollama_reachable():
    """Verify Ollama is reachable on localhost:11434."""
    import urllib.request
    import json

    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert "models" in data
    except Exception as exc:
        pytest.skip(f"Ollama not reachable: {exc}")


def test_reasoning_loop_single_step():
    """Run a single-step reasoning loop with real Ollama.

    This test verifies the full pipeline: context build -> model call ->
    action parse -> result. It does NOT verify correctness of the action,
    only that the loop runs without errors when a real model is available.
    """
    from igris.core.agent_reasoning_loop import AgentReasoningLoop

    loop = AgentReasoningLoop(
        project_root=os.environ.get("PROJECT_ROOT", "."),
        max_steps=1,
    )
    result = loop.run(goal="List the files in the current directory")

    assert result.status in ("finished", "stopped", "blocked")
    assert result.total_steps >= 0
    # If the model returned a finish action, status should be "finished"
    # If max_steps reached, status should be "stopped"
    # If blocked (e.g. auth), status should be "blocked"


def test_chat_engine_real_response():
    """Test chat engine with real Ollama model.

    Verifies that the chat engine can send a message and receive a
    non-empty response from the LLM.
    """
    from igris.core.chat_engine import chat

    try:
        response = chat("Hello, what is 2+2?")
        assert response is not None
        assert isinstance(response, dict)
        assert "text" in response
        assert len(response["text"]) > 0
    except Exception as exc:
        if "connection" in str(exc).lower() or "refused" in str(exc).lower():
            pytest.skip(f"Ollama not reachable: {exc}")
        raise


def test_model_orchestrator_real_call():
    """Test model orchestrator with real Ollama.

    Verifies that the orchestrator can route a request to Ollama and
    receive a valid response.
    """
    from igris.core.model_orchestrator import ModelOrchestrator

    orch = ModelOrchestrator()
    try:
        result = orch.complete(
            task_type="chat",
            messages=[{"role": "user", "content": "What is the capital of France?"}],
            system_prompt="You are a helpful assistant. Answer briefly.",
        )
        assert result is not None
    except Exception as exc:
        if "connection" in str(exc).lower() or "refused" in str(exc).lower():
            pytest.skip(f"Ollama not reachable: {exc}")
        raise
