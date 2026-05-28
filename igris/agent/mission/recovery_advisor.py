"""Recovery Advisor — EPIC #886 (#888-#890).

Generates advisory-only recovery recommendations from combined_status.
Feature-flagged via BridgeConfig; disabled by default.

Design constraints:
  - auto_executable is ALWAYS False — never triggers automatic actions.
  - advisory_only is ALWAYS True.
  - Non-blocking: all enrichment functions catch exceptions silently.
  - Additive only: never modifies existing report/cycle fields.
  - No loop modification: loop decisions are NEVER changed.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from igris.agent.mission.bridge_config import DEFAULT_BRIDGE_CONFIG, BridgeConfig
from igris.agent.mission.bridge_reporter import enrich_report
from igris.agent.mission.recovery_taxonomy import (
    CONFIDENCE_LEVELS,
    RECOVERY_ACTIONS,
    RECOVERY_TEMPLATES,
    get_template,
)
from igris.agent.mission.status_bridge import bridge


# ---------------------------------------------------------------------------
# Internal fallback template for unknown combined_statuses
# ---------------------------------------------------------------------------

_FALLBACK_TEMPLATE: Dict[str, Any] = {
    "action": "await_clarification",
    "confidence": "low",
    "evidence_required": [],
    "safe_next_action": "Do not act. Await clarification of run and goal status.",
    "rationale": "Unknown combined status — no specific recovery template available.",
    "auto_executable": False,
    "advisory_only": True,
}


# ---------------------------------------------------------------------------
# Core builder
# ---------------------------------------------------------------------------

def build_recovery_recommendation(
    combined_status: str,
    *,
    cycle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a recovery recommendation dict for a given combined_status.

    Args:
        combined_status: The combined status string from the bridge.
        cycle: Optional cycle dict used for evidence scoring.

    Returns:
        Dict with keys: action, confidence, safe_next_action, rationale,
        evidence_present, evidence_missing, missing_evidence_hint,
        auto_executable (always False), advisory_only (always True),
        based_on_combined_status.
    """
    tmpl = get_template(combined_status)
    if tmpl is None:
        tmpl = _FALLBACK_TEMPLATE  # type: ignore[assignment]

    evidence_required: List[str] = list(tmpl.get("evidence_required") or [])

    if cycle:
        evidence_present = [f for f in evidence_required if f in cycle and cycle[f] is not None]
        evidence_missing = [f for f in evidence_required if f not in cycle or cycle[f] is None]
    else:
        evidence_present = []
        evidence_missing = list(evidence_required)

    missing_hint = (
        f"Provide: {', '.join(evidence_missing)}" if evidence_missing else ""
    )

    return {
        "action": tmpl["action"],
        "confidence": tmpl["confidence"],
        "safe_next_action": tmpl["safe_next_action"],
        "rationale": tmpl["rationale"],
        "evidence_present": evidence_present,
        "evidence_missing": evidence_missing,
        "missing_evidence_hint": missing_hint,
        "auto_executable": False,   # INVARIANT — never change
        "advisory_only": True,      # INVARIANT — never change
        "based_on_combined_status": combined_status,
    }


# ---------------------------------------------------------------------------
# Report enrichment
# ---------------------------------------------------------------------------

def enrich_with_recovery(
    report: Dict[str, Any],
    *,
    run_status: Optional[str] = None,
    goal_status: Optional[str] = None,
    cycle: Optional[Dict[str, Any]] = None,
    config: BridgeConfig = DEFAULT_BRIDGE_CONFIG,
) -> Dict[str, Any]:
    """Add bridge_diagnostics and recovery_recommendation to a report dict.

    If config.should_emit is False, returns the original report unchanged.
    Non-blocking: any exception returns the original report.

    Args:
        report: The base report dict to enrich.
        run_status: The run's technical status (passed/failed/blocked/unknown).
        goal_status: The goal's assessed status (completed/partial/failed/unknown).
        cycle: Optional raw cycle dict for evidence scoring.
        config: BridgeConfig controlling feature flag state.

    Returns:
        Original report (if not emitting) or enriched report with
        bridge_diagnostics and recovery_recommendation added.
    """
    if not config.should_emit:
        return report

    try:
        # First enrich with bridge diagnostics
        enriched = enrich_report(
            report,
            run_status=run_status,
            goal_status=goal_status,
            config=config,
        )

        # Extract combined_status from bridge diagnostics
        combined_status: str = enriched.get("bridge_diagnostics", {}).get(
            "combined_status", ""
        )

        if not combined_status:
            # Fallback: compute directly from bridge()
            try:
                bridge_result = bridge(run_status or "unknown", goal_status or "unknown")
                combined_status = bridge_result.get("combined_status", "unknown_status")
            except Exception:
                combined_status = "unknown_status"

        rec = build_recovery_recommendation(combined_status, cycle=cycle)
        return {**enriched, "recovery_recommendation": rec}

    except Exception:
        return report


