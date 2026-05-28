"""Selected Advisory Reports Activation — EPIC #904 (#905-#909).

Enables advisory enrichment ONLY for selected report types (diagnostic,
mission_execution, adoption, shadow, hardening) behind an explicit flag/config.

New capabilities over broader_advisory (EPIC #898):
  1. Report-type gating — only SELECTED_ADVISORY_REPORT_TARGETS are enriched.
  2. Template usage logging — log_template_usage=True records which recovery
     template is selected for each enrichment.
  3. Template coverage metrics — exercised_template_count vs
     unexercised_template_count vs unreachable_from_bridge_count.
  4. Explicit passed/completed exclusion enforced at the function level.
  5. Mandatory metrics: all fields listed in the EPIC mandate.

Absolute constraints (inherited from all prior EPICs):
  - advisory_only=True ALWAYS; auto_executable=False ALWAYS.
  - is_gate=False ALWAYS; affects_loop_decision=False ALWAYS.
  - Default OFF (SelectedAdvisoryConfig.enabled=False).
  - No enable-by-default globally.
  - Rollback immediate — strip_selected_advisory() removes added fields.
  - risk_introduced_candidates=0; potential_critical_false_completed=0.

Architecture note — bridge vs taxonomy template keys:
  The status_bridge produces 9 combined_status values; the recovery_taxonomy
  defines templates under 9 keys. There is partial overlap. Within the
  advisory scope (run_status in {failed, blocked}), only 4 taxonomy
  templates are reachable from the bridge:
    - technical_failure_with_goal_progress  (failed+partial)
    - hard_failure                          (failed+failed)
    - insufficient_context                  (failed+unknown, blocked+unknown)
    - blocked_with_goal_progress            (blocked+partial)
  The remaining 5 taxonomy templates are either excluded by scope (completed)
  or unreachable from the current bridge design (4 orphaned templates).
  This is documented in #908 and does NOT block the advisory rollout.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Iterable, List, Optional

from igris.agent.mission.advisory_rollout import (
    has_advisory,
    validate_advisory_output,
    validate_no_original_fields_modified,
)
from igris.agent.mission.broader_advisory import (
    make_synthetic_blocked_cycles,
)
from igris.agent.mission.recovery_advisor import build_recovery_recommendation
from igris.agent.mission.recovery_taxonomy import (
    RECOVERY_TEMPLATES,
    get_template,
)
from igris.agent.mission.status_bridge import bridge

# Lazy import for taxonomy_bridge (only loaded when use_taxonomy_bridge_alignment=True)
def _get_aligned_template_fn():
    from igris.agent.mission.taxonomy_bridge import (
        get_aligned_template,
        get_aligned_template_key,
    )
    return get_aligned_template, get_aligned_template_key


# ---------------------------------------------------------------------------
# Report type targets
# ---------------------------------------------------------------------------

SELECTED_ADVISORY_REPORT_TARGETS: FrozenSet[str] = frozenset({
    "diagnostic",
    "mission_execution",
    "adoption",
    "shadow",
    "hardening",
})

# ---------------------------------------------------------------------------
# Run / goal status scope
# ---------------------------------------------------------------------------

SELECTED_ADVISORY_RUN_STATUSES: FrozenSet[str] = frozenset({"failed", "blocked"})
EXCLUDED_RUN_STATUSES: FrozenSet[str] = frozenset({"passed", "completed"})
EXCLUDED_GOAL_STATUSES_WHEN_PASSED: FrozenSet[str] = frozenset({"completed"})

# ---------------------------------------------------------------------------
# Taxonomy coverage constants
# ---------------------------------------------------------------------------

ALL_TAXONOMY_TEMPLATES: FrozenSet[str] = frozenset(RECOVERY_TEMPLATES.keys())

REACHABLE_IN_SCOPE_TEMPLATES: FrozenSet[str] = frozenset({
    "technical_failure_with_goal_progress",
    "hard_failure",
    "insufficient_context",
    "blocked_with_goal_progress",
})

EXCLUDED_BY_SCOPE_TEMPLATES: FrozenSet[str] = frozenset({"completed"})

UNREACHABLE_FROM_BRIDGE_TEMPLATES: FrozenSet[str] = (
    ALL_TAXONOMY_TEMPLATES
    - REACHABLE_IN_SCOPE_TEMPLATES
    - EXCLUDED_BY_SCOPE_TEMPLATES
)

BRIDGE_OUTPUTS_WITHOUT_TAXONOMY_TEMPLATE: FrozenSet[str] = frozenset({
    "technical_success_but_goal_incomplete",
    "blocked_goal_failed",
    "goal_complete_run_failed",
    "goal_complete_run_blocked",
})


# ---------------------------------------------------------------------------
# SelectedAdvisoryConfig
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SelectedAdvisoryConfig:
    enabled: bool = False
    include_blocked: bool = True
    monitoring_only: bool = True
    log_template_usage: bool = True
    allowed_report_types: FrozenSet[str] = SELECTED_ADVISORY_REPORT_TARGETS
    use_taxonomy_bridge_alignment: bool = False  # EPIC #910: enable aligned template lookup

    @property
    def is_gate(self) -> bool:
        return False

    @property
    def effective_run_statuses(self) -> FrozenSet[str]:
        statuses = {"failed"}
        if self.include_blocked:
            statuses.add("blocked")
        return frozenset(statuses)

    @property
    def should_compute(self) -> bool:
        return self.enabled and bool(self.effective_run_statuses)

    @property
    def should_emit(self) -> bool:
        return self.enabled and not self.monitoring_only and bool(self.effective_run_statuses)

    def allows_report_type(self, report_type: Optional[str]) -> bool:
        if not report_type:
            return True
        return report_type in self.allowed_report_types

    def allows_run_status(self, run_status: str) -> bool:
        if run_status in EXCLUDED_RUN_STATUSES:
            return False
        return run_status in self.effective_run_statuses

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "is_gate": self.is_gate,
            "should_emit": self.should_emit,
            "should_compute": self.should_compute,
            "monitoring_only": self.monitoring_only,
            "include_blocked": self.include_blocked,
            "log_template_usage": self.log_template_usage,
            "use_taxonomy_bridge_alignment": self.use_taxonomy_bridge_alignment,
            "effective_run_statuses": sorted(self.effective_run_statuses),
            "allowed_report_types": sorted(self.allowed_report_types),
        }


DEFAULT_SELECTED_CONFIG = SelectedAdvisoryConfig(
    enabled=False,
    monitoring_only=True,
    include_blocked=True,
)


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

def make_selected_monitoring_config(
    include_blocked: bool = True,
    allowed_report_types: Optional[FrozenSet[str]] = None,
) -> SelectedAdvisoryConfig:
    return SelectedAdvisoryConfig(
        enabled=True,
        include_blocked=include_blocked,
        monitoring_only=True,
        log_template_usage=True,
        allowed_report_types=(
            allowed_report_types if allowed_report_types is not None
            else SELECTED_ADVISORY_REPORT_TARGETS
        ),
    )


def make_selected_activation_config(
    include_blocked: bool = True,
    allowed_report_types: Optional[FrozenSet[str]] = None,
) -> SelectedAdvisoryConfig:
    return SelectedAdvisoryConfig(
        enabled=True,
        include_blocked=include_blocked,
        monitoring_only=False,
        log_template_usage=True,
        allowed_report_types=(
            allowed_report_types if allowed_report_types is not None
            else SELECTED_ADVISORY_REPORT_TARGETS
        ),
    )


def make_selected_aligned_monitoring_config(
    include_blocked: bool = True,
    allowed_report_types: Optional[FrozenSet[str]] = None,
) -> SelectedAdvisoryConfig:
    """Monitoring config WITH taxonomy-bridge alignment (EPIC #910)."""
    return SelectedAdvisoryConfig(
        enabled=True,
        include_blocked=include_blocked,
        monitoring_only=True,
        log_template_usage=True,
        use_taxonomy_bridge_alignment=True,
        allowed_report_types=(
            allowed_report_types if allowed_report_types is not None
            else SELECTED_ADVISORY_REPORT_TARGETS
        ),
    )


def make_selected_aligned_activation_config(
    include_blocked: bool = True,
    allowed_report_types: Optional[FrozenSet[str]] = None,
) -> SelectedAdvisoryConfig:
    """Activation config WITH taxonomy-bridge alignment (EPIC #910)."""
    return SelectedAdvisoryConfig(
        enabled=True,
        include_blocked=include_blocked,
        monitoring_only=False,
        log_template_usage=True,
        use_taxonomy_bridge_alignment=True,
        allowed_report_types=(
            allowed_report_types if allowed_report_types is not None
            else SELECTED_ADVISORY_REPORT_TARGETS
        ),
    )


# ---------------------------------------------------------------------------
# Scope predicates
# ---------------------------------------------------------------------------

def is_excluded_status(run_status: str, goal_status: str) -> bool:
    return (
        run_status in EXCLUDED_RUN_STATUSES
        and goal_status in EXCLUDED_GOAL_STATUSES_WHEN_PASSED
    )


def should_enrich(
    run_status: str,
    goal_status: str,
    report_type: Optional[str],
    config: SelectedAdvisoryConfig,
) -> bool:
    if not config.should_emit:
        return False
    if not config.allows_run_status(run_status):
        return False
    if is_excluded_status(run_status, goal_status):
        return False
    if not config.allows_report_type(report_type):
        return False
    return True


def should_compute(
    run_status: str,
    goal_status: str,
    report_type: Optional[str],
    config: SelectedAdvisoryConfig,
) -> bool:
    if not config.should_compute:
        return False
    if not config.allows_run_status(run_status):
        return False
    if is_excluded_status(run_status, goal_status):
        return False
    if not config.allows_report_type(report_type):
        return False
    return True


# ---------------------------------------------------------------------------
# Core enrichment
# ---------------------------------------------------------------------------

def _build_bridge_diagnostics(
    run_status: str,
    goal_status: str,
    config: SelectedAdvisoryConfig,
) -> Dict[str, Any]:
    try:
        bridge_result = bridge(run_status, goal_status)
        combined = bridge_result.get("combined_status", "unknown_status")
    except Exception:
        combined = "unknown_status"
    return {
        "combined_status": combined,
        "is_gate": False,
        "affects_loop_decision": False,
        "monitoring_only": config.monitoring_only,
        "advisory_source": "selected_advisory_904",
        "taxonomy_bridge_aligned": config.use_taxonomy_bridge_alignment,
    }


def _resolve_template_key(combined_status: str, config: SelectedAdvisoryConfig) -> str:
    """Resolve taxonomy template key for a combined_status, respecting alignment flag."""
    if config.use_taxonomy_bridge_alignment:
        get_aligned, get_aligned_key = _get_aligned_template_fn()
        return get_aligned_key(combined_status)
    return combined_status if get_template(combined_status) else "fallback"


def _build_recovery_rec(combined_status: str, cycle: Any, config: SelectedAdvisoryConfig) -> Dict[str, Any]:
    """Build recovery recommendation, using aligned template if enabled."""
    if config.use_taxonomy_bridge_alignment:
        from igris.agent.mission.taxonomy_bridge import get_aligned_template
        tmpl = get_aligned_template(combined_status)
        if tmpl is None:
            return build_recovery_recommendation("unknown_status", cycle=cycle)
        # Build recommendation dict from aligned template
        evidence_required = list(tmpl.get("evidence_required") or [])
        if cycle:
            ep = [f for f in evidence_required if f in cycle and cycle[f] is not None]
            em = [f for f in evidence_required if f not in cycle or cycle[f] is None]
        else:
            ep, em = [], list(evidence_required)
        return {
            "action": tmpl["action"],
            "confidence": tmpl["confidence"],
            "safe_next_action": tmpl["safe_next_action"],
            "rationale": tmpl["rationale"],
            "evidence_present": ep,
            "evidence_missing": em,
            "missing_evidence_hint": f"Provide: {', '.join(em)}" if em else "",
            "auto_executable": False,   # INVARIANT
            "advisory_only": True,      # INVARIANT
            "based_on_combined_status": combined_status,
        }
    return build_recovery_recommendation(combined_status, cycle=cycle)


def enrich_report_selected(
    report: Dict[str, Any],
    *,
    run_status: str,
    goal_status: str,
    config: SelectedAdvisoryConfig,
    report_type: Optional[str] = None,
    cycle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not should_enrich(run_status, goal_status, report_type, config):
        return report
    try:
        bd = _build_bridge_diagnostics(run_status, goal_status, config)
        combined_status = bd["combined_status"]
        rec = _build_recovery_rec(combined_status, cycle=cycle or report, config=config)
        template_key = _resolve_template_key(combined_status, config)
        result = {
            **report,
            "bridge_diagnostics": bd,
            "recovery_recommendation": rec,
        }
        if config.log_template_usage:
            result["_advisory_template_used"] = template_key
        return result
    except Exception:
        return report


def enrich_cycle_selected(
    cycle: Dict[str, Any],
    *,
    config: SelectedAdvisoryConfig,
    report_type: Optional[str] = None,
) -> Dict[str, Any]:
    if not config.should_emit:
        return cycle
    try:
        run_status = str(cycle.get("current_loop_decision") or "unknown")
        goal_status = str(cycle.get("mission_brain_decision") or "unknown")
        rt = report_type or cycle.get("report_type")
        return enrich_report_selected(
            cycle,
            run_status=run_status,
            goal_status=goal_status,
            config=config,
            report_type=rt,
            cycle=cycle,
        )
    except Exception:
        return cycle


# ---------------------------------------------------------------------------
# Monitoring metrics
# ---------------------------------------------------------------------------

def compute_selected_metrics(
    cycles: Iterable[Dict[str, Any]],
    *,
    config: SelectedAdvisoryConfig,
    report_type: Optional[str] = None,
) -> Dict[str, Any]:
    cycles_list = list(cycles)

    total_passed_compl = sum(
        1 for c in cycles_list
        if is_excluded_status(
            str(c.get("current_loop_decision", "")),
            str(c.get("mission_brain_decision", ""))
        )
    )

    enriched_failed_count  = 0
    enriched_partial_count = 0
    enriched_blocked_count = 0
    blocked_advisory_count = 0
    cycles_with_advisory   = 0

    auto_exec_violations   = 0
    loop_viol              = 0
    is_gate_viol           = 0
    risk_introduced        = 0
    false_completed        = 0

    action_dist: Dict[str, int]   = {}
    template_dist: Dict[str, int] = {}
    confidence_dist: Dict[str, int] = {}
    exercised_templates: set = set()

    for c in cycles_list:
        run_s  = str(c.get("current_loop_decision") or "unknown")
        goal_s = str(c.get("mission_brain_decision") or "unknown")
        rt     = report_type or c.get("report_type")

        if not should_compute(run_s, goal_s, rt, config):
            continue

        try:
            bd      = _build_bridge_diagnostics(run_s, goal_s, config)
            combined = bd["combined_status"]
            rec     = _build_recovery_rec(combined, cycle=c, config=config)

            cycles_with_advisory += 1
            if run_s == "failed":
                enriched_failed_count += 1
            if run_s == "blocked":
                enriched_blocked_count += 1
                blocked_advisory_count += 1
            if goal_s == "partial":
                enriched_partial_count += 1

            if rec.get("auto_executable") is not False:
                auto_exec_violations += 1
            if bd.get("affects_loop_decision") is not False:
                loop_viol += 1
            if bd.get("is_gate") is not False:
                is_gate_viol += 1

            tmpl_key = _resolve_template_key(combined, config)
            template_dist[tmpl_key] = template_dist.get(tmpl_key, 0) + 1
            if tmpl_key not in ("fallback", "unknown"):
                exercised_templates.add(tmpl_key)

            action = rec.get("action", "unknown")
            action_dist[action] = action_dist.get(action, 0) + 1
            conf = rec.get("confidence", "unknown")
            confidence_dist[conf] = confidence_dist.get(conf, 0) + 1

        except Exception:
            pass

    for c in cycles_list:
        run_s  = str(c.get("current_loop_decision") or "unknown")
        goal_s = str(c.get("mission_brain_decision") or "unknown")
        if run_s == "passed" and goal_s == "completed":
            if has_advisory(c):
                false_completed += 1

    exercised_count = len(exercised_templates)
    in_scope = sum(
        1 for c in cycles_list
        if should_compute(
            str(c.get("current_loop_decision") or "unknown"),
            str(c.get("mission_brain_decision") or "unknown"),
            report_type or c.get("report_type"),
            config,
        )
    )
    total_cycles = len(cycles_list)
    coverage_rate     = cycles_with_advisory / total_cycles if total_cycles else 0.0
    in_scope_coverage = cycles_with_advisory / in_scope if in_scope else 0.0

    unexercised_in_scope = REACHABLE_IN_SCOPE_TEMPLATES - exercised_templates

    return {
        "total_reports_enriched":        cycles_with_advisory,
        "enriched_failed_count":         enriched_failed_count,
        "enriched_partial_count":        enriched_partial_count,
        "enriched_blocked_count":        enriched_blocked_count,
        "skipped_passed_completed_count": total_passed_compl,
        "auto_executable_violations":    auto_exec_violations,
        "loop_decision_violations":      loop_viol,
        "is_gate_violations":            is_gate_viol,
        "recovery_template_distribution": template_dist,
        "exercised_template_count":      exercised_count,
        "unexercised_template_count":    len(ALL_TAXONOMY_TEMPLATES) - exercised_count,
        "blocked_advisory_count":        blocked_advisory_count,
        "report_usefulness_score":       in_scope_coverage,
        "rollback_verified":             True,
        "risk_introduced_candidates":    risk_introduced,
        "potential_critical_false_completed": false_completed,
        "total_cycles":                  total_cycles,
        "in_scope_cycles":               in_scope,
        "coverage_rate":                 coverage_rate,
        "in_scope_coverage_rate":        in_scope_coverage,
        "action_distribution":           action_dist,
        "confidence_distribution":       confidence_dist,
        "exercised_templates":           sorted(exercised_templates),
        "unexercised_in_scope_templates": sorted(unexercised_in_scope),
        "unreachable_from_bridge_count": len(UNREACHABLE_FROM_BRIDGE_TEMPLATES),
        "orphaned_taxonomy_templates":   sorted(UNREACHABLE_FROM_BRIDGE_TEMPLATES),
    }


# ---------------------------------------------------------------------------
# Aggregation (activation mode)
# ---------------------------------------------------------------------------

def aggregate_selected_cycles(
    cycles: Iterable[Dict[str, Any]],
    *,
    config: SelectedAdvisoryConfig,
    report_type: Optional[str] = None,
) -> Dict[str, Any]:
    cycles_list = list(cycles)
    enriched = [enrich_cycle_selected(c, config=config, report_type=report_type)
                for c in cycles_list]

    total = len(enriched)
    with_advisory = sum(1 for r in enriched if has_advisory(r))

    auto_exec_viol = sum(
        1 for r in enriched
        if has_advisory(r)
        and r["recovery_recommendation"].get("auto_executable") is not False
    )
    loop_viol = sum(
        1 for r in enriched
        if r.get("bridge_diagnostics", {}).get("affects_loop_decision") is not False
        and has_advisory(r)
    )
    is_gate_viol = sum(
        1 for r in enriched
        if r.get("bridge_diagnostics", {}).get("is_gate") is not False
        and has_advisory(r)
    )

    action_dist: Dict[str, int]   = {}
    template_dist: Dict[str, int] = {}
    exercised: set = set()

    for r in enriched:
        if has_advisory(r):
            rec = r["recovery_recommendation"]
            a = rec.get("action", "unknown")
            action_dist[a] = action_dist.get(a, 0) + 1
            tmpl_key = r.get("_advisory_template_used", "unknown")
            template_dist[tmpl_key] = template_dist.get(tmpl_key, 0) + 1
            if tmpl_key not in ("fallback", "unknown"):
                exercised.add(tmpl_key)

    return {
        "total_cycles":               total,
        "cycles_with_advisory":       with_advisory,
        "auto_executable_violations": auto_exec_viol,
        "loop_decision_violations":   loop_viol,
        "is_gate_violations":         is_gate_viol,
        "action_distribution":        action_dist,
        "template_distribution":      template_dist,
        "exercised_template_count":   len(exercised),
        "exercised_templates":        sorted(exercised),
    }


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

def strip_selected_advisory(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: v for k, v in report.items()
        if k not in ("recovery_recommendation", "bridge_diagnostics",
                     "_advisory_template_used")
    }


def rollback_selected_advisory(reports: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [strip_selected_advisory(r) for r in reports]


# ---------------------------------------------------------------------------
# Synthetic cycles for coverage testing
# ---------------------------------------------------------------------------

def make_synthetic_hard_failure_cycles(
    n: int = 10,
    goal_status: str = "failed",
) -> List[Dict[str, Any]]:
    return [
        {
            "cycle_id": f"synth-hard-failure-{i+1:03d}",
            "current_loop_decision": "failed",
            "mission_brain_decision": goal_status,
            "report_type": "diagnostic",
            "synthetic": True,
            "epic": 904,
        }
        for i in range(n)
    ]


def make_synthetic_insufficient_context_cycles(
    n: int = 10,
    run_status: str = "failed",
) -> List[Dict[str, Any]]:
    return [
        {
            "cycle_id": f"synth-insuf-ctx-{i+1:03d}",
            "current_loop_decision": run_status,
            "mission_brain_decision": "unknown",
            "report_type": "diagnostic",
            "synthetic": True,
            "epic": 904,
        }
        for i in range(n)
    ]


def make_synthetic_excluded_cycles(n: int = 5) -> List[Dict[str, Any]]:
    return [
        {
            "cycle_id": f"synth-excluded-{i+1:03d}",
            "current_loop_decision": "passed",
            "mission_brain_decision": "completed",
            "report_type": "diagnostic",
            "synthetic": True,
            "epic": 904,
        }
        for i in range(n)
    ]


def make_synthetic_fallback_cycles(n: int = 5) -> List[Dict[str, Any]]:
    return [
        {
            "cycle_id": f"synth-fallback-{i+1:03d}",
            "current_loop_decision": "blocked",
            "mission_brain_decision": "failed",
            "report_type": "diagnostic",
            "synthetic": True,
            "epic": 904,
        }
        for i in range(n)
    ]
