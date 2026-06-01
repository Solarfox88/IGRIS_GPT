"""Small helpers for supervisor repair-cycle bookkeeping.

Behavior-preserving extraction from ``self_repair_supervisor`` (#1107).
These helpers are intentionally narrow and deterministic.
"""

from __future__ import annotations

from typing import Any, Dict, List


def _event_data(event: Any) -> Dict[str, Any]:
    if hasattr(event, "data"):
        return getattr(event, "data") or {}
    if isinstance(event, dict):
        return event
    return {}


def collect_repair_diagnostics(run: Any) -> Dict[str, Any]:
    """Collect prior-attempt diagnostics for repair-context injection."""
    diag: Dict[str, Any] = {
        "repair_cycles_used": int(getattr(run, "repair_cycles_used", 0) or 0),
        "same_failure_count": int(getattr(run, "same_failure_count", 0) or 0),
    }

    events = getattr(run, "events", []) or []
    if not events:
        return diag

    for ev in reversed(events):
        phase = getattr(ev, "phase", "")
        if phase in ("rank_reasoning", "repair_reasoning"):
            detail = getattr(ev, "detail", "") or ""
            stop = _event_data(ev).get("stop_reason", "")
            if stop or detail:
                diag["previous_stop_reason"] = str(stop)[:200] if stop else ""
                diag["previous_reasoning_summary"] = str(detail)[:300]
                break

    for ev in reversed(events):
        phase = getattr(ev, "phase", "")
        status = getattr(ev, "status", "")
        if phase in ("full_pytest", "targeted_tests", "baseline_tests") and status == "failure":
            diag["previous_pytest_failure"] = str(getattr(ev, "detail", "") or "")[:500]
            break

    modified_files: List[str] = []
    for ev in reversed(events):
        fm = _event_data(ev).get("files_modified")
        if fm:
            modified_files = list(fm)[:10]
            break
    if modified_files:
        diag["previous_files_modified"] = modified_files

    for ev in reversed(events):
        if getattr(ev, "phase", "") == "repair_strategy_decision":
            ev_data = _event_data(ev)
            diag["previous_repair_strategy"] = {
                "task_type": ev_data.get("task_type", ""),
                "profile": ev_data.get("profile", ""),
                "notes": str(ev_data.get("notes", ""))[:200],
            }
            break

    for ev in reversed(events):
        if getattr(ev, "phase", "") == "mbop_phase9_quality_gate":
            ev_data = _event_data(ev)
            diag["previous_quality_gate_status"] = str(getattr(ev, "status", ""))[:50]
            diag["previous_quality_gate_reason"] = str(getattr(ev, "detail", ""))[:200]
            diag["previous_quality_gate_failed_checks"] = ev_data.get("stub_patterns", [])[:5]
            break

    for ev in reversed(events):
        if getattr(ev, "phase", "") == "mbop_phase10_satisfaction_gate":
            ev_data = _event_data(ev)
            missing = ev_data.get("criteria_missing", [])
            covered = ev_data.get("criteria_covered", [])
            checked = ev_data.get("criteria_checked", [])
            diag["previous_satisfaction_score"] = f"{len(covered)}/{len(checked)}" if checked else "unknown"
            diag["previous_satisfaction_missing_acs"] = [str(ac)[:100] for ac in missing[:5]]
            diag["previous_satisfaction_covered_acs"] = [str(ac)[:100] for ac in covered[:5]]
            break

    for ev in reversed(events):
        if getattr(ev, "phase", "") == "mbop_phase11_post_task_eval":
            ev_data = _event_data(ev)
            lessons = ev_data.get("lessons", [])
            diag["mbop_lessons"] = [str(item)[:150] for item in lessons[:5]]
            diag["mbop_recommended_strategy"] = str(ev_data.get("failure_class", ""))[:100]
            break

    for ev in reversed(events):
        if getattr(ev, "phase", "") == "mbop_phase12_next_step":
            ev_data = _event_data(ev)
            suggestions = ev_data.get("suggestions", [])
            diag["mbop_next_step"] = [str(item)[:150] for item in suggestions[:3]]
            break

    return diag


def update_same_failure_tracking(run: Any, failure: str) -> int:
    """Update same-failure counters without changing runtime semantics."""
    if failure and failure == getattr(run, "last_repair_failure", ""):
        run.same_failure_count = int(getattr(run, "same_failure_count", 0) or 0) + 1
    else:
        run.same_failure_count = 0
    run.last_repair_failure = failure
    return int(run.same_failure_count or 0)
