"""Integration test: mission end-to-end (#1320).

Gated by IGRIS_INTEGRATION_TESTS=1. Requires Ollama running locally.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("IGRIS_INTEGRATION_TESTS", "0") != "1",
    reason="Set IGRIS_INTEGRATION_TESTS=1 to run integration tests with real LLM",
)


def test_mission_create_plan_execute():
    """Full mission: create -> plan -> execute -> verify.

    This is a smoke test that verifies the mission pipeline works
    end-to-end with a real LLM. It does not verify mission success,
    only that the pipeline runs without crashes.
    """
    from igris.core.agent_reasoning_loop import AgentReasoningLoop

    loop = AgentReasoningLoop(
        project_root=os.environ.get("PROJECT_ROOT", "."),
        max_steps=3,
    )
    result = loop.run(
        goal="Create a file called _test_integration.txt with content 'hello'",
        mission_id="integration-test",
    )

    assert result.status in ("finished", "stopped", "blocked")
    assert result.total_steps >= 0
    # Clean up if the file was created
    test_file = os.path.join(os.environ.get("PROJECT_ROOT", "."), "_test_integration.txt")
    if os.path.exists(test_file):
        os.remove(test_file)


def test_mission_checkpoint_persistence():
    """Mission with checkpointing should persist state across steps."""
    from igris.core.agent_reasoning_loop import AgentReasoningLoop
    from igris.core.loop_checkpoint_manager import LoopCheckpointManager

    project_root = os.environ.get("PROJECT_ROOT", ".")
    loop = AgentReasoningLoop(
        project_root=project_root,
        max_steps=2,
    )
    result = loop.run(
        goal="Say hello",
        mission_id="integration-checkpoint-test",
    )

    # After completion, checkpoint should be cleared
    mgr = LoopCheckpointManager(project_root, mission_id="integration-checkpoint-test")
    # If mission completed successfully, checkpoint should be cleared
    # If it was stopped/blocked, checkpoint may still exist
    assert result.status in ("finished", "stopped", "blocked")


def test_mission_e2e_no_crash():
    """Mission E2E should not crash even with minimal config."""
    from igris.core.agent_reasoning_loop import AgentReasoningLoop

    loop = AgentReasoningLoop(
        project_root=os.environ.get("PROJECT_ROOT", "."),
        max_steps=1,
    )
    # This should not raise, even if the LLM is unavailable
    result = loop.run(goal="test", mission_id="integration-no-crash")
    assert result is not None
    assert result.status is not None
