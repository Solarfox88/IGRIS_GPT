"""Tests for WorkSession command history and supervisor wiring (issue #540)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from igris.core.work_session import WorkSession, WorkPhase


# ---------------------------------------------------------------------------
# WorkSession.remember() with commands_run
# ---------------------------------------------------------------------------

class TestWorkSessionRemember:
    def test_remember_without_commands_does_not_crash(self, tmp_path):
        ws = WorkSession.create("Fix #540", mission_id="m1")
        ws.remember(str(tmp_path))  # should not raise

    def test_remember_with_commands_saves_project_fact(self, tmp_path):
        ws = WorkSession.create("Fix #540", mission_id="m1")
        commands = [
            {"action_type": "run_tests", "outcome": "success", "duration_ms": 200},
            {"action_type": "run_tests", "outcome": "failure", "duration_ms": 150},
            {"action_type": "git_diff", "outcome": "success", "duration_ms": 30},
        ]

        mock_mg = MagicMock()
        add_calls = []
        mock_mg.add_node.side_effect = lambda *a, **kw: add_calls.append((a, kw))
        with patch("igris.core.memory_graph.MemoryGraph", return_value=mock_mg):
            ws.remember(str(tmp_path), commands_run=commands)

        # add_node called as mock_mg.add_node(node_type, content, **kw)
        # so a = (node_type, content, ...) — no self prefix
        node_types = [a[0] for a, _ in add_calls]
        assert "project_fact" in node_types, "command_history project_fact not saved"

        # Find the command_history node
        fact_args = next((a for a, _ in add_calls if a[0] == "project_fact"), None)
        assert fact_args is not None
        fact_content = fact_args[1]  # second arg: content dict
        assert fact_content.get("fact_type") == "command_history"
        tool_summary = fact_content.get("tool_summary", {})
        assert "run_tests" in tool_summary
        # run_tests: 1 success out of 2 = 0.5
        assert tool_summary["run_tests"]["success_rate"] == pytest.approx(0.5)
        assert tool_summary["run_tests"]["calls"] == 2

    def test_remember_empty_commands_does_not_save_project_fact(self, tmp_path):
        ws = WorkSession.create("Fix #540")
        mock_mg = MagicMock()
        add_calls = []
        mock_mg.add_node.side_effect = lambda *a, **kw: add_calls.append((a, kw))
        with patch("igris.core.memory_graph.MemoryGraph", return_value=mock_mg):
            ws.remember(str(tmp_path), commands_run=[])

        node_types = [a[0] for a, _ in add_calls]
        assert "project_fact" not in node_types

    def test_remember_memory_error_is_swallowed(self, tmp_path):
        ws = WorkSession.create("Fix #540")
        commands = [{"action_type": "pytest", "outcome": "success", "duration_ms": 100}]
        with patch("igris.core.memory_graph.MemoryGraph", side_effect=RuntimeError("DB locked")):
            ws.remember(str(tmp_path), commands_run=commands)  # must not raise


# ---------------------------------------------------------------------------
# Supervisor.run() — WorkSession wiring
# ---------------------------------------------------------------------------

class TestSupervisorWorkSessionWiring:
    def _make_supervisor(self, tmp_path):
        from igris.core.self_repair_supervisor import SelfRepairSupervisor
        sup = SelfRepairSupervisor(project_root=str(tmp_path))
        ok_result = MagicMock()
        ok_result.success = True
        ok_result.output = ""
        sup.backend = MagicMock()
        sup.backend.git_status.return_value = ok_result
        sup.backend.git_log_head.return_value = ok_result
        sup.backend.api_helper_is_configured.return_value = False
        return sup

    def test_work_session_created_on_run(self, tmp_path):
        """WorkSession.create must be called during supervisor.run()."""
        from igris.core.self_repair_supervisor import SelfRepairSupervisor, RankSupervisorConfig, SupervisorRun
        sup = self._make_supervisor(tmp_path)
        config = RankSupervisorConfig(goal="Fix #540", rank_id="test", dry_run=True)
        run = SupervisorRun(run_id="ws-test", rank_id="test")

        with patch("igris.core.work_session.WorkSession.create",
                   wraps=WorkSession.create) as mock_create, \
             patch.object(sup, "_run_preflight_phase",
                          return_value=(run, None)):  # preflight blocks immediately
            sup.run(config, run=run)
            mock_create.assert_called_once()

    def test_work_session_error_does_not_crash_run(self, tmp_path):
        """If WorkSession creation raises, supervisor.run() must still work."""
        from igris.core.self_repair_supervisor import SelfRepairSupervisor, RankSupervisorConfig, SupervisorRun
        sup = self._make_supervisor(tmp_path)
        config = RankSupervisorConfig(goal="Fix #540", rank_id="test", dry_run=True)
        run = SupervisorRun(run_id="ws-err", rank_id="test")

        with patch("igris.core.work_session.WorkSession.create",
                   side_effect=RuntimeError("import failure")), \
             patch.object(sup, "_run_preflight_phase",
                          return_value=(run, None)):
            result = sup.run(config, run=run)
            assert result is not None  # must return the run regardless

    def test_remember_called_on_preflight_block(self, tmp_path):
        """When preflight blocks, remember() should still be called (no commands)."""
        from igris.core.self_repair_supervisor import SelfRepairSupervisor, RankSupervisorConfig, SupervisorRun
        sup = self._make_supervisor(tmp_path)
        config = RankSupervisorConfig(goal="Fix #540", rank_id="test", dry_run=True)
        run = SupervisorRun(run_id="ws-block", rank_id="test")

        mock_ws = MagicMock(spec=WorkSession)
        with patch("igris.core.work_session.WorkSession.create", return_value=mock_ws), \
             patch.object(sup, "_run_preflight_phase",
                          return_value=(run, None)):
            sup.run(config, run=run)
            mock_ws.remember.assert_called()
