"""Advisory Recovery Rollout — EPIC #892.

Controls when and where advisory recovery recommendations are surfaced in reports.
Feature-flagged (default=OFF). Advisory-only. Non-blocking. Additive.

Scope:
  - Report types: mission_execution, diagnostic, shadow_cycle
  - Run statuses that receive advisory by default: failed, blocked
  - NOT: passed+completed (no recovery needed)
  - NOT: any auto-execution path
  - Loop decisions are NEVER modified.

Design constraints:
  - enabled=False by default — NEVER auto-enabled.
  - is_gate=False — NEVER a gate.
  - auto_executable=False — NEVER auto-executes.
  - advisory_only=True — ALWAYS advisory.
  - Rollback = set enabled=False → all advisory output disappears immediately.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from igris.agent.mission.bridge_config import DEFAULT_BRIDGE_CONFIG, make_diagnostic_config
from igris.agent.mission.recovery_advisor import (
    enrich_with_recovery,
    has_recovery_recommendation,
    strip_recovery_recommendation,
    validate_recovery_recommendation,
)

# ---------------------------------------------------------------------------
# Report type constants
# ---------------------------------------------------------------------------

REPORT_TYPE_MISSION_EXECUTION = "mission_execution"
REPORT_TYPE_DIAGNOSTIC        = "diagnostic"
REPORT_TYPE_SHADOW_CYCLE      = "shadow_cycle"

ADVISORY_REPORT_TARGETS: frozenset = frozenset({
    REPORT_TYPE_MISSION_EXECUTION,
    REPORT_TYPE_DIAGNOSTIC,
    REPORT_TYPE_SHADOW_CYCLE,
})

# Run statuses that receive advisory by default
ADVISORY_DEFAULT_RUN_STATUSES: frozenset = frozenset({"failed", "blocked"})


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AdvisoryRolloutConfig:
    """Feature flag config for advisory recovery rollout.

    Attributes:
        enabled: Master switch. Default: False. NEVER auto-enabled.
        include_passed_goal_incomplete: If True, also emit for passed+non-completed (anomaly case).
        log_enabled: If True, log advisory output.
    """
    enabled: bool = False
    include_passed_goal_incomplete: bool = False
    log_enabled: bool = False

    @property
    def is_gate(self) -> bool:
        return False  # NEVER a gate

    @property
    def should_emit(self) -> bool:
        return self.enabled

    @property
    def target_run_statuses(self) -> frozenset:
        return ADVISORY_DEFAULT_RUN_STATUSES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "include_passed_goal_incomplete": self.include_passed_goal_incomplete,
            "log_enabled": self.log_enabled,
            "is_gate": self.is_gate,
            "should_emit": self.should_emit,
            "target_run_statuses": sorted(self.target_run_statuses),
            "target_report_types": sorted(ADVISORY_REPORT_TARGETS),
        }


DEFAULT_ADVISORY_CONFIG = AdvisoryRolloutConfig(enabled=False)


def make_advisory_enabled_config(
    include_passed_goal_incomplete: bool = False,
    log_enabled: bool = False,
) -> AdvisoryRolloutConfig:
    """Create an enabled advisory config. Requires explicit opt-in."""
    return AdvisoryRolloutConfig(
        enabled=True,
        include_passed_goal_incomplete=include_passed_goal_incomplete,
        log_enabled=log_enabled,
    )


def advisory_config_from_env() -> AdvisoryRolloutConfig:
    """Load advisory config from environment variables. Default: disabled."""
    raw = os.environ.get("ADVISORY_ROLLOUT_ENABLED", "").strip().lower()
    if raw not in ("true", "1", "yes"):
        return DEFAULT_ADVISORY_CONFIG
    return make_advisory_enabled_config()


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------

def should_emit_for_run(
    run_status: Optional[str],
    goal_status: Optional[str],
    config: AdvisoryRolloutConfig,
) -> bool:
    """Return True if advisory should be emitted for this run/goal combination.

    False if config is disabled.
    True if run_status is in target_run_statuses (failed/blocked by default).
    True if include_passed_goal_incomplete and run is passed but goal not completed.
    False otherwise (including passed+completed — no recovery needed).
    """
    if not config.should_emit:
        return False
    rs = (run_status or "").strip().lower()
    gs = (goal_status or "").strip().lower()
    if rs in config.target_run_statuses:
        return True
    if config.include_passed_goal_incomplete and rs == "passed" and gs not in ("completed", ""):
        return True
    return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _bridge_config_for_advisory(advisory_config: AdvisoryRolloutConfig):
    """Return a BridgeConfig appropriate for the advisory emission state."""
    if advisory_config.should_emit:
        return make_diagnostic_config(log_enabled=advisory_config.log_enabled)
    return DEFAULT_BRIDGE_CONFIG


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

def enrich_report_with_advisory(
    report: Dict[str, Any],
    *,
    run_status: Optional[str] = None,
    goal_status: Optional[str] = None,
    cycle: Optional[Dict[str, Any]] = None,
    advisory_config: AdvisoryRolloutConfig = DEFAULT_ADVISORY_CONFIG,
) -> Dict[str, Any]:
    """Enrich a report with an advisory recovery recommendation (additive, non-blocking).

    Returns original report if:
      - advisory_config.enabled is False, or
      - run_status is not in scope (e.g. passed+completed), or
      - any exception occurs during enrichment.
    """
    if not should_emit_for_run(run_status, goal_status, advisory_config):
        return report
    try:
        bridge_cfg = _bridge_config_for_advisory(advisory_config)
        return enrich_with_recovery(
            report,
            run_status=run_status,
            goal_status=goal_status,
            cycle=cycle,
            config=bridge_cfg,
        )
    except Exception:
        return report


def enrich_cycle_with_advisory(
    cycle: Dict[str, Any],
    *,
    advisory_config: AdvisoryRolloutConfig = DEFAULT_ADVISORY_CONFIG,
) -> Dict[str, Any]:
    """Enrich a shadow-monitoring cycle dict with an advisory recommendation.

    Reads run_status from cycle["current_loop_decision"] and
    goal_status from cycle["mission_brain_decision"].

    Non-blocking; returns cycle unchanged on any exception.
    """
    run_status  = str(cycle.get("current_loop_decision")  or "unknown")
    goal_status = str(cycle.get("mission_brain_decision") or "unknown")
    return enrich_report_with_advisory(
        cycle,
        run_status=run_status,
        goal_status=goal_status,
        cycle=cycle,
        advisory_config=advisory_config,
    )


# ---------------------------------------------------------------------------
# Presence / cleanup helpers
# ---------------------------------------------------------------------------

def has_advisory(report: Dict[str, Any]) -> bool:
    """Return True if the report contains a recovery_recommendation."""
    return has_recovery_recommendation(report)


def strip_advisory(report: Dict[str, Any]) -> Dict[str, Any]:
    """Remove recovery_recommendation from report (keeps bridge_diagnostics)."""
    return strip_recovery_recommendation(report)


def rollback(report: Dict[str, Any]) -> Dict[str, Any]:
    """Full rollback: remove both recovery_recommendation and bridge_diagnostics."""
    return {k: v for k, v in report.items()
            if k not in ("recovery_recommendation", "bridge_diagnostics")}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_advisory_output(report: Dict[str, Any]) -> Dict[str, Any]:
    """Validate advisory invariants for a single enriched report.

    Returns:
        {"valid": bool, "violations": List[str]}
    """
    violations: List[str] = []

    if has_advisory(report):
        rec = report["recovery_recommendation"]
        if rec.get("auto_executable") is not False:
            violations.append(
                f"auto_executable must be False, got {rec.get('auto_executable')!r}"
            )
        if rec.get("advisory_only") is not True:
            violations.append(
                f"advisory_only must be True, got {rec.get('advisory_only')!r}"
            )
        try:
            validate_recovery_recommendation(rec)
        except ValueError as exc:
            violations.append(str(exc))

    if "bridge_diagnostics" in report:
        bd = report["bridge_diagnostics"]
        if bd.get("affects_loop_decision") is not False:
            violations.append(
                "bridge_diagnostics.affects_loop_decision must be False"
            )
        if bd.get("is_gate") is not False:
            violations.append("bridge_diagnostics.is_gate must be False")

    return {"valid": len(violations) == 0, "violations": violations}


def validate_no_original_fields_modified(
    original: Dict[str, Any],
    enriched: Dict[str, Any],
) -> bool:
    """Return True if all original fields are preserved unchanged in the enriched report."""
    for k, v in original.items():
        if enriched.get(k) != v:
            return False
    return True


# ---------------------------------------------------------------------------
# Aggregate statistics
# ---------------------------------------------------------------------------

def aggregate_advisory_cycles(
    cycles: Iterable[Dict[str, Any]],
    *,
    advisory_config: AdvisoryRolloutConfig,
) -> Dict[str, Any]:
    """Enrich all cycles and aggregate advisory recommendation statistics."""
    enriched = [enrich_cycle_with_advisory(c, advisory_config=advisory_config) for c in cycles]

    total              = len(enriched)
    with_advisory      = sum(1 for r in enriched if has_advisory(r))

    auto_exec_viol     = sum(
        1 for r in enriched
        if has_advisory(r) and r["recovery_recommendation"].get("auto_executable") is not False
    )
    advisory_only_viol = sum(
        1 for r in enriched
        if has_advisory(r) and r["recovery_recommendation"].get("advisory_only") is not True
    )
    loop_viol          = sum(
        1 for r in enriched
        if "bridge_diagnostics" in r
        and r["bridge_diagnostics"].get("affects_loop_decision") is not False
    )
    gate_viol          = sum(
        1 for r in enriched
        if "bridge_diagnostics" in r
        and r["bridge_diagnostics"].get("is_gate") is not False
    )

    action_dist: Dict[str, int] = {}
    confidence_dist: Dict[str, int] = {}
    for r in enriched:
        if has_advisory(r):
            a = r["recovery_recommendation"].get("action", "unknown")
            c = r["recovery_recommendation"].get("confidence", "unknown")
            action_dist[a]      = action_dist.get(a, 0) + 1
            confidence_dist[c]  = confidence_dist.get(c, 0) + 1

    return {
        "total_cycles":               total,
        "cycles_with_advisory":       with_advisory,
        "auto_executable_violations":   auto_exec_viol,
        "advisory_only_violations":     advisory_only_viol,
        "loop_decision_violations":     loop_viol,
        "is_gate_violations":           gate_viol,
        "action_distribution":          action_dist,
        "confidence_distribution":      confidence_dist,
    }
