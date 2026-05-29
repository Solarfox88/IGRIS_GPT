"""Tests for igris/core/tool_tracker.py (issue #534).

Validates ToolTracker persistence, stats computation, unreliable tool detection,
and wiring into agent_reasoning_loop._execute_step().
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from igris.core.tool_tracker import ToolStats, ToolTracker


# ---------------------------------------------------------------------------
# Basic record and stats
# ---------------------------------------------------------------------------

class TestToolTrackerRecord:
    def test_record_success_increments_total_and_success(self, tmp_path):
        tt = ToolTracker(str(tmp_path))
        tt.record("pytest", success=True, duration_ms=500.0)
        s = tt.get_stats("pytest")
        assert s.total_calls == 1
        assert s.successes == 1
        assert s.failures == 0

    def test_record_failure_increments_failure(self, tmp_path):
        tt = ToolTracker(str(tmp_path))
        tt.record("gh", success=False, duration_ms=100.0, error_snippet="timeout")
        s = tt.get_stats("gh")
        assert s.failures == 1
        assert "timeout" in s.common_error_patterns[0]

    def test_avg_duration_running_average(self, tmp_path):
        tt = ToolTracker(str(tmp_path))
        tt.record("ruff", success=True, duration_ms=100.0)
        tt.record("ruff", success=True, duration_ms=300.0)
        s = tt.get_stats("ruff")
        assert s.avg_duration_ms == pytest.approx(200.0)

    def test_multiple_tools_tracked_independently(self, tmp_path):
        tt = ToolTracker(str(tmp_path))
        tt.record("git", success=True, duration_ms=10.0)
        tt.record("pytest", success=False, duration_ms=50.0)
        assert tt.get_stats("git").successes == 1
        assert tt.get_stats("pytest").failures == 1

    def test_unknown_tool_returns_none(self, tmp_path):
        tt = ToolTracker(str(tmp_path))
        assert tt.get_stats("does_not_exist") is None

    def test_error_patterns_deduplicated(self, tmp_path):
        tt = ToolTracker(str(tmp_path))
        tt.record("gh", success=False, duration_ms=10.0, error_snippet="timeout")
        tt.record("gh", success=False, duration_ms=10.0, error_snippet="timeout")
        s = tt.get_stats("gh")
        assert s.common_error_patterns.count("timeout") == 1

    def test_error_patterns_capped_at_max(self, tmp_path):
        tt = ToolTracker(str(tmp_path))
        for i in range(10):
            tt.record("gh", success=False, duration_ms=5.0, error_snippet=f"error_{i}")
        s = tt.get_stats("gh")
        assert len(s.common_error_patterns) <= tt.max_error_patterns


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestToolTrackerPersistence:
    def test_stats_survive_reload(self, tmp_path):
        tt = ToolTracker(str(tmp_path))
        tt.record("pytest", success=True, duration_ms=300.0)
        tt2 = ToolTracker(str(tmp_path))
        s = tt2.get_stats("pytest")
        assert s is not None
        assert s.total_calls == 1

    def test_atomic_write_no_tmp_leftover(self, tmp_path):
        tt = ToolTracker(str(tmp_path))
        tt.record("git", success=True, duration_ms=5.0)
        assert not list(tmp_path.rglob("*.tmp"))

    def test_corrupt_file_does_not_crash(self, tmp_path):
        (tmp_path / ".igris").mkdir()
        (tmp_path / ".igris" / "tool_stats.json").write_text("GARBAGE")
        tt = ToolTracker(str(tmp_path))  # should not raise
        assert tt.get_all_stats() == {}


# ---------------------------------------------------------------------------
# get_all_stats / get_unreliable_tools
# ---------------------------------------------------------------------------

class TestToolTrackerQuery:
    def test_get_all_stats_returns_all(self, tmp_path):
        tt = ToolTracker(str(tmp_path))
        tt.record("git", success=True, duration_ms=5.0)
        tt.record("pytest", success=False, duration_ms=200.0)
        all_stats = tt.get_all_stats()
        assert "git" in all_stats
        assert "pytest" in all_stats

    def test_unreliable_tools_detection(self, tmp_path):
        tt = ToolTracker(str(tmp_path))
        for _ in range(3):
            tt.record("flaky_tool", success=True, duration_ms=10.0)
        for _ in range(7):
            tt.record("flaky_tool", success=False, duration_ms=10.0)
        unreliable = tt.get_unreliable_tools(min_calls=5, max_success_rate=0.6)
        assert "flaky_tool" in unreliable

    def test_reliable_tool_not_in_unreliable(self, tmp_path):
        tt = ToolTracker(str(tmp_path))
        for _ in range(10):
            tt.record("pytest", success=True, duration_ms=10.0)
        unreliable = tt.get_unreliable_tools(min_calls=5)
        assert "pytest" not in unreliable

    def test_below_min_calls_not_in_unreliable(self, tmp_path):
        tt = ToolTracker(str(tmp_path))
        tt.record("new_tool", success=False, duration_ms=10.0)
        unreliable = tt.get_unreliable_tools(min_calls=5)
        assert "new_tool" not in unreliable


# ---------------------------------------------------------------------------
# Wiring into agent_reasoning_loop
# ---------------------------------------------------------------------------

class TestToolTrackerWiring:
    def test_tool_tracker_called_after_execute_action(self, tmp_path):
        """ToolTracker.record must be called during _execute_step."""
        from igris.core.agent_reasoning_loop import AgentReasoningLoop

        loop = AgentReasoningLoop(project_root=str(tmp_path), max_steps=1)

        # Mock dependencies to complete one step
        fake_action = MagicMock()
        fake_action.action_type = "git_status"
        fake_action.reason = "check repo"
        fake_action.parameters = {}
        fake_action.risk_hint = "low"
        fake_action.confidence = 0.9

        with patch.object(loop, "_build_context", return_value=MagicMock()), \
             patch.object(loop, "_decide_action", return_value=(fake_action, [])), \
             patch.object(loop, "_check_anti_repeat", return_value=None), \
             patch.object(loop, "_validate_action", return_value=MagicMock(valid=True)), \
             patch("igris.core.agent_action_schema.get_action_route", return_value="tool_runtime"), \
             patch.object(loop, "_execute_action", return_value={"success": True, "summary": "ok"}), \
             patch("igris.core.tool_tracker.ToolTracker.record") as mock_record:
            loop._execute_step(1, "test goal", "mission1")
            mock_record.assert_called_once()
            call_kwargs = mock_record.call_args
            assert call_kwargs[1]["tool_name"] == "git_status" or call_kwargs[0][0] == "git_status"

    def test_tool_tracker_error_does_not_crash_step(self, tmp_path):
        """If ToolTracker raises, _execute_step must still succeed."""
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
             patch.object(loop, "_execute_action", return_value={"success": True, "summary": "ok"}), \
             patch("igris.core.tool_tracker.ToolTracker.record",
                   side_effect=RuntimeError("storage failure")):
            step = loop._execute_step(1, "test goal", "mission1")
            # Must not propagate the error
            assert step.outcome in {"success", "failure", "blocked", "skipped"}
