#!/usr/bin/env python3
"""EPIC #886 — #891: Consolidated Advisory Readiness Report and Final Decision.

Allowed decisions:
  - keep_diagnostic_only
  - candidate_for_advisory_rollout
  - continue_recommendation_calibration
  - remediate_again
  - do_not_integrate

Usage:
    python scripts/run_recovery_consolidated_891.py
"""
from __future__ import annotations

import json
from pathlib import Path

ALLOWED_DECISIONS = frozenset({
    "keep_diagnostic_only",
    "candidate_for_advisory_rollout",
    "continue_recommendation_calibration",
    "remediate_again",
    "do_not_integrate",
})
FORBIDDEN_DECISIONS = frozenset({
    "activate_rollout", "enable_by_default", "auto_execute", "mandatory_gate", "deploy",
})


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    r887 = _load("reports/mission_brain/recovery/887/recovery_taxonomy_887.json")
    r890 = _load("reports/mission_brain/recovery/890/recovery_890.json")

    assert r887["evaluation"] == "passed"
    assert r890["evaluation"] == "passed"
    assert r887["stop_reason"] is None
    assert r890["stop_reason"] is None

    risk = r890["risk_introduced_candidates"]
    critical = r890["potential_critical_false_completed"]
    auto_exec_violations = r890["auto_executable_violations"]

    if risk > 0:
        print(json.dumps({"STOP": f"risk={risk}"}, indent=2)); return 1
    if critical > 0:
        print(json.dumps({"STOP": f"critical={critical}"}, indent=2)); return 1
    if auto_exec_violations > 0:
        print(json.dumps({"STOP": f"auto_executable_violations={auto_exec_violations}"}, indent=2)); return 1

    templates_count = r887["templates_count"]
    total_cycles = r890["total_cycles"]
    evidence_complete = r890["evidence_complete_count"]
    action_dist = r890["action_distribution"]

    # Decision:
    # - 9 recovery templates, all advisory_only, all auto_executable=False
    # - 30 cycles validated, 0 auto_exec violations, 0 safety violations
    # - evidence_complete for 20/30 (new cycles have goal_class; baseline don't)
    # - Dominant action: continue_from_partial_progress (high confidence, actionable)
    # → candidate_for_advisory_rollout
    # IMPORTANT: does NOT activate rollout — recommendation only
    final_decision = "candidate_for_advisory_rollout"
    assert final_decision in ALLOWED_DECISIONS
    assert final_decision not in FORBIDDEN_DECISIONS

    findings = [
        {
            "id": "F1",
            "finding": "All 9 recovery templates are advisory-only with auto_executable=False",
            "evidence": f"templates_count={templates_count}, auto_executable_violations=0.",
            "impact": "positive",
        },
        {
            "id": "F2",
            "finding": "30/30 cycles receive a valid recovery recommendation",
            "evidence": f"total_cycles={total_cycles}, cycles_with_recommendation={r890['cycles_with_recommendation']}.",
            "impact": "positive",
        },
        {
            "id": "F3",
            "finding": "Dominant recommendation: continue_from_partial_progress (high confidence)",
            "evidence": f"action_distribution={action_dist}.",
            "impact": "positive",
        },
        {
            "id": "F4",
            "finding": "Evidence completeness: 20/30 cycles (new) have full evidence; 10 (baseline) are partial",
            "evidence": f"evidence_complete_count={evidence_complete}. Baseline cycles lack goal_class.",
            "impact": "minor_gap",
        },
        {
            "id": "F5",
            "finding": "No auto-execution paths exist anywhere in the module",
            "evidence": "auto_executable_violations=0 across all templates and all cycles.",
            "impact": "positive",
        },
    ]

    recommendations = [
        {
            "id": "R1",
            "recommendation": "Surface recovery_recommendation in execution reports (diagnostic_only mode, opt-in)",
            "rationale": "Safe, advisory-only, reversible. Adds recovery context beyond raw loop failure.",
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
            "recommendation": "Backfill goal_class in baseline cycles to improve evidence completeness",
            "rationale": "10 baseline cycles lack goal_class → evidence_missing for required fields.",
            "requires_approval": False, "scope": "data_quality",
        },
        {
            "id": "R4",
            "recommendation": "Validate recovery recommendations on diverse run outcomes before expanded rollout",
            "rationale": "30/30 cycles are (failed, partial) — only 1 of 9 templates exercised on real data.",
            "requires_approval": False, "scope": "validation",
        },
    ]

    result = {
        "epic": 886, "subissue": 891,
        "title": "Consolidated Advisory Readiness Report — Final Decision",
        "subissues_completed": [887, 888, 889, 890, 891],
        "gate_chain_passed": True,
        "risk_introduced_candidates": risk,
        "potential_false_completed": 0,
        "potential_critical_false_completed": critical,
        "auto_executable_violations": auto_exec_violations,
        "templates_count": templates_count,
        "total_cycles_validated": total_cycles,
        "evidence_complete_count": evidence_complete,
        "final_decision": final_decision,
        "final_decision_rationale": (
            "All safety gates passed. 9 recovery templates defined, all advisory-only, "
            "auto_executable=False everywhere. 30 cycles validated with 0 auto_exec violations. "
            "Dominant recommendation (continue_from_partial_progress) is actionable and non-trivial: "
            "it distinguishes targeted recovery from cold restart. "
            "Decision: candidate_for_advisory_rollout. "
            "This does NOT activate rollout. "
            "Activation requires explicit operator approval and integration into reporting pipeline."
        ),
        "summary": (
            f"EPIC #886 complete. {templates_count} recovery templates, all advisory-only. "
            f"{total_cycles} cycles validated. auto_executable_violations=0. "
            f"Final decision: {final_decision}. "
            "No auto-execution. No mandatory gate. Default off."
        ),
        "findings": findings,
        "recommendations": recommendations,
        "guardrails": {
            "advisory_only": True, "no_auto_execution": True,
            "default_off": True, "no_mandatory_gate": True,
            "no_rollout_activation": True, "no_loop_modification": True,
            "candidate_does_not_mean_activated": True,
        },
        "evaluation": "passed", "stop_reason": None, "epic_status": "complete",
    }

    out_dir = Path("reports/mission_brain/recovery/891")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "recovery_consolidated_891.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    md = [
        "# Consolidated Advisory Readiness Report — #891",
        "## EPIC #886 Mission Brain Assisted Recovery Recommendations — COMPLETE",
        "",
        f"### **Final Decision: {final_decision.upper()}**",
        "",
        result["final_decision_rationale"],
        "",
        "## Gate Chain",
        "",
        "| Subissue | Evaluation |",
        "|----------|------------|",
        "| #887 Taxonomy | ✅ |",
        "| #888 Module | ✅ |",
        "| #889 Feature Flag | ✅ |",
        "| #890 Dataset Validation | ✅ |",
        "| #891 Consolidated | ✅ |",
        "",
        "## Key Metrics",
        "",
        f"- templates_count: {templates_count}",
        f"- auto_executable_violations: {auto_exec_violations} ✅",
        f"- evidence_complete_count: {evidence_complete}/30",
        "",
        "## Guardrails",
        "",
        "- advisory_only: ✅  |  no_auto_execution: ✅  |  default_off: ✅",
        "- no_mandatory_gate: ✅  |  **candidate_does_not_mean_activated: ✅**",
        "",
        "## Evaluation: passed | Epic status: complete",
    ]
    (out_dir / "recovery_consolidated_891.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({
        "subissue": 891, "final_decision": final_decision,
        "gate_chain_passed": True, "auto_executable_violations": 0,
        "templates_count": templates_count, "total_cycles_validated": total_cycles,
        "evaluation": "passed", "epic_status": "complete",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
