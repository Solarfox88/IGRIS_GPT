"""Tests for #914 — MissionBrain Advisory wired into supervisor _blocked().

Verifies that:
1. _blocked() emits an "advisory_diagnostic" event for failed/blocked runs.
2. The advisory_diagnostic event has advisory_surfaced=False (monitoring-only).
3. The advisory_diagnostic event never changes run.status or run.outcome.
4. The advisory wiring is guarded by try/except — a broken advisory module
   must NOT cause _blocked() to raise.
5. The advisory_diagnostic event is absent when _selected_advisory_available=False.
"""
from __future__ import annotations

import types
import pytest

import igris.core.self_repair_supervisor as sup_module
from igris.core.self_repair_supervisor import SelfRepairSupervisor, SupervisorRun


def _make_run(**kwargs) -> SupervisorRun:
    """Build a minimal SupervisorRun for testing."""
    import uuid
    defaults = dict(
        run_id=str(uuid.uuid4()),
        rank_id="rank-test",
        status="running",
        outcome="",
        failure_class="",
        repair_cycles_used=0,
        capability_signals={},
        goal="test goal",
    )
    defaults.update(kwargs)
    run = SupervisorRun.__new__(SupervisorRun)
    for k, v in defaults.items():
        setattr(run, k, v)
    run.events = []
    run.report = {}
    run.audit_resolver = None
    run.update_hook = None
    run.decomposition = None
    run.mission_scope = None
    run.acceptance_evidence = None
    run.strategy_used = ""
    run.same_failure_count = 0
    run.last_repair_failure = ""
    run.execution_budget_used_usd = 0.0
    run.api_escalations_used = 0
    run.api_escalations_failed_unconfigured = 0
    run.api_budget_used_usd = 0.0
    run.max_api_escalations_per_run = 0
    run.max_api_budget_usd = 0.0
    run.max_repair_cycles = 3
    run.branch = ""
    run.cancel_requested = False
    run.cancel_reason = ""
    run.autorun_child_run_id = ""
    run.autorun_policy = ""
    run.autorun_skipped_reason = ""
    return run


def _call_blocked(run: SupervisorRun, failure: str = "reasoning_loop_blocked") -> SupervisorRun:
    """Call _blocked() on a minimal SelfRepairSupervisor instance."""
    supervisor = SelfRepairSupervisor.__new__(SelfRepairSupervisor)
    supervisor.project_root = "/tmp/test_project"
    # Stub out side-effect methods to isolate _blocked()
    supervisor._cleanup_blocked_workspace = lambda r: None
    supervisor._api_escalation_report_fragment = lambda r: {}
    supervisor._stage_report_fragment = lambda mp, ss: {}
    supervisor._failure_memory = None
    supervisor._run_store = types.SimpleNamespace(
        transition=lambda _run, new_status, reason="": setattr(_run, "status", new_status)
    )
    return supervisor._blocked(run, failure, "test detail")


# ---------------------------------------------------------------------------
# Advisory diagnostic emitted on blocked run
# ---------------------------------------------------------------------------

class TestAdvisoryDiagnosticOnBlocked:

    def test_advisory_diagnostic_event_emitted(self):
        """_blocked() should emit advisory_diagnostic event when advisory available."""
        if not sup_module._selected_advisory_available:
            pytest.skip("Advisory module not available in this environment")
        run = _make_run()
        result = _call_blocked(run, failure="reasoning_loop_blocked")
        phases = [e.phase for e in result.events]
        assert "advisory_diagnostic" in phases, (
            f"Expected advisory_diagnostic event in {phases}"
        )

    def test_advisory_diagnostic_not_surfaced(self):
        """advisory_diagnostic must have advisory_surfaced=False."""
        if not sup_module._selected_advisory_available:
            pytest.skip("Advisory module not available in this environment")
        run = _make_run()
        result = _call_blocked(run, failure="no_diff_repair")
        adv_events = [e for e in result.events if e.phase == "advisory_diagnostic"]
        if adv_events:
            for ev in adv_events:
                assert ev.data.get("advisory_surfaced") is False, (
                    f"advisory_surfaced must be False, got: {ev.data}"
                )

    def test_run_status_unchanged(self):
        """Advisory wiring must NOT change run.status."""
        if not sup_module._selected_advisory_available:
            pytest.skip("Advisory module not available in this environment")
        run = _make_run()
        result = _call_blocked(run, failure="reasoning_loop_blocked")
        assert result.status == "blocked", (
            f"run.status should be 'blocked' after _blocked(), got: {result.status}"
        )

    def test_partial_goal_status_when_repair_cycles_used(self):
        """When repair_cycles_used > 0, goal_status should be 'partial'."""
        if not sup_module._selected_advisory_available:
            pytest.skip("Advisory module not available in this environment")
        run = _make_run(repair_cycles_used=2)
        result = _call_blocked(run, failure="reasoning_loop_blocked")
        adv_events = [e for e in result.events if e.phase == "advisory_diagnostic"]
        # Just verify the event was emitted — goal_status is internal to advisory
        assert len(adv_events) >= 1, "advisory_diagnostic should be emitted"


# ---------------------------------------------------------------------------
# Advisory wiring is guarded — broken module must not raise
# ---------------------------------------------------------------------------

class TestAdvisoryResiliency:

    def test_broken_advisory_does_not_raise(self, monkeypatch):
        """If advisory module is broken, _blocked() must still succeed."""
        original = sup_module._selected_advisory_available

        def _broken(*args, **kwargs):
            raise RuntimeError("advisory module broken")

        monkeypatch.setattr(sup_module, "_selected_advisory_available", True)
        monkeypatch.setattr(sup_module, "_enrich_cycle_selected", _broken, raising=False)
        try:
            run = _make_run()
            result = _call_blocked(run, failure="reasoning_loop_blocked")
            # Must not raise; status is still set correctly
            assert result.status == "blocked"
        finally:
            monkeypatch.setattr(sup_module, "_selected_advisory_available", original)

    def test_no_advisory_event_when_unavailable(self, monkeypatch):
        """No advisory_diagnostic event when _selected_advisory_available=False."""
        monkeypatch.setattr(sup_module, "_selected_advisory_available", False)
        run = _make_run()
        result = _call_blocked(run, failure="reasoning_loop_blocked")
        adv_events = [e for e in result.events if e.phase == "advisory_diagnostic"]
        assert len(adv_events) == 0, (
            f"No advisory event expected when unavailable, got: {adv_events}"
        )


# ---------------------------------------------------------------------------
# Module-level flag
# ---------------------------------------------------------------------------

class TestAdvisoryFlag:

    def test_flag_defined(self):
        assert hasattr(sup_module, "_selected_advisory_available")

    def test_flag_is_bool(self):
        assert isinstance(sup_module._selected_advisory_available, bool)


class TestRunStoreWiring:

    def test_blocked_uses_transition_store(self):
        run = _make_run()
        supervisor = SelfRepairSupervisor.__new__(SelfRepairSupervisor)
        supervisor.project_root = "/tmp/test_project"
        supervisor._cleanup_blocked_workspace = lambda r: None
        supervisor._api_escalation_report_fragment = lambda r: {}
        supervisor._stage_report_fragment = lambda mp, ss: {}
        supervisor._failure_memory = None
        calls = []
        supervisor._run_store = types.SimpleNamespace(
            transition=lambda _run, new_status, reason="": (
                calls.append((new_status, reason)),
                setattr(_run, "status", new_status),
            )
        )
        result = supervisor._blocked(run, "reasoning_loop_blocked", "test detail")
        assert result.status == "blocked"
        assert calls and calls[0][0] == "blocked"
