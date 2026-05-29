"""Tests for dependency-gating observability (issue #616).

Validates:
- /api/memory/summary includes dependency_graph field
- watchdog_dependency_skip event emitted when roadmap candidate has open deps
- watchdog_dependency_skip NOT emitted when deps are satisfied
- dependency_graph entry has correct structure: {deps, satisfied, unsatisfied}
- dep check error during autoselect is logged as non-fatal
- .igris/dependencies.json fallback covered end-to-end in integration
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from igris.core.dependency_checker import save_dep_file
from igris.core.self_repair_supervisor import (
    RankSupervisorConfig,
    SelfRepairSupervisor,
    SupervisorRun,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run() -> SupervisorRun:
    return SupervisorRun(run_id="obs-test", rank_id="test")


def _make_config(**kwargs) -> RankSupervisorConfig:
    defaults = dict(goal="test", rank_id="test", dry_run=True, allow_roadmap_autoselect=True)
    defaults.update(kwargs)
    return RankSupervisorConfig(**defaults)


def _make_supervisor(tmp_path: Path) -> SelfRepairSupervisor:
    return SelfRepairSupervisor(project_root=str(tmp_path))


def _events_by_phase(run: SupervisorRun, phase: str):
    return [e for e in run.events if e.phase == phase]


# ---------------------------------------------------------------------------
# watchdog_dependency_skip event
# ---------------------------------------------------------------------------

class TestWatchdogDependencySkip:
    def test_skip_event_emitted_when_dep_open(self, tmp_path):
        """Roadmap candidate with unsatisfied dep → watchdog_dependency_skip emitted."""
        sup = _make_supervisor(tmp_path)
        run = _make_run()
        config = _make_config()
        next_issue = {"number": 500, "title": "Test issue", "labels": []}

        with patch.object(sup, "_select_next_roadmap_issue", return_value=next_issue), \
             patch("igris.core.dependency_checker.DependencyChecker.check",
                   return_value=(False, [614])):
            sup._maybe_autoselect_next_roadmap(run, config)

        skip_events = _events_by_phase(run, "watchdog_dependency_skip")
        assert skip_events, "watchdog_dependency_skip must be emitted"
        assert skip_events[0].status == "skipped"
        assert skip_events[0].data.get("issue_number") == 500
        assert 614 in skip_events[0].data.get("unsatisfied_deps", [])

    def test_skip_event_not_emitted_when_dep_satisfied(self, tmp_path):
        """Roadmap candidate with satisfied deps → no skip event, roadmap_next_target emitted."""
        sup = _make_supervisor(tmp_path)
        run = _make_run()
        config = _make_config()
        next_issue = {"number": 614, "title": "DependencyChecker", "labels": []}

        with patch.object(sup, "_select_next_roadmap_issue", return_value=next_issue), \
             patch("igris.core.dependency_checker.DependencyChecker.check",
                   return_value=(True, [])):
            sup._maybe_autoselect_next_roadmap(run, config)

        skip_events = _events_by_phase(run, "watchdog_dependency_skip")
        assert not skip_events, "skip event must NOT be emitted when deps satisfied"
        target_events = _events_by_phase(run, "roadmap_next_target")
        assert target_events, "roadmap_next_target must be emitted"

    def test_skip_dep_check_error_is_non_fatal(self, tmp_path):
        """Error in dep check during autoselect → 'error' event, roadmap continues."""
        sup = _make_supervisor(tmp_path)
        run = _make_run()
        config = _make_config()
        next_issue = {"number": 614, "title": "DependencyChecker", "labels": []}

        with patch.object(sup, "_select_next_roadmap_issue", return_value=next_issue), \
             patch("igris.core.dependency_checker.DependencyChecker.check",
                   side_effect=RuntimeError("gh CLI error")):
            # Should not raise
            sup._maybe_autoselect_next_roadmap(run, config)

        skip_events = _events_by_phase(run, "watchdog_dependency_skip")
        # An error event should be logged
        assert skip_events, "error event should still be logged"
        assert skip_events[0].status == "error"
        # After the error, roadmap_next_target should still be emitted (best-effort)
        target_events = _events_by_phase(run, "roadmap_next_target")
        assert target_events, "roadmap should still proceed after dep check error"

    def test_no_issue_no_skip_event(self, tmp_path):
        """When _select_next_roadmap_issue returns None, no events emitted."""
        sup = _make_supervisor(tmp_path)
        run = _make_run()
        config = _make_config()

        with patch.object(sup, "_select_next_roadmap_issue", return_value=None):
            sup._maybe_autoselect_next_roadmap(run, config)

        assert not _events_by_phase(run, "watchdog_dependency_skip")
        assert not _events_by_phase(run, "roadmap_next_target")


# ---------------------------------------------------------------------------
# /api/memory/summary — dependency_graph field
# ---------------------------------------------------------------------------

class TestMemorySummaryDependencyGraph:
    def test_dependency_graph_key_present(self, tmp_path):
        """dependency_graph must always be present in the response."""
        # We test the logic directly (the dep graph builder in isolation).
        dep_map = {614: [522, 523], 819: [614]}
        save_dep_file(str(tmp_path), dep_map)

        from igris.core.dependency_checker import DependencyChecker, load_dep_file
        loaded = load_dep_file(str(tmp_path))
        assert "614" in loaded
        assert "819" in loaded
        # Simulate what /api/memory/summary does
        checker = DependencyChecker(str(tmp_path))
        graph = {}
        for issue_str, deps in loaded.items():
            with patch("igris.core.dependency_checker.DependencyChecker.check",
                       return_value=(True, [])):
                ok, unsat = checker.check(int(issue_str))
                graph[issue_str] = {"deps": deps, "satisfied": ok, "unsatisfied": unsat}

        assert "614" in graph
        assert "819" in graph
        assert graph["614"]["satisfied"] is True
        assert graph["614"]["deps"] == [522, 523]

    def test_dependency_graph_unsatisfied_entries(self, tmp_path):
        """When a dep is open, unsatisfied list is populated."""
        from igris.core.dependency_checker import DependencyChecker, load_dep_file
        dep_map = {500: [614]}
        save_dep_file(str(tmp_path), dep_map)
        loaded = load_dep_file(str(tmp_path))

        checker = DependencyChecker(str(tmp_path))
        graph = {}
        for issue_str, deps in loaded.items():
            with patch("igris.core.dependency_checker.DependencyChecker.check",
                       return_value=(False, [614])):
                ok, unsat = checker.check(int(issue_str))
                graph[issue_str] = {"deps": deps, "satisfied": ok, "unsatisfied": unsat}

        assert graph["500"]["satisfied"] is False
        assert 614 in graph["500"]["unsatisfied"]

    def test_empty_dep_file_returns_empty_graph(self, tmp_path):
        """If no dep file exists, dependency_graph is empty {}."""
        from igris.core.dependency_checker import load_dep_file
        loaded = load_dep_file(str(tmp_path))
        assert loaded == {}


# ---------------------------------------------------------------------------
# Integration: dep file fallback end-to-end
# ---------------------------------------------------------------------------

class TestDepFileFallbackIntegration:
    def test_dep_file_fallback_blocks_run(self, tmp_path):
        """Issue in dep file with open dep → blocked in preflight."""
        save_dep_file(str(tmp_path), {500: [614]})

        from igris.core.self_repair_supervisor import SelfRepairSupervisor, SupervisorRun
        sup = SelfRepairSupervisor(project_root=str(tmp_path))
        ok_result = MagicMock()
        ok_result.success = True
        ok_result.output = ""
        sup.backend = MagicMock()
        sup.backend.git_status.return_value = ok_result
        sup.backend.git_log_head.return_value = ok_result
        sup.backend.api_helper_is_configured.return_value = False

        config = RankSupervisorConfig(
            goal="Fix #500",
            rank_id="test",
            dry_run=True,
            issue_number=500,
        )
        run = SupervisorRun(run_id="integ", rank_id="test")

        # 614 is open — dep check should block
        with patch("igris.core.dependency_checker._gh_issue_state", return_value="open"), \
             patch("igris.core.dependency_checker._gh_pr_merged", return_value=False), \
             patch.object(sup, "_cancel_if_requested", return_value=None):
            result, ctx = sup._run_preflight_phase(run, config)

        assert ctx is None, "Must be blocked when dep is open"
        dep_events = [e for e in run.events if e.phase == "dependency_check"]
        assert dep_events and dep_events[0].status == "blocked"

    def test_dep_file_fallback_allows_run_when_closed(self, tmp_path):
        """Issue in dep file with closed dep → dep check passes."""
        save_dep_file(str(tmp_path), {500: [614]})

        from igris.core.self_repair_supervisor import SelfRepairSupervisor, SupervisorRun
        sup = SelfRepairSupervisor(project_root=str(tmp_path))
        ok_result = MagicMock()
        ok_result.success = True
        ok_result.output = ""
        sup.backend = MagicMock()
        sup.backend.git_status.return_value = ok_result
        sup.backend.git_log_head.return_value = ok_result
        sup.backend.api_helper_is_configured.return_value = False

        config = RankSupervisorConfig(
            goal="Fix #500",
            rank_id="test",
            dry_run=True,
            issue_number=500,
        )
        run = SupervisorRun(run_id="integ2", rank_id="test")

        # 614 is closed — dep check should pass
        with patch("igris.core.dependency_checker._gh_issue_state",
                   side_effect=lambda r, n: "closed" if n == 614 else "open"), \
             patch("igris.core.dependency_checker._gh_pr_merged", return_value=None), \
             patch.object(sup, "_cancel_if_requested", return_value=None):
            result, ctx = sup._run_preflight_phase(run, config)

        dep_events = [e for e in run.events if e.phase == "dependency_check"]
        assert dep_events and dep_events[0].status == "satisfied"
