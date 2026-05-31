"""Tests for #1103 — MBOP post-run feedback injected into repair cycles.

Validates that ``_collect_repair_diagnostics`` extracts diagnostics from
the current run's events, and that ``ContextManager._build_state_context``
renders them as operative directives.
"""

from __future__ import annotations

import types
from typing import Any, Dict, List

import pytest


# ---------------------------------------------------------------------------
# Minimal stub for SupervisorRun events
# ---------------------------------------------------------------------------

class _StubEvent:
    """Minimal event object compatible with supervisor event access patterns."""

    def __init__(self, phase: str, status: str, detail: str = "", **data: Any):
        self.phase = phase
        self.status = status
        self.detail = detail
        self._data = data

    @property
    def data(self) -> Dict[str, Any]:
        return self._data


class _StubRun:
    """Minimal run object compatible with ``_collect_repair_diagnostics``."""

    def __init__(
        self,
        events: List[_StubEvent] | None = None,
        repair_cycles_used: int = 0,
        same_failure_count: int = 0,
    ):
        self.events = events or []
        self.repair_cycles_used = repair_cycles_used
        self.same_failure_count = same_failure_count


# ---------------------------------------------------------------------------
# Import the real method under test
# ---------------------------------------------------------------------------

from igris.core.self_repair_supervisor import SelfRepairSupervisor


class TestCollectRepairDiagnostics:
    """Unit tests for ``SelfRepairSupervisor._collect_repair_diagnostics``."""

    def test_empty_events_returns_cycle_counts(self):
        run = _StubRun()
        diag = SelfRepairSupervisor._collect_repair_diagnostics(run, "pytest_failure", 1)
        assert diag["repair_cycles_used"] == 0
        assert diag["same_failure_count"] == 0
        assert "previous_stop_reason" not in diag

    def test_extracts_previous_stop_reason(self):
        run = _StubRun(events=[
            _StubEvent("rank_reasoning", "completed", "Task done", stop_reason="max_steps"),
        ])
        diag = SelfRepairSupervisor._collect_repair_diagnostics(run, "max_steps", 1)
        assert diag["previous_stop_reason"] == "max_steps"
        assert "Task done" in diag["previous_reasoning_summary"]

    def test_extracts_repair_reasoning_stop(self):
        run = _StubRun(events=[
            _StubEvent("rank_reasoning", "completed", "First attempt"),
            _StubEvent("repair_reasoning", "timeout", "Timed out", stop_reason="reasoning_timeout"),
        ])
        diag = SelfRepairSupervisor._collect_repair_diagnostics(run, "reasoning_timeout", 2)
        assert diag["previous_stop_reason"] == "reasoning_timeout"
        assert "Timed out" in diag["previous_reasoning_summary"]

    def test_extracts_pytest_failure(self):
        run = _StubRun(events=[
            _StubEvent("full_pytest", "failure", "FAILED tests/test_x.py::test_foo - AssertionError"),
        ])
        diag = SelfRepairSupervisor._collect_repair_diagnostics(run, "pytest_failure", 1)
        assert "FAILED" in diag["previous_pytest_failure"]
        assert "test_foo" in diag["previous_pytest_failure"]

    def test_extracts_targeted_tests_failure(self):
        run = _StubRun(events=[
            _StubEvent("targeted_tests", "failure", "2 failed, 1 passed"),
        ])
        diag = SelfRepairSupervisor._collect_repair_diagnostics(run, "pytest_failure", 1)
        assert "2 failed" in diag["previous_pytest_failure"]

    def test_extracts_files_modified(self):
        run = _StubRun(events=[
            _StubEvent("rank_reasoning", "completed", "done", files_modified=["igris/web/server.py", "tests/test_ping.py"]),
        ])
        diag = SelfRepairSupervisor._collect_repair_diagnostics(run, "pytest_failure", 1)
        assert "igris/web/server.py" in diag["previous_files_modified"]
        assert "tests/test_ping.py" in diag["previous_files_modified"]

    def test_extracts_repair_strategy_decision(self):
        run = _StubRun(events=[
            _StubEvent("repair_strategy_decision", "proceed", "strategy info",
                       task_type="semantic_repair", profile="strong_execution", notes="escalated"),
        ])
        diag = SelfRepairSupervisor._collect_repair_diagnostics(run, "semantic_incomplete", 2)
        assert diag["previous_repair_strategy"]["task_type"] == "semantic_repair"
        assert diag["previous_repair_strategy"]["profile"] == "strong_execution"

    def test_cycle_counts_from_run(self):
        run = _StubRun(repair_cycles_used=3, same_failure_count=2)
        diag = SelfRepairSupervisor._collect_repair_diagnostics(run, "pytest_failure", 3)
        assert diag["repair_cycles_used"] == 3
        assert diag["same_failure_count"] == 2

    def test_truncates_long_detail(self):
        long_detail = "x" * 1000
        run = _StubRun(events=[
            _StubEvent("rank_reasoning", "completed", long_detail, stop_reason="a" * 500),
        ])
        diag = SelfRepairSupervisor._collect_repair_diagnostics(run, "max_steps", 1)
        assert len(diag["previous_stop_reason"]) <= 200
        assert len(diag["previous_reasoning_summary"]) <= 300

    def test_no_pytest_failure_when_none(self):
        run = _StubRun(events=[
            _StubEvent("rank_reasoning", "completed", "done", stop_reason="finish"),
        ])
        diag = SelfRepairSupervisor._collect_repair_diagnostics(run, "missing_tests", 1)
        assert "previous_pytest_failure" not in diag

    def test_multiple_events_picks_latest(self):
        run = _StubRun(events=[
            _StubEvent("rank_reasoning", "completed", "First attempt", stop_reason="max_steps"),
            _StubEvent("repair_reasoning", "completed", "Second attempt", stop_reason="finish"),
        ])
        diag = SelfRepairSupervisor._collect_repair_diagnostics(run, "pytest_failure", 2)
        # Should pick the last (repair_reasoning), not the first (rank_reasoning)
        assert diag["previous_stop_reason"] == "finish"
        assert "Second attempt" in diag["previous_reasoning_summary"]


