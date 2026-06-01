"""Tests for #1103 hardening: MBOP Phase 9-12 feedback in repair context.

Covers:
- _collect_repair_diagnostics extracts Phase 9 quality gate
- _collect_repair_diagnostics extracts Phase 10 satisfaction missing ACs
- _collect_repair_diagnostics extracts Phase 11 lessons
- _collect_repair_diagnostics extracts Phase 12 next-step
- ContextManager renders MBOP fields in PREVIOUS ATTEMPT DIAGNOSTICS
- Graceful handling of missing/malformed MBOP data
- Secret redaction / truncation preserved
"""

from unittest.mock import MagicMock

from igris.core.context_manager import ContextManager
from igris.core.self_repair_supervisor import SelfRepairSupervisor


def _make_event(phase: str, status: str = "done", detail: str = "", **data):
    ev = MagicMock()
    ev.phase = phase
    ev.status = status
    ev.detail = detail
    ev.data = data
    return ev


def _make_run(events=None):
    run = MagicMock()
    run.events = events or []
    run.repair_cycles_used = 1
    run.same_failure_count = 0
    return run


# ---------------------------------------------------------------------------
# _collect_repair_diagnostics tests
# ---------------------------------------------------------------------------

def test_collects_phase9_quality_gate():
    ev = _make_event(
        "mbop_phase9_quality_gate", status="fail",
        detail="QG FAIL: stubs found",
        stub_patterns=["TODO", "FIXME"],
    )
    run = _make_run([ev])
    diag = SelfRepairSupervisor._collect_repair_diagnostics(run, "test", 1)
    assert diag["previous_quality_gate_status"] == "fail"
    assert "stubs found" in diag["previous_quality_gate_reason"]
    assert "TODO" in diag["previous_quality_gate_failed_checks"]


def test_collects_phase10_satisfaction():
    ev = _make_event(
        "mbop_phase10_satisfaction_gate", status="advisory",
        detail="1/3 ACs covered",
        criteria_checked=["add tests", "add endpoint", "add docs"],
        criteria_covered=["add endpoint"],
        criteria_missing=["add tests", "add docs"],
    )
    run = _make_run([ev])
    diag = SelfRepairSupervisor._collect_repair_diagnostics(run, "test", 1)
    assert diag["previous_satisfaction_score"] == "1/3"
    assert "add tests" in diag["previous_satisfaction_missing_acs"]
    assert "add docs" in diag["previous_satisfaction_missing_acs"]
    assert "add endpoint" in diag["previous_satisfaction_covered_acs"]


def test_collects_phase11_lessons():
    ev = _make_event(
        "mbop_phase11_post_task_eval", status="done",
        detail="eval summary",
        lessons=["Tests failed at completion", "Stubs detected"],
        failure_class="test_failure",
    )
    run = _make_run([ev])
    diag = SelfRepairSupervisor._collect_repair_diagnostics(run, "test", 1)
    assert "Tests failed at completion" in diag["mbop_lessons"]
    assert diag["mbop_recommended_strategy"] == "test_failure"


def test_collects_phase12_next_step():
    ev = _make_event(
        "mbop_phase12_next_step", status="advisory",
        detail="decompose",
        suggestions=["Split into subtasks", "Fix tests first"],
    )
    run = _make_run([ev])
    diag = SelfRepairSupervisor._collect_repair_diagnostics(run, "test", 1)
    assert "Split into subtasks" in diag["mbop_next_step"]
    assert "Fix tests first" in diag["mbop_next_step"]


def test_all_phases_together():
    events = [
        _make_event("rank_reasoning", status="failure", detail="loop stuck",
                     stop_reason="max_iterations"),
        _make_event("full_pytest", status="failure", detail="2 failed"),
        _make_event("mbop_phase9_quality_gate", status="pass",
                     stub_patterns=[]),
        _make_event("mbop_phase10_satisfaction_gate", status="advisory",
                     criteria_checked=["add X"], criteria_covered=[],
                     criteria_missing=["add X"]),
        _make_event("mbop_phase11_post_task_eval",
                     lessons=["no progress made"]),
        _make_event("mbop_phase12_next_step",
                     suggestions=["try different approach"]),
    ]
    run = _make_run(events)
    diag = SelfRepairSupervisor._collect_repair_diagnostics(run, "test", 2)
    assert diag["previous_stop_reason"] == "max_iterations"
    assert diag["previous_pytest_failure"] == "2 failed"
    assert diag["previous_quality_gate_status"] == "pass"
    assert diag["previous_satisfaction_score"] == "0/1"
    assert "add X" in diag["previous_satisfaction_missing_acs"]
    assert "no progress made" in diag["mbop_lessons"]
    assert "try different approach" in diag["mbop_next_step"]


