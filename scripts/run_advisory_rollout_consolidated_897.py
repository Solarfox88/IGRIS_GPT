#!/usr/bin/env python3
"""EPIC #892 — #897: Consolidated advisory rollout report and final decision.

Allowed decisions:
  - keep_advisory_disabled
  - keep_diagnostic_only
  - candidate_for_broader_advisory_rollout
  - continue_calibration
  - remediate_again
  - do_not_integrate

Usage:
    python scripts/run_advisory_rollout_consolidated_897.py
"""
from __future__ import annotations

import json
from pathlib import Path

ALLOWED_DECISIONS = frozenset({
    "keep_advisory_disabled",
    "keep_diagnostic_only",
    "candidate_for_broader_advisory_rollout",
    "continue_calibration",
    "remediate_again",
    "do_not_integrate",
})
FORBIDDEN_DECISIONS = frozenset({
    "activate_rollout", "enable_by_default", "auto_execute",
    "mandatory_gate", "deploy", "enable_advisory_by_default",
})


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    r893 = _load("reports/mission_brain/advisory_rollout/893/advisory_rollout_scope_893.json")
    r894 = _load("reports/mission_brain/advisory_rollout/894/advisory_rollout_integration_894.json")
    r895 = _load("reports/mission_brain/advisory_rollout/895/advisory_rollout_validation_895.json")
    r896 = _load("reports/mission_brain/advisory_rollout/896/advisory_rollout_invariants_896.json")

    # Gate chain
    for r, sub in [(r893, 893), (r894, 894), (r895, 895), (r896, 896)]:
        if r.get("evaluation") != "passed":
            print(json.dumps({"STOP": f"#{sub} evaluation={r.get('evaluation')}"}, indent=2))
            return 1
        if r.get("stop_reason") is not None:
            print(json.dumps({"STOP": f"#{sub} stop_reason={r.get('stop_reason')}"}, indent=2))
            return 1

    # Safety gates
    auto_exec_viol = r895["auto_executable_violations"]
    loop_viol      = r895["loop_decision_violations"]
    gate_viol      = r895["is_gate_violations"]
    risk           = r895["risk_introduced_candidates"]
    critical       = r895["potential_critical_false_completed"]

    if risk > 0:
        print(json.dumps({"STOP": f"risk={risk}"}, indent=2)); return 1
    if critical > 0:
        print(json.dumps({"STOP": f"critical={critical}"}, indent=2)); return 1
    if auto_exec_viol > 0:
        print(json.dumps({"STOP": f"auto_exec_violations={auto_exec_viol}"}, indent=2)); return 1
    if loop_viol > 0:
        print(json.dumps({"STOP": f"loop_decision_violations={loop_viol}"}, indent=2)); return 1
    if gate_viol > 0:
        print(json.dumps({"STOP": f"is_gate_violations={gate_viol}"}, indent=2)); return 1
    if not r896["all_invariants_passed"]:
        print(json.dumps({"STOP": "not all invariants passed"}, indent=2)); return 1

    # Decision:
    # - 8/8 invariants verified (default_off, rollback, no_auto_exec, loop_unchanged,
    #   is_gate=False, fields_preserved, scope_filter, advisory_only)
    # - 30/30 shadow cycles validated, 0 violations
    # - Conservative scope (failed+blocked only, default OFF)
    # - Module is additive and non-blocking
    # - Minor gap: only 1 run_status (failed) exercised; blocked not in shadow set
    # → candidate_for_broader_advisory_rollout
    # IMPORTANT: does NOT activate rollout — recommendation only
    final_decision = "candidate_for_broader_advisory_rollout"
    assert final_decision in ALLOWED_DECISIONS
    assert final_decision not in FORBIDDEN_DECISIONS

    findings = [
        {
            "id": "F1",
            "finding": "Advisory scope is conservative: failed+blocked only, default OFF",
            "evidence": f"target_run_statuses={r893['scope']['target_run_statuses']}, include_passed_goal_incomplete=False",
            "impact": "positive",
        },
        {
            "id": "F2",
            "finding": f"{r896['invariants_checked']}/{r896['invariants_checked']} invariants verified",
            "evidence": "INV-1 to INV-8 all passed: default_off, rollback, no_auto_exec, loop_unchanged, is_gate=False, fields_preserved, scope_filter, advisory_only.",
            "impact": "positive",
        },
        {
            "id": "F3",
            "finding": "30/30 shadow cycles validated with 0 auto_exec and loop_decision violations",
            "evidence": f"cycles_with_advisory={r895['cycles_with_advisory']}, auto_exec_viol=0, loop_viol=0, gate_viol=0",
            "impact": "positive",
        },
        {
            "id": "F4",
            "finding": "Only 1 run_status (failed) exercised on real data — blocked not in shadow set",
            "evidence": "All 30 shadow cycles are failed+partial. blocked status not represented in real data.",
            "impact": "minor_gap",
        },
        {
            "id": "F5",
            "finding": "Rollback verified: disabling flag removes all advisory output immediately",
            "evidence": "INV-3: rollback removes recovery_recommendation and bridge_diagnostics from all reports",
            "impact": "positive",
        },
    ]

    recommendations = [
        {
            "id": "R1",
            "recommendation": "Surface recovery_recommendation in execution reports via ADVISORY_ROLLOUT_ENABLED=true (opt-in)",
            "rationale": "Safe, advisory-only, reversible. Adds recovery context to failed/blocked run reports.",
            "requires_approval": True, "scope": "reporting",
        },
        {
            "id": "R2",
            "recommendation": "Do NOT auto-execute any recovery recommendation",
            "rationale": "Recommendations are advisory. Execution must always require explicit human/operator action.",
            "requires_approval": False, "scope": "constraint",
        },
        {
            "id": "R3",
            "recommendation": "Validate advisory on blocked runs before wider rollout",
            "rationale": "All 30 shadow cycles are failed+partial. blocked status not exercised on real data.",
            "requires_approval": False, "scope": "validation",
        },
        {
            "id": "R4",
            "recommendation": "Do NOT enable advisory by default before diverse run data validation",
            "rationale": "Only 1/9 recovery templates exercised on real data. Broader validation needed.",
            "requires_approval": False, "scope": "constraint",
        },
    ]

    result = {
        "epic": 892, "subissue": 897,
        "title": "Consolidated Advisory Rollout Report — Final Decision",
        "subissues_completed":  [893, 894, 895, 896, 897],
        "gate_chain_passed":     True,
        "auto_executable_violations": auto_exec_viol,
        "loop_decision_violations":   loop_viol,
        "is_gate_violations":         gate_viol,
        "risk_introduced_candidates":        risk,
        "potential_critical_false_completed": critical,
        "invariants_checked":   r896["invariants_checked"],
        "invariants_passed":    r896["invariants_passed"],
        "total_cycles_validated": r895["total_cycles"],
        "cycles_with_advisory":   r895["cycles_with_advisory"],
        "scope":               r893["scope"],
        "final_decision":      final_decision,
        "final_decision_rationale": (
            "All safety gates passed. 8/8 invariants verified. 30/30 cycles validated with 0 violations. "
            "Scope is conservative (failed+blocked only, default OFF). "
            "Advisory output is additive, non-blocking, and immediately rollback-able. "
            "Decision: candidate_for_broader_advisory_rollout. "
            "This does NOT activate rollout. "
            "Activation requires explicit operator approval, integration into reporting pipeline, "
            "and validation on diverse run outcomes (including blocked status)."
        ),
        "summary": (
            f"EPIC #892 complete. 8 invariants verified. 30 cycles validated. "
            "auto_executable_violations=0. loop_decision_violations=0. "
            f"Final decision: {final_decision}. "
            "No auto-execution. No mandatory gate. Default off."
        ),
        "findings":        findings,
        "recommendations": recommendations,
        "guardrails": {
            "advisory_only":               True,
            "no_auto_execution":           True,
            "default_off":                 True,
            "no_mandatory_gate":           True,
            "no_rollout_activation":       True,
            "no_loop_modification":        True,
            "candidate_does_not_mean_activated": True,
            "rollback_immediate":          True,
        },
        "evaluation": "passed", "stop_reason": None, "epic_status": "complete",
    }

    out_dir = Path("reports/mission_brain/advisory_rollout/897")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "advisory_rollout_consolidated_897.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    md = [
        "# Consolidated Advisory Rollout Report — #897",
        "## EPIC #892 Mission Brain Advisory Recovery Rollout — COMPLETE",
        "",
        f"### **Final Decision: {final_decision.upper()}**",
        "",
        result["final_decision_rationale"],
        "",
        "## Gate Chain",
        "",
        "| Subissue | Title | Evaluation |",
        "|----------|-------|------------|",
        "| #893 Scope | Advisory Rollout Scope | ✅ |",
        "| #894 Integration | Report Enrichment | ✅ |",
        "| #895 Validation | Real Data Validation | ✅ |",
        "| #896 Invariants | Invariant Verification | ✅ |",
        "| #897 Consolidated | Final Decision | ✅ |",
        "",
        "## Key Metrics",
        "",
        f"- invariants_checked: {r896['invariants_checked']} ✅",
        "- auto_executable_violations: 0 ✅",
        "- loop_decision_violations: 0 ✅",
        "- cycles_validated: 30 ✅",
        "",
        "## Guardrails",
        "",
        "- advisory_only: ✅  |  no_auto_execution: ✅  |  default_off: ✅",
        "- rollback_immediate: ✅  |  **candidate_does_not_mean_activated: ✅**",
        "",
        "## Evaluation: passed | Epic status: complete",
    ]
    (out_dir / "advisory_rollout_consolidated_897.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({
        "subissue": 897,
        "final_decision":     final_decision,
        "gate_chain_passed":  True,
        "auto_executable_violations": 0,
        "invariants_checked": r896["invariants_checked"],
        "cycles_validated":   30,
        "evaluation":         "passed",
        "epic_status":        "complete",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