class TestContextManagerRepairDirectives:
    """Tests that ContextManager renders repair diagnostics as directives."""

    def test_repair_diagnostics_in_state_context(self):
        from igris.core.context_manager import ContextManager
        cm = ContextManager.__new__(ContextManager)
        cm.project_root = "/tmp/test"
        cm.token_budgets = {"local_coder": 4096}
        cm.default_budget = 4096

        world_state = {
            "previous_stop_reason": "max_steps",
            "previous_reasoning_summary": "Agent hit step limit",
            "previous_pytest_failure": "FAILED test_x.py::test_foo",
            "previous_files_modified": ["server.py"],
        }
        result = cm._build_state_context(world_state)
        assert "PREVIOUS ATTEMPT DIAGNOSTICS" in result
        assert "max_steps" in result
        assert "Agent hit step limit" in result
        assert "FAILED test_x.py::test_foo" in result
        assert "server.py" in result
        assert "Do NOT repeat" in result

    def test_no_repair_section_without_diagnostics(self):
        from igris.core.context_manager import ContextManager
        cm = ContextManager.__new__(ContextManager)
        cm.project_root = "/tmp/test"
        cm.token_budgets = {"local_coder": 4096}
        cm.default_budget = 4096

        world_state = {"some_key": "some_value"}
        result = cm._build_state_context(world_state)
        assert "PREVIOUS ATTEMPT DIAGNOSTICS" not in result

    def test_repair_keys_excluded_from_condensed(self):
        from igris.core.context_manager import ContextManager
        cm = ContextManager.__new__(ContextManager)
        cm.project_root = "/tmp/test"
        cm.token_budgets = {"local_coder": 4096}
        cm.default_budget = 4096

        world_state = {
            "previous_stop_reason": "max_steps",
            "previous_reasoning_summary": "summary",
            "previous_pytest_failure": "failure",
            "previous_files_modified": ["a.py"],
            "previous_repair_strategy": {"task_type": "semantic_repair"},
        }
        result = cm._build_state_context(world_state)
        # These keys should NOT appear in the condensed STATE section
        lines = result.split("\n")
        state_lines = [l for l in lines if l.startswith("previous_")]
        assert len(state_lines) == 0, f"Repair keys leaked into condensed state: {state_lines}"
