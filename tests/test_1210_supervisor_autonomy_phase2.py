"""Tests for Supervisor Autonomy phase 2 (#1210).

Phase 2 additions:
- Deterministic defect routing: high/critical unrepaired defects route to issues
- Richer actor provenance in external intervention audit
- Run reports link intervention evidence back to defect issue URLs
- No real external calls in tests
- Autonomy policy stays intact
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from igris.core.behavior_tracker import (
    BehaviorRecord,
    BehaviorTracker,
    ExternalInterventionRecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tracker(run_id: str = "run-test-001") -> BehaviorTracker:
    return BehaviorTracker(run_id=run_id, issue_number=42)


def _make_audit_kwargs(**overrides) -> Dict[str, Any]:
    base = dict(
        run_status="blocked",
        failure_class="pytest_failure",
        repair_cycles_used=3,
        smoke_ran=False,
        pytest_ran=True,
        workspace_dirty=False,
        escalation_budget_exhausted=True,
        escalation_was_called=True,
        completion_mode="",
        project_root="",
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Deterministic defect routing
# ---------------------------------------------------------------------------

def test_defect_route_payload_is_deterministic():
    """_defect_issue_route always produces the same payload for the same record."""
    tracker = _make_tracker()
    rec = tracker.record("E001", "wrong file was edited", severity="high", blocking=True, stage_id="s1")

    route1 = BehaviorTracker._defect_issue_route(rec)
    route2 = BehaviorTracker._defect_issue_route(rec)
    assert route1 == route2


def test_defect_route_high_severity_requires_issue():
    """High-severity defects mark requires_issue=True in routing payload."""
    rec = BehaviorRecord(code="E002", name="reasoning_loop_no_progress",
                         detail="loop repeated 5x", severity="high")
    route = BehaviorTracker._defect_issue_route(rec)
    assert route["requires_issue"] is True
    assert route["severity"] == "high"
    assert route["kind"] == "supervisor-defect"


def test_defect_route_critical_severity_requires_issue():
    """Critical-severity defects also mark requires_issue=True."""
    rec = BehaviorRecord(code="E013", name="success_without_verification",
                         detail="completed without smoke", severity="critical")
    route = BehaviorTracker._defect_issue_route(rec)
    assert route["requires_issue"] is True
    assert route["severity"] == "critical"


def test_defect_route_low_severity_does_not_require_issue():
    """Low-severity defects do not require an issue."""
    rec = BehaviorRecord(code="E006", name="incomplete_report",
                         detail="report missing steps", severity="low")
    route = BehaviorTracker._defect_issue_route(rec)
    assert route["requires_issue"] is False


def test_defect_route_label_always_supervisor():
    """Routing payload always includes 'supervisor-defect' label."""
    rec = BehaviorRecord(code="E001", name="wrong_file_edit", detail="x", severity="medium")
    route = BehaviorTracker._defect_issue_route(rec)
    assert "supervisor-defect" in route["label"]


def test_defect_route_includes_stage_and_blocking():
    """Routing payload preserves stage_id and blocking from the record."""
    rec = BehaviorRecord(code="E007", name="no_rollback_after_ast_failure",
                         detail="ast failed", severity="high", blocking=True, stage_id="repair-2")
    route = BehaviorTracker._defect_issue_route(rec)
    assert route["stage_id"] == "repair-2"
    assert route["blocking"] is True


# ---------------------------------------------------------------------------
# External intervention — richer actor provenance
# ---------------------------------------------------------------------------

def test_external_intervention_records_rich_provenance():
    """Intervention record carries actor, source, evidence, and related_issue_urls."""
    tracker = _make_tracker()
    rec = tracker.record_external_intervention(
        actor="claude-sonnet-4-6",
        source="api_escalation",
        detail="escalated due to reasoning timeout",
        severity="high",
        escalated=True,
        stage_id="repair-3",
        evidence="timeout after 300s on step 12",
        issue_url="https://github.com/org/repo/issues/99",
        related_issue_urls=["https://github.com/org/repo/issues/42"],
    )

    assert rec.actor == "claude-sonnet-4-6"
    assert rec.source == "api_escalation"
    assert rec.severity == "high"
    assert rec.escalated is True
    assert rec.stage_id == "repair-3"
    assert "timeout" in rec.evidence
    assert rec.issue_url == "https://github.com/org/repo/issues/99"
    assert "https://github.com/org/repo/issues/42" in rec.related_issue_urls
    assert len(tracker.external_interventions) == 1


def test_external_intervention_multiple_actors():
    """Multiple interventions with distinct actors are all recorded."""
    tracker = _make_tracker()
    tracker.record_external_intervention(
        actor="claude-sonnet", source="api_escalation", detail="first call",
        severity="medium", escalated=True,
    )
    tracker.record_external_intervention(
        actor="human-operator", source="manual", detail="second call",
        severity="high", escalated=True,
        issue_url="https://github.com/org/repo/issues/10",
    )

    assert len(tracker.external_interventions) == 2
    actors = [r.actor for r in tracker.external_interventions]
    assert "claude-sonnet" in actors
    assert "human-operator" in actors


def test_external_intervention_no_real_external_calls():
    """recording intervention does not make real external calls (no subprocess)."""
    import subprocess as sp
    original_run = sp.run
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        raise AssertionError("subprocess.run should not be called in tests")

    sp.run = fake_run
    try:
        tracker = _make_tracker()
        tracker.record_external_intervention(
            actor="fake", source="test", detail="none",
            severity="low", escalated=False,
        )
    finally:
        sp.run = original_run

    assert not calls


# ---------------------------------------------------------------------------
# Self-audit — intervention evidence linked to defect issues
# ---------------------------------------------------------------------------

def test_self_audit_records_intervention_when_escalation_was_called():
    """When escalation_was_called=True and no intervention recorded, self_audit adds one."""
    tracker = _make_tracker()
    result = tracker.self_audit(**_make_audit_kwargs(escalation_was_called=True))
    # auto-added intervention should appear
    interventions = tracker.external_interventions
    assert any(r.escalated for r in interventions)


def test_self_audit_does_not_duplicate_intervention():
    """If an intervention was already recorded, self_audit doesn't add a second."""
    tracker = _make_tracker()
    tracker.record_external_intervention(
        actor="claude", source="api_escalation", detail="already recorded",
        severity="high", escalated=True,
        issue_url="https://github.com/org/repo/issues/5",
    )
    tracker.self_audit(**_make_audit_kwargs(escalation_was_called=True))
    escalated = [r for r in tracker.external_interventions if r.escalated]
    # Only 1, not duplicated
    assert len(escalated) == 1


