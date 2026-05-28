"""Broader Advisory Rollout — EPIC #898."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from igris.agent.mission.advisory_rollout import (
    DEFAULT_ADVISORY_CONFIG, AdvisoryRolloutConfig,
    enrich_cycle_with_advisory, enrich_report_with_advisory,
    has_advisory, validate_advisory_output,
)

BROADER_ADVISORY_REPORT_TYPES: frozenset = frozenset({"mission_execution", "diagnostic"})

@dataclass(frozen=True)
class BroaderAdvisoryConfig:
    enabled: bool = False
    include_failed: bool = True
    include_blocked: bool = False
    monitoring_only: bool = True
    log_enabled: bool = False

    @property
    def is_gate(self) -> bool:
        return False

    @property
    def effective_run_statuses(self) -> frozenset:
        statuses: set = set()
        if self.include_failed:
            statuses.add("failed")
        if self.include_blocked:
            statuses.add("blocked")
        return frozenset(statuses)

    @property
    def should_compute(self) -> bool:
        return self.enabled and bool(self.effective_run_statuses)

    @property
    def should_emit(self) -> bool:
        return self.enabled and not self.monitoring_only and bool(self.effective_run_statuses)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled, "include_failed": self.include_failed,
            "include_blocked": self.include_blocked, "monitoring_only": self.monitoring_only,
            "log_enabled": self.log_enabled, "is_gate": self.is_gate,
            "should_compute": self.should_compute, "should_emit": self.should_emit,
            "effective_run_statuses": sorted(self.effective_run_statuses),
            "broader_report_types": sorted(BROADER_ADVISORY_REPORT_TYPES),
        }

DEFAULT_BROADER_CONFIG = BroaderAdvisoryConfig(enabled=False, monitoring_only=True)

def make_broader_monitoring_config(include_blocked: bool = False, log_enabled: bool = False) -> BroaderAdvisoryConfig:
    return BroaderAdvisoryConfig(enabled=True, include_failed=True, include_blocked=include_blocked, monitoring_only=True, log_enabled=log_enabled)

def make_broader_activation_config(include_blocked: bool = False, log_enabled: bool = False) -> BroaderAdvisoryConfig:
    return BroaderAdvisoryConfig(enabled=True, include_failed=True, include_blocked=include_blocked, monitoring_only=False, log_enabled=log_enabled)

def _to_advisory_emit_config(config: BroaderAdvisoryConfig) -> AdvisoryRolloutConfig:
    if not config.should_emit:
        return DEFAULT_ADVISORY_CONFIG
    return AdvisoryRolloutConfig(enabled=True, include_passed_goal_incomplete=False, log_enabled=config.log_enabled)

def _to_advisory_compute_config(log_enabled: bool = False) -> AdvisoryRolloutConfig:
    return AdvisoryRolloutConfig(enabled=True, include_passed_goal_incomplete=False, log_enabled=log_enabled)

def should_emit_for_run_broader(run_status: Optional[str], config: BroaderAdvisoryConfig) -> bool:
    if not config.should_emit:
        return False
    return (run_status or "").strip().lower() in config.effective_run_statuses

def should_compute_for_run_broader(run_status: Optional[str], config: BroaderAdvisoryConfig) -> bool:
    if not config.should_compute:
        return False
    return (run_status or "").strip().lower() in config.effective_run_statuses

def enrich_report_broader(report: Dict[str, Any], *, run_status: Optional[str] = None,
    goal_status: Optional[str] = None, cycle: Optional[Dict[str, Any]] = None,
    config: BroaderAdvisoryConfig = DEFAULT_BROADER_CONFIG) -> Dict[str, Any]:
    if not should_emit_for_run_broader(run_status, config):
        return report
    try:
        return enrich_report_with_advisory(report, run_status=run_status, goal_status=goal_status,
            cycle=cycle, advisory_config=_to_advisory_emit_config(config))
    except Exception:
        return report

def enrich_cycle_broader(cycle: Dict[str, Any], *, config: BroaderAdvisoryConfig = DEFAULT_BROADER_CONFIG) -> Dict[str, Any]:
    run_status  = str(cycle.get("current_loop_decision")  or "unknown")
    goal_status = str(cycle.get("mission_brain_decision") or "unknown")
    return enrich_report_broader(cycle, run_status=run_status, goal_status=goal_status, cycle=cycle, config=config)

def compute_monitoring_metrics(cycles: List[Dict[str, Any]], *, config: BroaderAdvisoryConfig) -> Dict[str, Any]:
    if not config.should_compute:
        return {"total_cycles": len(cycles), "cycles_in_scope": 0, "cycles_with_advisory": 0,
                "coverage_rate": 0.0, "in_scope_coverage_rate": 0.0, "auto_executable_violations": 0,
                "action_distribution": {}, "confidence_distribution": {}, "evidence_complete_count": 0,
                "note": "should_compute=False"}
    compute_cfg = _to_advisory_compute_config()
    total = len(cycles)
    in_scope = sum(1 for c in cycles if str(c.get("current_loop_decision") or "").strip().lower() in config.effective_run_statuses)
    enriched = []
    for c in cycles:
        rs = str(c.get("current_loop_decision") or "unknown").strip().lower()
        if rs in config.effective_run_statuses:
            enriched.append(enrich_cycle_with_advisory(c, advisory_config=compute_cfg))
        else:
            enriched.append(c)
    with_advisory = sum(1 for r in enriched if has_advisory(r))
    coverage_rate = round(with_advisory / total, 4) if total > 0 else 0.0
    in_scope_coverage = round(with_advisory / in_scope, 4) if in_scope > 0 else 0.0
    auto_exec_viol = sum(1 for r in enriched if has_advisory(r) and r["recovery_recommendation"].get("auto_executable") is not False)
    action_dist: Dict[str, int] = {}
    confidence_dist: Dict[str, int] = {}
    evidence_complete = 0
    for r in enriched:
        if has_advisory(r):
            a = r["recovery_recommendation"].get("action", "unknown")
            c2 = r["recovery_recommendation"].get("confidence", "unknown")
            action_dist[a] = action_dist.get(a, 0) + 1
            confidence_dist[c2] = confidence_dist.get(c2, 0) + 1
            if not r["recovery_recommendation"].get("evidence_missing"):
                evidence_complete += 1
    return {"total_cycles": total, "cycles_in_scope": in_scope, "cycles_with_advisory": with_advisory,
            "coverage_rate": coverage_rate, "in_scope_coverage_rate": in_scope_coverage,
            "auto_executable_violations": auto_exec_viol, "action_distribution": action_dist,
            "confidence_distribution": confidence_dist, "evidence_complete_count": evidence_complete}

def aggregate_broader_cycles(cycles: List[Dict[str, Any]], *, config: BroaderAdvisoryConfig) -> Dict[str, Any]:
    enriched = [enrich_cycle_broader(c, config=config) for c in cycles]
    total = len(enriched)
    with_advisory = sum(1 for r in enriched if has_advisory(r))
    auto_exec_viol = sum(1 for r in enriched if has_advisory(r) and r["recovery_recommendation"].get("auto_executable") is not False)
    loop_viol = sum(1 for r in enriched if "bridge_diagnostics" in r and r["bridge_diagnostics"].get("affects_loop_decision") is not False)
    gate_viol = sum(1 for r in enriched if "bridge_diagnostics" in r and r["bridge_diagnostics"].get("is_gate") is not False)
    action_dist: Dict[str, int] = {}
    for r in enriched:
        if has_advisory(r):
            a = r["recovery_recommendation"].get("action", "unknown")
            action_dist[a] = action_dist.get(a, 0) + 1
    return {"total_cycles": total, "cycles_with_advisory": with_advisory,
            "auto_executable_violations": auto_exec_viol, "loop_decision_violations": loop_viol,
            "is_gate_violations": gate_viol, "action_distribution": action_dist}

def make_synthetic_blocked_cycles(n: int = 10, goal_status: str = "partial") -> List[Dict[str, Any]]:
    return [{"cycle_id": f"synthetic-blocked-{i}", "current_loop_decision": "blocked",
             "mission_brain_decision": goal_status, "goal_class": "planning" if i % 2 == 0 else "policy_check",
             "synthetic": True} for i in range(n)]
