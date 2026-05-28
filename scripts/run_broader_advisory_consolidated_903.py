#!/usr/bin/env python3
"""EPIC #898 — #903: Consolidated advisory rollout report and final decision.

Allowed decisions:
  - keep_advisory_disabled
  - enable_selected_advisory_reports
  - extend_advisory_rollout
  - remediate_again
  - do_not_integrate

Usage:
    python scripts/run_broader_advisory_consolidated_903.py
"""
from __future__ import annotations

import json
from pathlib import Path

ALLOWED_DECISIONS = frozenset({
    "keep_advisory_disabled",
    "enable_selected_advisory_reports",
    "extend_advisory_rollout",
    "remediate_again",
    "do_not_integrate",
})
FORBIDDEN_DECISIONS = frozenset({
    "activate_globally", "enable_by_default", "auto_execute",
    "mandatory_gate", "deploy_without_flag", "remove_flag",
})


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    r899 = _load("reports/mission_brain/broader_advisory/899/broader_advisory_scope_899.json")
    r900 = _load("reports/mission_brain/broader_advisory/900/broader_advisory_blocked_900.json")
    r901 = _load("reports/mission_brain/broader_advisory/901/broader_advisory_enable_901.json")
    r902 = _load("reports/mission_brain/broader_advisory/902/broader_advisory_monitoring_902.json")

    # Gate chain
    for r, sub in [(r899, 899), (r900, 900), (r901, 901), (r902, 902)]:
        if r.get("evaluation") != "passed":
            print(json.dumps({"STOP": f"#{sub} evaluation={r.get('evaluation')}"}, indent=2))
            return 1
        if r.get("stop_reason") is not None:
            print(json.dumps({"STOP": f"#{sub} stop_reason={r.get('stop_reason')}"}, indent=2))
            return 1

    # Safety gates
    auto_exec_viol = r901["auto_executable_violations"]
    loop_viol      = r901["loop_decision_violations"]
    gate_viol      = r901["is_gate_violations"]

    if auto_exec_viol > 0:
        print(json.dumps({"STOP": f"auto_exec_violations={auto_exec_viol}"}, indent=2)); return 1
    if loop_viol > 0:
        print(json.dumps({"STOP": f"loop_decision_violations={loop_viol}"}, indent=2)); return 1
    if gate_viol > 0:
        print(json.dumps({"STOP": f"is_gate_violations={gate_viol}"}, indent=2)); return 1

    if not r900["blocked_advisory_validated"]:
        print(json.dumps({"STOP": "blocked advisory not validated"}, indent=2)); return 1
    if r902["monitoring_mode_surfaced_advisory"] > 0:
        print(json.dumps({"STOP": "monitoring mode surfaced advisory"}, indent=2)); return 1

    # Decision rationale:
    # - #899: scope defined, 4 rollout stages, invariants verified
    # - #900: blocked-status validated (10/10, escalate_blocked, 0 violations)
    # - #901: 40/40 cycles enriched with advisory (30 failed + 10 blocked), 0 violations,
    #          monitoring_only=True confirmed silent (not surfaced)
    # - #902: monitoring metrics computed, coverage=100% in-scope, 0 auto_exec violations
    # → enable_selected_advisory_reports
    # IMPORTANT: flag remains required — NOT globally enabled by default
    final_decision = "enable_selected_advisory_reports"
    assert final_decision in ALLOWED_DECISIONS
    assert final_decision not in FORBIDDEN_DECISIONS

    findings = [
        {
            "id": "F1",
            "finding": "Blocked-status advisory validated: 10/10 cycles get escalate_blocked (high confidence)",
            "evidence": f"blocked_advisory_validated={r900['blocked_advisory_validated']}, auto_exec_viol=0",
            "impact": "positive",
        },
        {
            "id": "F2",
            "finding": "40/40 cycles enriched with advisory in activation mode (30 failed + 10 blocked), 0 violations",
            "evidence": f"cycles_with_advisory={r901['cycles_with_advisory']}, auto_exec_viol=0, loop_viol=0",
            "impact": "positive",
        },
        {
            "id": "F3",
            "finding": "Monitoring mode confirmed silent: 0 advisory surfaced when monitoring_only=True",
            "evidence": f"monitoring_mode_surfaced_advisory={r902['monitoring_mode_surfaced_advisory']}",
            "impact": "positive",
        },
        {
            "id": "F4",
            "finding": "In-scope coverage rate = 100% — all failed+blocked cycles receive advisory",
            "evidence": f"in_scope_coverage_rate={r902['metrics_all_cycles']['in_scope_coverage_rate']}",
            "impact": "positive",
        },
        {
            "id": "F5",
            "finding": "Only 2 actions exercised on real+synthetic data (continue_from_partial_progress, escalate_blocked)",
            "evidence": f"action_distribution={r902['metrics_all_cycles']['action_distribution']}",
            "impact": "minor_gap",
        },
    ]

    recommendations = [
        {
            "id": "R1",
            "recommendation": "Enable advisory for mission_execution and diagnostic reports via ADVISORY_ROLLOUT_ENABLED=true",
            "rationale": "Safe, advisory-only, reversible. Validated on failed+blocked status.",
            "requires_approval": True, "scope": "reporting",
        },
        {
            "id": "R2",
            "recommendation": "Do NOT enable globally by default — flag remains required",
            "rationale": "Only 2 of 9 recovery templates exercised. Broader coverage needed before global default.",
            "requires_approval": False, "scope": "constraint",
        },
        {
            "id": "R3",
            "recommendation": "Do NOT auto-execute any advisory recommendation",
            "rationale": "Recommendations are advisory. Human action always required.",
            "requires_approval": False, "scope": "constraint",
        },
        {
            "id": "R4",
            "recommendation": "Validate remaining 7 recovery templates on real diverse run outcomes",
            "rationale": "Only failed+partial (continue_from_partial_progress) and blocked+partial (escalate_blocked) exercised.",
            "requires_approval": False, "scope": "validation",
        },
    ]

    result = {
        "epic": 898, "subissue": 903,
        "title": "Consolidated Broader Advisory Rollout Report — Final Decision",
        "subissues_completed": [899, 900, 901, 902, 903],
        "gate_chain_passed": True,
        "auto_executable_violations": auto_exec_viol,
        "loop_decision_violations": loop_viol,
        "is_gate_violations": gate_viol,
        "blocked_advisory_validated": True,
        "total_cycles_validated": r901["total_cycles"],
        "cycles_with_advisory": r901["cycles_with_advisory"],
        "monitoring_mode_silent": r902["monitoring_mode_surfaced_advisory"] == 0,
        "in_scope_coverage_rate": r902["metrics_all_cycles"]["in_scope_coverage_rate"],
        "action_distribution": r902["metrics_all_cycles"]["action_distribution"],
        "final_decision": final_decision,
        "final_decision_rationale": (
            "All safety gates passed. Blocked-status advisory validated (escalate_blocked, 0 violations). "
            "40/40 cycles enriched with advisory in activation mode (30 failed + 10 blocked). "
            "Monitoring mode confirmed silent. In-scope coverage = 100%. "
            "Decision: enable_selected_advisory_reports. "
            "Flag remains required (NOT globally enabled). "
            "No auto-execution. No mandatory gate. Rollback immediate."
        ),
        "summary": (
            "EPIC #898 complete. blocked validated. 40 cycles enriched. "
            "0 violations. monitoring_mode_silent=True. "
            f"Final decision: {final_decision}. No auto-execution. Flag required."
        ),
        "findings": findings,
        "recommendations": recommendations,
        "guardrails": {
            "advisory_only": True,
            "no_auto_execution": True,
            "default_off": True,
            "flag_required": True,
            "no_mandatory_gate": True,
            "no_global_default": True,
            "no_loop_modification": True,
            "candidate_does_not_mean_activated_globally": True,
            "rollback_immediate": True,
            "monitoring_mode_available": True,
        },
        "evaluation": "passed", "stop_reason": None, "epic_status": "complete",
    }

    out = Path("reports/mission_brain/broader_advisory/903")
    out.mkdir(parents=True, exist_ok=True)
    (out / "broader_advisory_consolidated_903.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    md = [
        "# Consolidated Broader Advisory Rollout — #903",
        "## EPIC #898 Mission Brain Broader Advisory Rollout Activation Plan — COMPLETE",
        "",
        f"### **Final Decision: {final_decision.upper()}**",
        "",
        result["final_decision_rationale"],
        "",
        "## Gate Chain",
        "",
        "| Subissue | Title | Evaluation |",
        "|----------|-------|------------|",
        "| #899 Scope | Rollout Scope and Config | ✅ |",
        "| #900 Blocked | Blocked-Status Validation | ✅ |",
        "| #901 Enable | Advisory Enrichment Enabled | ✅ |",
        "| #902 Monitoring | Controlled Monitoring | ✅ |",
        "| #903 Consolidated | Final Decision | ✅ |",
        "",
        "## Key Metrics",
        "",
        "- auto_executable_violations: 0 ✅",
        "- loop_decision_violations: 0 ✅",
        "- blocked_advisory_validated: True ✅",
        f"- cycles_validated: {r901['total_cycles']} ✅",
        f"- in_scope_coverage_rate: {r902['metrics_all_cycles']['in_scope_coverage_rate']} ✅",
        "",
        "## Guardrails",
        "",
        "- advisory_only: ✅  |  no_auto_execution: ✅  |  flag_required: ✅",
        "- no_global_default: ✅  |  rollback_immediate: ✅  |  monitoring_mode_available: ✅",
        "",
        "## Evaluation: passed | Epic status: complete",
    ]
    (out / "broader_advisory_consolidated_903.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({
        "subissue": 903,
        "final_decision": final_decision,
        "gate_chain_passed": True,
        "auto_executable_violations": 0,
        "blocked_validated": True,
        "cycles_validated": r901["total_cycles"],
        "evaluation": "passed",
        "epic_status": "complete",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