def enrich_cycle_with_recovery(
    cycle: Dict[str, Any],
    *,
    config: BridgeConfig = DEFAULT_BRIDGE_CONFIG,
) -> Dict[str, Any]:
    """Enrich a shadow-monitoring cycle dict with a recovery recommendation.

    Reads run_status from cycle["current_loop_decision"] and
    goal_status from cycle["mission_brain_decision"].

    Non-blocking; returns cycle unchanged on any exception.
    """
    if not config.should_emit:
        return cycle

    try:
        run_status = str(cycle.get("current_loop_decision") or "unknown")
        goal_status = str(cycle.get("mission_brain_decision") or "unknown")

        return enrich_with_recovery(
            cycle,
            run_status=run_status,
            goal_status=goal_status,
            cycle=cycle,
            config=config,
        )
    except Exception:
        return cycle


# ---------------------------------------------------------------------------
# Presence helpers
# ---------------------------------------------------------------------------

def has_recovery_recommendation(report: Dict[str, Any]) -> bool:
    """Return True if the report contains a recovery_recommendation section."""
    return "recovery_recommendation" in report


def strip_recovery_recommendation(report: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of report with recovery_recommendation removed."""
    return {k: v for k, v in report.items() if k != "recovery_recommendation"}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_recovery_recommendation(rec: Dict[str, Any]) -> bool:
    """Validate a recovery_recommendation dict.

    Raises ValueError on any invariant violation.
    Returns True on success.
    """
    if rec.get("auto_executable") is not False:
        raise ValueError(
            f"auto_executable must be False, got {rec.get('auto_executable')!r}"
        )
    if rec.get("advisory_only") is not True:
        raise ValueError(
            f"advisory_only must be True, got {rec.get('advisory_only')!r}"
        )
    action = rec.get("action", "")
    if action not in RECOVERY_ACTIONS:
        raise ValueError(
            f"action {action!r} is not a valid recovery action. "
            f"Allowed: {sorted(RECOVERY_ACTIONS)}"
        )
    confidence = rec.get("confidence", "")
    if confidence not in CONFIDENCE_LEVELS:
        raise ValueError(
            f"confidence {confidence!r} is not valid. Allowed: {sorted(CONFIDENCE_LEVELS)}"
        )
    if not str(rec.get("safe_next_action", "")).strip():
        raise ValueError("safe_next_action must be non-empty")
    return True


# ---------------------------------------------------------------------------
# Aggregate statistics
# ---------------------------------------------------------------------------

def aggregate_recovery_cycles(
    cycles: Iterable[Dict[str, Any]],
    *,
    config: BridgeConfig,
) -> Dict[str, Any]:
    """Enrich all cycles and aggregate recovery recommendation statistics.

    Returns:
        total_cycles, cycles_with_recommendation, auto_executable_violations,
        evidence_complete_count, action_distribution, confidence_distribution.
    """
    enriched = [enrich_cycle_with_recovery(c, config=config) for c in cycles]

    total = len(enriched)
    with_rec = sum(1 for r in enriched if has_recovery_recommendation(r))

    auto_exec_violations = sum(
        1 for r in enriched
        if has_recovery_recommendation(r)
        and r["recovery_recommendation"].get("auto_executable") is not False
    )

    evidence_complete = sum(
        1 for r in enriched
        if has_recovery_recommendation(r)
        and not r["recovery_recommendation"].get("evidence_missing")
    )

    action_dist: Dict[str, int] = {}
    confidence_dist: Dict[str, int] = {}
    for r in enriched:
        if has_recovery_recommendation(r):
            rec = r["recovery_recommendation"]
            a = rec.get("action", "unknown")
            c = rec.get("confidence", "unknown")
            action_dist[a] = action_dist.get(a, 0) + 1
            confidence_dist[c] = confidence_dist.get(c, 0) + 1

    return {
        "total_cycles": total,
        "cycles_with_recommendation": with_rec,
        "auto_executable_violations": auto_exec_violations,
        "evidence_complete_count": evidence_complete,
        "action_distribution": action_dist,
        "confidence_distribution": confidence_dist,
    }
