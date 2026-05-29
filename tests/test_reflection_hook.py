"""Tests for igris/core/reflection_hook.py (issue #532).

Validates ReflectionHook complexity trigger, per-session throttling,
LLM extraction, and memory graph persistence wiring.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, call

import pytest

from igris.core.reflection_hook import ReflectionHook, ReflectionOutput, ReflectionConfig


# ---------------------------------------------------------------------------
# ReflectionConfig
# ---------------------------------------------------------------------------

class TestReflectionConfig:
    def test_defaults(self):
        cfg = ReflectionConfig()
        assert cfg.enabled is True
        assert cfg.max_reflections_per_session == 10
        assert cfg.min_tool_calls == 3
        assert cfg.min_response_chars == 500
        assert cfg.model_profile == "local_light"

    def test_from_file(self, tmp_path):
        data = {
            "enabled": False,
            "max_reflections_per_session": 5,
            "min_tool_calls": 2,
            "min_response_chars": 300,
            "model_profile": "cloud_strong",
        }
        cfg_file = tmp_path / ".igris" / "reflection_config.json"
        cfg_file.parent.mkdir()
        cfg_file.write_text(json.dumps(data))
        cfg = ReflectionConfig.from_file(str(cfg_file))
        assert cfg.enabled is False
        assert cfg.max_reflections_per_session == 5
        assert cfg.min_tool_calls == 2
        assert cfg.min_response_chars == 300
        assert cfg.model_profile == "cloud_strong"

    def test_from_file_missing_uses_defaults(self, tmp_path):
        cfg = ReflectionConfig.from_file(str(tmp_path / "nonexistent.json"))
        assert cfg.enabled is True  # default


# ---------------------------------------------------------------------------
# ReflectionHook.should_reflect()
# ---------------------------------------------------------------------------

class TestShouldReflect:
    def _hook(self, tmp_path, config=None):
        return ReflectionHook(str(tmp_path), config=config)

    def test_not_triggered_when_disabled(self, tmp_path):
        hook = self._hook(tmp_path, config={"enabled": False})
        step = {"tool_count": 10, "response": "x" * 1000}
        assert hook.should_reflect(step) is False

    def test_triggered_by_tool_count(self, tmp_path):
        hook = self._hook(tmp_path, config={"min_tool_calls": 3})
        step = {"tool_count": 3, "response": "short"}
        assert hook.should_reflect(step) is True

    def test_not_triggered_by_low_tool_count(self, tmp_path):
        hook = self._hook(tmp_path, config={"min_tool_calls": 3, "min_response_chars": 9999})
        step = {"tool_count": 1, "response": "short"}
        assert hook.should_reflect(step) is False

    def test_triggered_by_response_length(self, tmp_path):
        hook = self._hook(tmp_path, config={"min_tool_calls": 99, "min_response_chars": 100})
        step = {"tool_count": 0, "response": "x" * 101}
        assert hook.should_reflect(step) is True

    def test_throttled_when_budget_exhausted(self, tmp_path):
        hook = self._hook(tmp_path, config={"max_reflections_per_session": 2, "min_tool_calls": 1})
        hook._reflections_this_session = 2
        step = {"tool_count": 5, "response": "x" * 1000}
        assert hook.should_reflect(step) is False

    def test_not_throttled_before_budget_exhausted(self, tmp_path):
        hook = self._hook(tmp_path, config={"max_reflections_per_session": 5, "min_tool_calls": 1})
        hook._reflections_this_session = 4
        step = {"tool_count": 5, "response": "short"}
        assert hook.should_reflect(step) is True


# ---------------------------------------------------------------------------
# ReflectionHook._parse_llm_output()
# ---------------------------------------------------------------------------

class TestParseLlmOutput:
    def _hook(self, tmp_path):
        return ReflectionHook(str(tmp_path))

    def test_parses_valid_json(self, tmp_path):
        hook = self._hook(tmp_path)
        text = json.dumps({
            "observations": ["test X failed"],
            "patterns": ["use --tb=short"],
            "user_preferences": ["no verbose output"],
        })
        out = hook._parse_llm_output(text)
        assert out is not None
        assert "test X failed" in out.observations
        assert "use --tb=short" in out.patterns
        assert "no verbose output" in out.user_preferences

    def test_strips_markdown_fences(self, tmp_path):
        hook = self._hook(tmp_path)
        text = '```json\n{"observations": ["ok"], "patterns": [], "user_preferences": []}\n```'
        out = hook._parse_llm_output(text)
        assert out is not None
        assert "ok" in out.observations

    def test_malformed_json_returns_none(self, tmp_path):
        hook = self._hook(tmp_path)
        out = hook._parse_llm_output("not json at all {broken}")
        assert out is None

    def test_empty_json_returns_empty_output(self, tmp_path):
        hook = self._hook(tmp_path)
        out = hook._parse_llm_output('{"observations": [], "patterns": [], "user_preferences": []}')
        assert out is not None
        assert out.observations == []
        assert out.patterns == []

    def test_items_truncated_at_120_chars(self, tmp_path):
        hook = self._hook(tmp_path)
        long_item = "x" * 200
        out = hook._parse_llm_output(json.dumps({"observations": [long_item], "patterns": [], "user_preferences": []}))
        assert out is not None
        assert len(out.observations[0]) == 120


# ---------------------------------------------------------------------------
# ReflectionHook.on_step_complete() — LLM call and persistence
# ---------------------------------------------------------------------------

class TestOnStepComplete:
    def _hook(self, tmp_path, config=None):
        return ReflectionHook(str(tmp_path), config=config or {"min_tool_calls": 1, "min_response_chars": 9999})

    def test_no_reflect_when_should_reflect_false(self, tmp_path):
        hook = self._hook(tmp_path, config={"enabled": False})
        with patch.object(hook, "_call_llm") as mock_llm:
            result = hook.on_step_complete({"tool_count": 10, "response": "x" * 1000}, goal="test")
        assert result is None
        mock_llm.assert_not_called()

    def test_counter_increments_on_success(self, tmp_path):
        hook = self._hook(tmp_path)
        mock_output = ReflectionOutput(observations=["obs1"], patterns=["pat1"], user_preferences=[])
        with patch.object(hook, "_call_llm", return_value=mock_output), \
             patch.object(hook, "_persist"):
            hook.on_step_complete({"tool_count": 5}, goal="test")
        assert hook._reflections_this_session == 1

    def test_counter_not_incremented_on_empty_output(self, tmp_path):
        hook = self._hook(tmp_path)
        mock_output = ReflectionOutput(observations=[], patterns=[], user_preferences=[])
        with patch.object(hook, "_call_llm", return_value=mock_output), \
             patch.object(hook, "_persist"):
            hook.on_step_complete({"tool_count": 5}, goal="test")
        assert hook._reflections_this_session == 0

    def test_persist_called_with_output(self, tmp_path):
        hook = self._hook(tmp_path)
        mock_output = ReflectionOutput(observations=["obs"], patterns=[], user_preferences=[])
        with patch.object(hook, "_call_llm", return_value=mock_output), \
             patch.object(hook, "_persist") as mock_persist:
            hook.on_step_complete({"tool_count": 5}, goal="Fix #532")
        mock_persist.assert_called_once()

    def test_llm_failure_returns_none(self, tmp_path):
        hook = self._hook(tmp_path)
        with patch.object(hook, "_call_llm", return_value=None):
            result = hook.on_step_complete({"tool_count": 5}, goal="test")
        assert result is None
        assert hook._reflections_this_session == 0

    def test_exception_in_call_returns_none(self, tmp_path):
        hook = self._hook(tmp_path)
        with patch.object(hook, "_call_llm", side_effect=RuntimeError("oops")):
            result = hook.on_step_complete({"tool_count": 5}, goal="test")
        # on_step_complete catches all exceptions
        assert result is None


# ---------------------------------------------------------------------------
# ReflectionHook._persist() — MemoryGraph node insertion
# ---------------------------------------------------------------------------

class TestPersist:
    def test_persists_observations_and_patterns(self, tmp_path):
        hook = ReflectionHook(str(tmp_path))
        output = ReflectionOutput(
            observations=["test X failed with ImportError"],
            patterns=["always import before use"],
            user_preferences=[],
        )
        mock_mg = MagicMock()
        add_calls = []
        mock_mg.add_node.side_effect = lambda *a, **kw: add_calls.append((a, kw))

        with patch("igris.core.memory_graph.MemoryGraph", return_value=mock_mg):
            hook._persist(output, goal="Fix #532", project_root=str(tmp_path))

        # Should have 2 add_node calls (1 obs + 1 pattern)
        assert len(add_calls) == 2
        # Both should be 'lesson' nodes
        node_types = [a[0] for a, _ in add_calls]
        assert all(t == "lesson" for t in node_types)
        # Check source tag
        contents = [a[1] for a, _ in add_calls]
        assert all(c.get("source") == "reflection_hook" for c in contents)
        # Check kinds
        kinds = [c.get("kind") for c in contents]
        assert "observation" in kinds
        assert "pattern" in kinds

    def test_persist_memory_error_is_swallowed(self, tmp_path):
        hook = ReflectionHook(str(tmp_path))
        output = ReflectionOutput(observations=["obs"], patterns=[], user_preferences=[])
        with patch("igris.core.memory_graph.MemoryGraph", side_effect=RuntimeError("DB error")):
            hook._persist(output, goal="test", project_root=str(tmp_path))  # must not raise


# ---------------------------------------------------------------------------
# Wiring into agent_reasoning_loop._execute_step
# ---------------------------------------------------------------------------

class TestReflectionHookWiring:
    def test_reflection_hook_called_after_step(self, tmp_path):
        """ReflectionHook.on_step_complete must be called after _execute_step."""
        from igris.core.agent_reasoning_loop import AgentReasoningLoop

        loop = AgentReasoningLoop(project_root=str(tmp_path), max_steps=1)

        fake_action = MagicMock()
        fake_action.action_type = "run_tests"
        fake_action.reason = "run tests"
        fake_action.parameters = {}
        fake_action.risk_hint = "low"
        fake_action.confidence = 0.9

        with patch.object(loop, "_build_context", return_value=MagicMock()), \
             patch.object(loop, "_decide_action", return_value=(fake_action, [])), \
             patch.object(loop, "_check_anti_repeat", return_value=None), \
             patch.object(loop, "_validate_action", return_value=MagicMock(valid=True)), \
             patch("igris.core.agent_action_schema.get_action_route", return_value="tool_runtime"), \
             patch.object(loop, "_execute_action",
                          return_value={"success": True, "summary": "ok", "result_data": "output"}), \
             patch("igris.core.reflection_hook.ReflectionHook.on_step_complete") as mock_reflect:
            loop._execute_step(1, "Fix #532", "mission1")
            mock_reflect.assert_called()

    def test_reflection_hook_error_does_not_crash_step(self, tmp_path):
        """If ReflectionHook raises, _execute_step must still return a valid step."""
        from igris.core.agent_reasoning_loop import AgentReasoningLoop

        loop = AgentReasoningLoop(project_root=str(tmp_path), max_steps=1)

        fake_action = MagicMock()
        fake_action.action_type = "run_tests"
        fake_action.reason = "run tests"
        fake_action.parameters = {}
        fake_action.risk_hint = "low"
        fake_action.confidence = 0.9

        with patch.object(loop, "_build_context", return_value=MagicMock()), \
             patch.object(loop, "_decide_action", return_value=(fake_action, [])), \
             patch.object(loop, "_check_anti_repeat", return_value=None), \
             patch.object(loop, "_validate_action", return_value=MagicMock(valid=True)), \
             patch("igris.core.agent_action_schema.get_action_route", return_value="tool_runtime"), \
             patch.object(loop, "_execute_action",
                          return_value={"success": True, "summary": "ok", "result_data": "output"}), \
             patch("igris.core.reflection_hook.ReflectionHook.on_step_complete",
                   side_effect=RuntimeError("reflection crash")):
            step = loop._execute_step(1, "Fix #532", "mission1")
            assert step.outcome in {"success", "failure", "blocked", "skipped", "finish"}
