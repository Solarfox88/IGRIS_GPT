"""Tests for igris/core/tool_output_compactor.py (issue #531 — TokenJuice).

Validates ToolOutputCompactor rules and wiring into the reasoning loop.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from igris.core.tool_output_compactor import CompactorConfig, ToolOutputCompactor


# ---------------------------------------------------------------------------
# ToolOutputCompactor.compress()
# ---------------------------------------------------------------------------

class TestToolOutputCompactor:
    def test_empty_string_returned_unchanged(self):
        c = ToolOutputCompactor()
        assert c.compress("") == ""

    def test_strips_ansi_codes(self):
        text = "\x1b[31mERROR\x1b[0m: something failed"
        result = ToolOutputCompactor().compress(text)
        assert "\x1b[" not in result
        assert "ERROR" in result

    def test_deduplicates_consecutive_identical_lines(self):
        text = "dot\ndot\ndot\ndot\n"
        result = ToolOutputCompactor().compress(text)
        # Must have fewer 'dot' occurrences than input
        assert result.count("dot") < 4

    def test_large_output_hard_truncated(self):
        text = "x" * 200_000
        c = ToolOutputCompactor()
        result = c.compress(text)
        assert len(result) <= c.config.max_chars + 50  # allow for truncation marker

    def test_test_runner_source_type_applies_tail_first(self):
        # Last lines should be preserved when source_type='test_runner'
        lines = ["line_" + str(i) for i in range(100)]
        text = "\n".join(lines)
        c = ToolOutputCompactor()
        result = c.compress(text, source_type="test_runner")
        # Last lines should be in result
        assert "line_99" in result

    def test_generic_source_type_does_not_tail(self):
        lines = ["line_" + str(i) for i in range(100)]
        text = "\n".join(lines)
        c = ToolOutputCompactor()
        result = c.compress(text, source_type="generic")
        # Should have content (not just tailed)
        assert len(result) > 0

    def test_compactor_config_custom_max(self):
        config = CompactorConfig(max_chars=50)
        c = ToolOutputCompactor(config=config)
        text = "a" * 500
        result = c.compress(text)
        assert len(result) <= 100  # some overhead for truncation marker


# ---------------------------------------------------------------------------
# Wiring into agent_reasoning_loop._execute_step
# ---------------------------------------------------------------------------

class TestCompactorWiring:
    def test_compactor_called_on_string_result_data(self, tmp_path):
        """ToolOutputCompactor.compress must be called on string result_data."""
        from igris.core.agent_reasoning_loop import AgentReasoningLoop

        loop = AgentReasoningLoop(project_root=str(tmp_path), max_steps=1)

        fake_action = MagicMock()
        fake_action.action_type = "run_tests"
        fake_action.reason = "run tests"
        fake_action.parameters = {}
        fake_action.risk_hint = "low"
        fake_action.confidence = 0.9

        large_output = "test output line\n" * 1000

        with patch.object(loop, "_build_context", return_value=MagicMock()), \
             patch.object(loop, "_decide_action", return_value=(fake_action, [])), \
             patch.object(loop, "_check_anti_repeat", return_value=None), \
             patch.object(loop, "_validate_action", return_value=MagicMock(valid=True)), \
             patch("igris.core.agent_action_schema.get_action_route", return_value="tool_runtime"), \
             patch.object(loop, "_execute_action",
                          return_value={"success": True, "summary": "ok",
                                        "result_data": large_output}), \
             patch("igris.core.tool_output_compactor.ToolOutputCompactor.compress",
                   wraps=ToolOutputCompactor().compress) as mock_compress:
            loop._execute_step(1, "test goal", "mission1")
            mock_compress.assert_called()

    def test_compactor_error_does_not_crash_step(self, tmp_path):
        """If compactor raises, step must still succeed (best-effort)."""
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
                          return_value={"success": True, "summary": "ok",
                                        "result_data": "some output"}), \
             patch("igris.core.tool_output_compactor.ToolOutputCompactor.compress",
                   side_effect=RuntimeError("compactor internal error")):
            step = loop._execute_step(1, "test goal", "mission1")
            # Must not propagate the error
            assert step.outcome in {"success", "failure", "blocked", "skipped"}

    def test_compactor_not_called_for_non_string_result(self, tmp_path):
        """Compactor should only run on string result_data, not dicts."""
        from igris.core.agent_reasoning_loop import AgentReasoningLoop

        loop = AgentReasoningLoop(project_root=str(tmp_path), max_steps=1)

        fake_action = MagicMock()
        fake_action.action_type = "git_status"
        fake_action.reason = "check"
        fake_action.parameters = {}
        fake_action.risk_hint = "low"
        fake_action.confidence = 0.9

        with patch.object(loop, "_build_context", return_value=MagicMock()), \
             patch.object(loop, "_decide_action", return_value=(fake_action, [])), \
             patch.object(loop, "_check_anti_repeat", return_value=None), \
             patch.object(loop, "_validate_action", return_value=MagicMock(valid=True)), \
             patch("igris.core.agent_action_schema.get_action_route", return_value="tool_runtime"), \
             patch.object(loop, "_execute_action",
                          return_value={"success": True, "summary": "ok",
                                        "result_data": {"files": []}}), \
             patch("igris.core.tool_output_compactor.ToolOutputCompactor.compress") as mock_compress:
            loop._execute_step(1, "test goal", "mission1")
            # Compactor should NOT be called for non-string result_data
            mock_compress.assert_not_called()
