from unittest.mock import MagicMock, patch

from igris.core.agent_contracts import AgentCoordinator, validate_agent_action
from igris.core.agent_registry import ESCALATION_PATH, OUTPUT_SCHEMA, ROLES, TOOL_PERMISSIONS


def test_violation_for_role_skips_step():
    ok, _ = validate_agent_action("cost_guardian", "edit_file")
    assert ok is False


def test_violation_recorded_as_lesson(tmp_path):
    with patch("igris.core.memory_graph.MemoryGraph") as mg_cls:
        mg = mg_cls.return_value
        mg.query_lessons_for_failure_class.return_value = []
        allowed, _ = AgentCoordinator(str(tmp_path)).check_and_record("cost_guardian", "edit_file", "goal")
        assert not allowed
        mg.add_node.assert_called()


def test_coordinator_consults_graph_for_history(tmp_path):
    with patch("igris.core.memory_graph.MemoryGraph") as mg_cls:
        mg = mg_cls.return_value
        mg.query_lessons_for_failure_class.return_value = [{"content": {"role": "cost_guardian", "action_type": "edit_file"}}, {"content": {"role": "cost_guardian", "action_type": "edit_file"}}]
        AgentCoordinator(str(tmp_path)).check_and_record("cost_guardian", "edit_file", "goal")
        assert any(call.args[0] == "run_event" for call in mg.add_node.call_args_list)


def test_coordinator_role_allowed(tmp_path):
    allowed, reason = AgentCoordinator(str(tmp_path)).check_and_record("backend_coder", "edit_file", "goal")
    assert allowed is True
    assert reason == ""


def test_coordinator_unknown_role_failopen(tmp_path):
    allowed, _ = AgentCoordinator(str(tmp_path)).check_and_record("unknown", "edit_file", "goal")
    assert allowed is True


def test_coordinator_role_has_memory_write():
    assert "memory_graph_write" in TOOL_PERMISSIONS["memory_architect"]


def test_coordinator_graph_unavailable_failopen(tmp_path):
    with patch("igris.core.memory_graph.MemoryGraph", side_effect=RuntimeError("down")):
        allowed, _ = AgentCoordinator(str(tmp_path)).check_and_record("cost_guardian", "edit_file", "goal")
        assert allowed is False


def test_output_schema_defined_for_all_roles():
    for role in ROLES:
        assert role in OUTPUT_SCHEMA


def test_escalation_path_defined():
    for role in ROLES:
        assert role in ESCALATION_PATH


def test_coordinator_no_direct_tools():
    assert "run_tests" not in TOOL_PERMISSIONS["coordinator"]