def test_missing_mbop_data_graceful():
    """No MBOP events → diagnostics still work, no MBOP keys."""
    ev = _make_event("rank_reasoning", status="failure", detail="error",
                     stop_reason="crash")
    run = _make_run([ev])
    diag = SelfRepairSupervisor._collect_repair_diagnostics(run, "test", 1)
    assert diag["previous_stop_reason"] == "crash"
    assert "previous_quality_gate_status" not in diag
    assert "previous_satisfaction_score" not in diag
    assert "mbop_lessons" not in diag
    assert "mbop_next_step" not in diag


def test_empty_events_graceful():
    """No events at all → minimal diagnostics."""
    run = _make_run([])
    diag = SelfRepairSupervisor._collect_repair_diagnostics(run, "test", 1)
    assert diag["repair_cycles_used"] == 1
    assert "previous_stop_reason" not in diag


def test_truncation_on_long_values():
    """Long values are truncated."""
    ev = _make_event(
        "mbop_phase11_post_task_eval",
        lessons=["x" * 500],
        failure_class="y" * 300,
    )
    run = _make_run([ev])
    diag = SelfRepairSupervisor._collect_repair_diagnostics(run, "test", 1)
    assert len(diag["mbop_lessons"][0]) <= 150
    assert len(diag["mbop_recommended_strategy"]) <= 100


# ---------------------------------------------------------------------------
# ContextManager rendering tests
# ---------------------------------------------------------------------------

def test_context_manager_renders_quality_gate():
    cm = ContextManager()
    ws = {
        "previous_stop_reason": "max_iterations",
        "previous_quality_gate_status": "fail",
        "previous_quality_gate_reason": "stubs detected",
        "previous_quality_gate_failed_checks": ["TODO"],
    }
    ctx = cm._build_state_context(ws)
    assert "QUALITY GATE: fail" in ctx
    assert "QUALITY GATE ISSUES: TODO" in ctx


def test_context_manager_renders_satisfaction():
    cm = ContextManager()
    ws = {
        "previous_stop_reason": "max_iterations",
        "previous_satisfaction_score": "1/3",
        "previous_satisfaction_missing_acs": ["add tests", "add docs"],
    }
    ctx = cm._build_state_context(ws)
    assert "SATISFACTION SCORE: 1/3" in ctx
    assert "MISSING AC: add tests" in ctx
    assert "MISSING AC: add docs" in ctx


def test_context_manager_renders_lessons():
    cm = ContextManager()
    ws = {
        "previous_stop_reason": "crash",
        "mbop_lessons": ["Tests failed", "Stubs detected"],
    }
    ctx = cm._build_state_context(ws)
    assert "LESSONS FROM PREVIOUS RUN:" in ctx
    assert "Tests failed" in ctx


def test_context_manager_renders_next_step():
    cm = ContextManager()
    ws = {
        "previous_stop_reason": "error",
        "mbop_next_step": ["Fix tests first", "Split task"],
    }
    ctx = cm._build_state_context(ws)
    assert "SUGGESTED NEXT STEPS:" in ctx
    assert "Fix tests first" in ctx


def test_context_manager_no_mbop_data_still_renders_basic():
    cm = ContextManager()
    ws = {
        "previous_stop_reason": "max_iterations",
        "previous_reasoning_summary": "loop stuck",
    }
    ctx = cm._build_state_context(ws)
    assert "STOP REASON: max_iterations" in ctx
    assert "SUMMARY: loop stuck" in ctx
    assert "QUALITY GATE" not in ctx


def test_context_manager_skips_mbop_keys_from_compact():
    """MBOP feedback keys should NOT appear in compact state section."""
    cm = ContextManager()
    ws = {
        "previous_stop_reason": "x",
        "previous_quality_gate_status": "pass",
        "previous_satisfaction_score": "2/2",
        "mbop_lessons": ["lesson"],
        "mbop_next_step": ["step"],
        "mbop_recommended_strategy": "retry",
        "previous_satisfaction_missing_acs": [],
        "previous_satisfaction_covered_acs": ["ac1"],
        "previous_quality_gate_reason": "ok",
        "previous_quality_gate_failed_checks": [],
    }
    ctx = cm._build_state_context(ws)
    # These keys should be in the DIAGNOSTICS section, not dumped raw
    lines = ctx.split("\n")
    compact_section = [l for l in lines if l.startswith("  ") and ":" in l and "QUALITY" not in l and "SATISFACTION" not in l and "LESSONS" not in l and "NEXT STEPS" not in l]
    for line in compact_section:
        assert "mbop_lessons" not in line
        assert "mbop_next_step" not in line
        assert "previous_quality_gate_status" not in line
