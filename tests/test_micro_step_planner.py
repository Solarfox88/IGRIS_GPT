from __future__ import annotations

from unittest.mock import patch

from igris.core.agent_action_schema import AgentAction
from igris.core.agent_reasoning_loop import AgentReasoningLoop
from igris.core.micro_step_planner import MicroStep, MicroStepPlanner


def test_goal_type_endpoint_initializes_discover():
    p = MicroStepPlanner()
    st = p.initialize("Add /api/ping endpoint in FastAPI route", {})
    assert st.current_step == MicroStep.DISCOVER
    assert st.goal_type == "endpoint_api"


def test_goal_type_bugfix_initializes_discover():
    p = MicroStepPlanner()
    st = p.initialize("Fix failing test traceback error", {})
    assert st.current_step == MicroStep.DISCOVER
    assert st.goal_type == "bugfix"


def test_goal_type_add_test_initializes_discover():
    p = MicroStepPlanner()
    st = p.initialize("add test for pytest coverage", {})
    assert st.current_step == MicroStep.DISCOVER
    assert st.goal_type == "add_test"


def test_goal_type_doc_config_uses_non_test_path():
    p = MicroStepPlanner()
    st = p.initialize("Update README.md docs and config", {})
    st = p.update_after_action(st, {"action_type": "find_files", "parameters": {}}, {"success": True, "discovered_files": ["README.md"]})
    st = p.update_after_action(st, {"action_type": "read_file_range", "parameters": {"path": "README.md"}}, {"success": True})
    st = p.update_after_action(st, {"action_type": "write_file", "parameters": {"path": "README.md"}}, {"success": True})
    assert st.current_step == MicroStep.VERIFY


def test_generic_fallback_non_crashing():
    p = MicroStepPlanner()
    st = p.initialize("Do something generic", {})
    d = p.next_directive(st, {})
    assert d.expected_step == MicroStep.DISCOVER


def test_discover_to_read_when_files_found():
    p = MicroStepPlanner()
    st = p.initialize("bug fix", {})
    st = p.update_after_action(st, {"action_type": "find_files", "parameters": {}}, {"success": True, "discovered_files": ["a.py"]})
    assert st.current_step == MicroStep.READ


def test_read_to_modify_when_file_read():
    p = MicroStepPlanner()
    st = p.initialize("fix bug", {})
    st.current_step = MicroStep.READ
    st = p.update_after_action(st, {"action_type": "read_file_range", "parameters": {"path": "a.py"}}, {"success": True})
    assert st.current_step == MicroStep.MODIFY


def test_modify_to_test_when_file_modified():
    p = MicroStepPlanner()
    st = p.initialize("fix bug", {})
    st.current_step = MicroStep.MODIFY
    st = p.update_after_action(st, {"action_type": "write_file", "parameters": {"path": "a.py"}}, {"success": True})
    assert st.current_step == MicroStep.TEST


def test_test_to_verify_after_tests():
    p = MicroStepPlanner()
    st = p.initialize("fix bug", {})
    st.current_step = MicroStep.TEST
    st = p.update_after_action(st, {"action_type": "run_tests", "parameters": {}}, {"success": True})
    assert st.current_step == MicroStep.VERIFY


def test_verify_to_finish_after_git_verification():
    p = MicroStepPlanner()
    st = p.initialize("fix bug", {})
    st.current_step = MicroStep.VERIFY
    st = p.update_after_action(st, {"action_type": "git_diff", "parameters": {}}, {"success": True})
    assert st.current_step == MicroStep.FINISH


def test_repeated_discovery_redirected_when_targets_exist():
    p = MicroStepPlanner()
    st = p.initialize("fix bug", {})
    st.current_step = MicroStep.READ
    st.discovered_files = ["igris/core/x.py"]
    should, reason = p.should_redirect_action(st, {"action_type": "find_files", "reason": "search again", "parameters": {"pattern": "*.py"}})
    assert should is True
    assert "Do not repeat discovery" in reason


def test_empty_discovery_allows_more_discovery():
    p = MicroStepPlanner()
    st = p.initialize("fix bug", {})
    st.current_step = MicroStep.READ
    st.discovered_files = []
    should, _ = p.should_redirect_action(st, {"action_type": "find_files", "reason": "search again", "parameters": {"pattern": "*.py"}})
    assert should is False


def test_wrong_file_context_allows_controlled_rediscovery():
    p = MicroStepPlanner()
    st = p.initialize("fix bug", {})
    st.current_step = MicroStep.MODIFY
    st.discovered_files = ["a.py"]
    should, _ = p.should_redirect_action(st, {"action_type": "find_files", "reason": "wrong file edited", "parameters": {"pattern": "*.py"}})
    assert should is False


def test_planner_state_serializable():
    p = MicroStepPlanner()
    st = p.initialize("fix bug", {})
    payload = st.to_dict()
    assert payload["current_step"] == "discover"
    assert payload["goal_type"] == "bugfix"


def test_to_context_concise_directives():
    p = MicroStepPlanner()
    st = p.initialize("fix bug", {})
    d = p.next_directive(st, {})
    ctx = p.to_context(st, d)
    assert ctx["micro_step_current"] == "discover"
    assert "micro_step_instruction" in ctx
    assert len(ctx["micro_step_instruction"]) <= 240


def test_reasoning_loop_includes_micro_step_context():
    loop = AgentReasoningLoop(project_root="/tmp", max_steps=1)
    loop._ensure_micro_step_state("fix bug")
    pkt = loop._build_context("fix bug", "m1")
    assert loop._world_state.get("micro_step_current")
    assert loop._world_state.get("micro_step_allowed_action_families")
    assert "micro_step_current" in pkt.state_context


def test_reasoning_loop_updates_planner_after_action():
    loop = AgentReasoningLoop(project_root="/tmp", max_steps=1)
    act = AgentAction(mode="coder", action_type="find_files", reason="discover", parameters={"pattern": "*.py"})

    def _exec(action, route):
        return {"success": True, "summary": "ok", "result_data": ["igris/core/agent_reasoning_loop.py"]}

    with patch.object(loop, "_decide_action", return_value=(act, [])), patch.object(loop, "_execute_action", side_effect=_exec):
        loop._execute_step(1, "fix bug", "m1")
    assert loop._world_state.get("micro_step_state", {}).get("current_step") in {"read", "modify", "plan"}


def test_reasoning_loop_emits_micro_step_redirect_observation():
    loop = AgentReasoningLoop(project_root="/tmp", max_steps=2)
    loop._world_state["discovered_files"] = ["igris/core/agent_reasoning_loop.py"]
    loop._ensure_micro_step_state("fix bug")
    loop._micro_step_state.current_step = MicroStep.READ
    act = AgentAction(mode="coder", action_type="find_files", reason="discover again", parameters={"pattern": "*.py"})

    def _exec(action, route):
        if action.action_type == "read_file_range":
            return {"success": True, "summary": "read", "result_data": "content"}
        return {"success": True, "summary": "ok", "result_data": ["x.py"]}

    with patch.object(loop, "_decide_action", return_value=(act, [])), patch.object(loop, "_execute_action", side_effect=_exec):
        step = loop._execute_step(1, "fix bug", "m1")
    assert step.action_type == "read_file_range"
    assert loop._world_state.get("micro_step_redirects")
