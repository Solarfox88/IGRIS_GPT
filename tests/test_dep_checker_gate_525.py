"""
Tests for DependencyChecker hard pre-run gate — issue #525.

Verifies:
- Mission start calls check_runtime_deps()
- Blocking missing deps abort mission (dependency_skip audit event)
- Audit event dependency_skip is recorded when gate fires
- Non-blocking missing deps produce warning but don't abort
- Regression: supervisor tests still pass (supervisor instantiation)
"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from igris.core.dependency_checker import check_runtime_deps, RuntimeDepResult


def _make_supervisor(project_root: str):
    from igris.core.self_repair_supervisor import SelfRepairSupervisor
    backend = MagicMock()
    backend.run_command.return_value = MagicMock(success=True, stdout="", stderr="", returncode=0)
    backend.restore_dangerous_diff.return_value = MagicMock(success=True)
    backend.git_status.return_value = MagicMock(success=True, output="", stdout="", stderr="")
    backend.git_log_head.return_value = MagicMock(success=True, output="abc123 HEAD", stdout="")
    backend.api_helper_is_configured.return_value = False
    return SelfRepairSupervisor(project_root=project_root, backend=backend)


# ---- Unit tests for check_runtime_deps ----

class TestCheckRuntimeDeps:
    def test_returns_runtime_dep_result(self):
        result = check_runtime_deps()
        assert isinstance(result, RuntimeDepResult)

    def test_passed_when_all_critical_present(self):
        result = check_runtime_deps(critical=["os", "sys"], non_blocking=[])
        assert result.passed is True
        assert result.blocking_missing == []

    def test_blocking_missing_on_missing_critical(self):
        result = check_runtime_deps(critical=["__nonexistent_pkg_xyz__"], non_blocking=[])
        assert result.passed is False
        assert "__nonexistent_pkg_xyz__" in result.blocking_missing

    def test_warning_missing_on_missing_non_blocking(self):
        result = check_runtime_deps(critical=[], non_blocking=["__nonexistent_pkg_xyz__"])
        assert result.passed is True  # non-blocking doesn't fail
        assert "__nonexistent_pkg_xyz__" in result.warning_missing

    def test_blocking_missing_empty_when_all_present(self):
        result = check_runtime_deps(critical=["os", "sys", "json"], non_blocking=[])
        assert result.blocking_missing == []
        assert result.passed is True

    def test_repr_contains_passed(self):
        result = check_runtime_deps(critical=[], non_blocking=[])
        assert "passed" in repr(result)


# ---- Integration: supervisor run calls check_runtime_deps ----

class TestDepCheckerGateWiring:
    def test_blocking_deps_abort_run(self, tmp_path):
        """When critical deps are missing, supervisor run must return blocked."""
        supervisor = _make_supervisor(str(tmp_path))
        from igris.core.self_repair_supervisor import RankSupervisorConfig

        config = RankSupervisorConfig(rank_id="test-rank", goal="fix something")

        mock_dep_result = RuntimeDepResult(
            blocking_missing=["missing_critical_pkg"],
            warning_missing=[],
        )
        with patch("igris.core.dependency_checker.check_runtime_deps", return_value=mock_dep_result):
            run = supervisor.run(config)

        # Run must be blocked (dependency_skip event present)
        event_phases = [e.phase for e in run.events]
        assert "dependency_skip" in event_phases, (
            f"dependency_skip event not in run events: {event_phases}"
        )

    def test_blocking_deps_record_audit_event(self, tmp_path):
        """dependency_skip event must be recorded in run events."""
        supervisor = _make_supervisor(str(tmp_path))
        from igris.core.self_repair_supervisor import RankSupervisorConfig

        config = RankSupervisorConfig(rank_id="test-rank", goal="fix something")
        mock_dep_result = RuntimeDepResult(
            blocking_missing=["missing_pkg"],
            warning_missing=[],
        )
        with patch("igris.core.dependency_checker.check_runtime_deps", return_value=mock_dep_result):
            run = supervisor.run(config)

        dep_events = [e for e in run.events if e.phase == "dependency_skip"]
        assert len(dep_events) >= 1
        assert dep_events[0].status == "blocked"

    def test_non_blocking_missing_does_not_trigger_dep_skip(self, tmp_path):
        """Non-blocking missing deps must NOT set dependency_skip event."""
        supervisor = _make_supervisor(str(tmp_path))
        from igris.core.self_repair_supervisor import RankSupervisorConfig, SupervisorRun

        config = RankSupervisorConfig(rank_id="test-rank", goal="fix something")
        mock_dep_result = RuntimeDepResult(
            blocking_missing=[],
            warning_missing=["optional_missing_pkg"],
        )

        # Only run preflight phase to avoid mock complexity of full run
        with patch("igris.core.dependency_checker.check_runtime_deps", return_value=mock_dep_result):
            # Mock git_status to make preflight fail at git stage (not dep gate)
            supervisor.backend.git_status.return_value = MagicMock(
                success=False, output="dirty workspace", stdout="", stderr=""
            )
            run, ctx = supervisor._run_preflight_phase(None, config)

        # dependency_skip event must NOT be present
        dep_skip_events = [e for e in run.events if e.phase == "dependency_skip"]
        assert len(dep_skip_events) == 0, (
            "Non-blocking dep should NOT trigger dependency_skip block"
        )

    def test_checker_exception_does_not_block(self, tmp_path):
        """If check_runtime_deps raises, the mission is not blocked by dep gate."""
        supervisor = _make_supervisor(str(tmp_path))
        from igris.core.self_repair_supervisor import RankSupervisorConfig

        config = RankSupervisorConfig(rank_id="test-rank", goal="fix something")
        # Make git_status fail so preflight returns early (avoiding mock complexity)
        supervisor.backend.git_status.return_value = MagicMock(
            success=False, output="dirty workspace", stdout="", stderr=""
        )
        with patch("igris.core.dependency_checker.check_runtime_deps", side_effect=RuntimeError("checker crashed")):
            run, ctx = supervisor._run_preflight_phase(None, config)

        # No dependency_skip event — exception is non-blocking
        dep_skip_events = [e for e in run.events if e.phase == "dependency_skip"]
        assert len(dep_skip_events) == 0

    def test_run_preflight_source_contains_dep_gate(self):
        """Source inspection: _run_preflight_phase must contain check_runtime_deps call."""
        import igris.core.self_repair_supervisor as srv
        import inspect
        src = inspect.getsource(srv.SelfRepairSupervisor._run_preflight_phase)
        assert "check_runtime_deps" in src, (
            "check_runtime_deps not found in _run_preflight_phase — hard gate not wired"
        )

    def test_dependency_skip_event_has_missing_data(self, tmp_path):
        """dependency_skip event must include which packages are missing."""
        supervisor = _make_supervisor(str(tmp_path))
        from igris.core.self_repair_supervisor import RankSupervisorConfig

        config = RankSupervisorConfig(rank_id="test-rank", goal="fix something")
        mock_dep_result = RuntimeDepResult(
            blocking_missing=["critical_pkg_A", "critical_pkg_B"],
            warning_missing=[],
        )
        with patch("igris.core.dependency_checker.check_runtime_deps", return_value=mock_dep_result):
            run = supervisor.run(config)

        dep_events = [e for e in run.events if e.phase == "dependency_skip"]
        assert len(dep_events) >= 1
        # Event detail must mention the missing packages
        event_detail = str(dep_events[0].detail)
        assert "critical_pkg" in event_detail or "missing" in event_detail.lower()