def test_self_audit_links_intervention_to_opened_issue(monkeypatch):
    """When an issue is auto-opened, the intervention record references it."""
    import igris.core.behavior_tracker as bt_mod

    # Patch _open_defect_issues to return a fake URL without calling gh
    monkeypatch.setenv("IGRIS_AUTO_OPEN_DEFECT_ISSUES", "true")
    monkeypatch.setattr(
        bt_mod.BehaviorTracker,
        "_open_defect_issues",
        lambda self, root: ["https://github.com/org/repo/issues/99"],
    )

    tracker = _make_tracker()
    tracker.record("E013", "completed without smoke", severity="high")
    result = tracker.self_audit(**_make_audit_kwargs(
        run_status="completed",
        smoke_ran=False,
        pytest_ran=False,
        escalation_was_called=True,
        escalation_budget_exhausted=False,
        project_root="/fake",
    ))

    assert "https://github.com/org/repo/issues/99" in result.opened_issues
    # The auto-added intervention should reference the opened issue
    interventions = [r for r in tracker.external_interventions if r.escalated]
    assert any("issues/99" in r.issue_url for r in interventions)


# ---------------------------------------------------------------------------
# Run report integration — defect routing summary
# ---------------------------------------------------------------------------

def test_tracker_defect_routing_summary():
    """BehaviorTracker produces a routing summary for all high/critical defects."""
    tracker = _make_tracker()
    tracker.record("E001", "wrong file edited", severity="high", blocking=True)
    tracker.record("E013", "success without verification", severity="critical")
    tracker.record("E006", "report missing", severity="low")

    high_critical = [r for r in tracker.records if r.severity in ("high", "critical")]
    routing = [BehaviorTracker._defect_issue_route(r) for r in high_critical]

    assert len(routing) == 2
    assert all(r["requires_issue"] is True for r in routing)
    assert all(r["kind"] == "supervisor-defect" for r in routing)


def test_tracker_intervention_provenance_summary():
    """All interventions have actor + source for provenance audit."""
    tracker = _make_tracker()
    tracker.record_external_intervention(
        actor="claude-opus", source="hard_escalation",
        detail="very hard problem", severity="high", escalated=True,
        issue_url="https://github.com/org/repo/issues/7",
        related_issue_urls=["https://github.com/org/repo/issues/42"],
    )

    interventions = tracker.external_interventions
    assert len(interventions) == 1
    first = interventions[0]
    # All provenance fields populated
    assert first.actor
    assert first.source
    assert first.issue_url
    assert first.related_issue_urls


def test_autonomy_policy_intact_no_free_shell():
    """BehaviorTracker never provides or calls free-form shell execution."""
    tracker = _make_tracker()
    # The tracker should not have any method that runs arbitrary shell commands
    assert not hasattr(tracker, "run_shell")
    assert not hasattr(tracker, "execute")
    assert not hasattr(tracker, "shell")
