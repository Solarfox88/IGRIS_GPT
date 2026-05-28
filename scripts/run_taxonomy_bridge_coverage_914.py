#!/usr/bin/env python3
"""EPIC #910 — #914: Template coverage comparison before vs after alignment.

Compares coverage using standard vs aligned configs:
  BEFORE (#904): 4 reachable in-scope templates
  AFTER  (#910): 6 reachable in-scope templates (+ blocked_no_goal_progress,
                  + anomaly_run_passed_goal_not_completed)

Documents remaining limitations:
  - run_passed_goal_partial: only from passed runs (excluded from advisory scope)
  - unknown_status: internal-fallback-only (no bridge output produces this key)
  - completed: excluded by scope (only from passed+completed)

Writes: reports/mission_brain/taxonomy_bridge/914/taxonomy_bridge_coverage_914.json

Usage:
    python scripts/run_taxonomy_bridge_coverage_914.py
"""
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.advisory_rollout import has_advisory, validate_advisory_output
from igris.agent.mission.selected_advisory import (
    compute_selected_metrics,
    enrich_cycle_selected,
    make_selected_activation_config,
    make_selected_aligned_activation_config,
    make_synthetic_blocked_cycles,
    make_synthetic_excluded_cycles,
    make_synthetic_fallback_cycles,
    make_synthetic_hard_failure_cycles,
    make_synthetic_insufficient_context_cycles,
)
from igris.agent.mission.taxonomy_bridge import (
    ALL_TAXONOMY_TEMPLATES,
    INTERNAL_FALLBACK_ONLY_TEMPLATES,
    POST_ALIGNMENT_REACHABLE,
    PRE_ALIGNMENT_REACHABLE,
    REACHABLE_OUTSIDE_SCOPE,
    compute_alignment_coverage,
)


def _load(rel: str) -> list:
    return json.loads(Path(rel).read_text(encoding="utf-8"))


def _gate_fail(msg: str, **kw) -> int:
    print(json.dumps({"STOP": msg, **kw}, indent=2))
    return 1


def main() -> int:
    # Load full dataset
    shadow = (
        _load("reports/mission_brain/shadow_monitoring/847/shadow_batch1_cycles_847.json")
        + _load("reports/mission_brain/shadow_monitoring/849/shadow_batch2_cycles_849.json")
        + _load("reports/mission_brain/shadow_monitoring/859/extended_shadow_batch1_cycles_859.json")
        + _load("reports/mission_brain/shadow_monitoring/860/extended_shadow_batch2_cycles_860.json")
    )
    for c in shadow:
        c.setdefault("report_type", "diagnostic")

    blocked   = make_synthetic_blocked_cycles(n=10, goal_status="partial")
    hard_fail = make_synthetic_hard_failure_cycles(n=10)
    insuf_ctx = make_synthetic_insufficient_context_cycles(n=10)
    fallback  = make_synthetic_fallback_cycles(n=5)   # blocked+failed
    excluded  = make_synthetic_excluded_cycles(n=5)

    in_scope = shadow + blocked + hard_fail + insuf_ctx + fallback
    all_cycles = in_scope + excluded

    # Additional anomaly cycles for #914 analysis
    anomaly_failed_compl = [
        {"cycle_id": f"anomaly-fc-{i}", "current_loop_decision": "failed",
         "mission_brain_decision": "completed", "report_type": "diagnostic",
         "synthetic": True}
        for i in range(5)
    ]
    anomaly_blocked_compl = [
        {"cycle_id": f"anomaly-bc-{i}", "current_loop_decision": "blocked",
         "mission_brain_decision": "completed", "report_type": "diagnostic",
         "synthetic": True}
        for i in range(5)
    ]
    extended = in_scope + anomaly_failed_compl + anomaly_blocked_compl  # 75 cycles

    # --- BEFORE alignment (standard config) ---
    standard_cfg = make_selected_activation_config(include_blocked=True)
    metrics_before = compute_selected_metrics(extended, config=standard_cfg)

    # --- AFTER alignment ---
    aligned_cfg = make_selected_aligned_activation_config(include_blocked=True)
    metrics_after = compute_selected_metrics(extended, config=aligned_cfg)

    # --- Safety checks ---
    if metrics_after["auto_executable_violations"] > 0:
        return _gate_fail(f"auto_exec_violations={metrics_after['auto_executable_violations']}")
    if metrics_after["loop_decision_violations"] > 0:
        return _gate_fail(f"loop_viol={metrics_after['loop_decision_violations']}")
    if metrics_after["is_gate_violations"] > 0:
        return _gate_fail(f"is_gate_viol={metrics_after['is_gate_violations']}")
    if metrics_after["potential_critical_false_completed"] > 0:
        return _gate_fail(f"false_completed={metrics_after['potential_critical_false_completed']}")
    if metrics_after["risk_introduced_candidates"] > 0:
        return _gate_fail(f"risk_introduced={metrics_after['risk_introduced_candidates']}")

    # --- Coverage improvement ---
    before_count = metrics_before["exercised_template_count"]
    after_count  = metrics_after["exercised_template_count"]
    if after_count <= before_count:
        return _gate_fail(f"alignment did not improve coverage: before={before_count} after={after_count}")

    # --- All pre-alignment templates still exercised ---
    for tmpl in PRE_ALIGNMENT_REACHABLE:
        if tmpl not in metrics_after.get("exercised_templates", []):
            return _gate_fail(f"pre-alignment template lost: {tmpl}")

    # --- Newly reachable templates exercised ---
    if "blocked_no_goal_progress" not in metrics_after.get("exercised_templates", []):
        return _gate_fail("blocked_no_goal_progress NOT exercised after alignment")
    if "anomaly_run_passed_goal_not_completed" not in metrics_after.get("exercised_templates", []):
        return _gate_fail("anomaly_run_passed_goal_not_completed NOT exercised after alignment")

    cov = compute_alignment_coverage()

    # --- Remaining limitations ---
    limitations = [
        {
            "template": "run_passed_goal_partial",
            "status": "excluded_from_scope",
            "reason": "Only reachable from passed+partial runs. Advisory scope excludes passed run_status.",
            "resolution": "N/A — scope boundary is intentional.",
        },
        {
            "template": "unknown_status",
            "status": "internal_fallback_only",
            "reason": "No bridge combined_status produces 'unknown_status'. Used only when bridge result is missing combined_status key.",
            "resolution": "N/A — internal edge case fallback.",
        },
        {
            "template": "completed",
            "status": "excluded_by_scope",
            "reason": "Only from passed+completed. Explicitly excluded by is_excluded_status().",
            "resolution": "N/A — correct exclusion.",
        },
    ]

    result = {
        "epic": 910, "subissue": 914,
        "title": "Template Coverage Comparison Before vs After Alignment",
        "dataset": {
            "shadow_cycles": len(shadow),
            "synthetic_in_scope": len(extended) - len(shadow),
            "total_extended": len(extended),
        },
        "before_alignment": {
            "exercised_template_count": before_count,
            "exercised_templates": metrics_before.get("exercised_templates", []),
            "action_distribution": metrics_before.get("action_distribution", {}),
        },
        "after_alignment": {
            "exercised_template_count": after_count,
            "exercised_templates": metrics_after.get("exercised_templates", []),
            "action_distribution": metrics_after.get("action_distribution", {}),
        },
        "improvement": {
            "templates_gained": after_count - before_count,
            "newly_exercised": [
                t for t in metrics_after.get("exercised_templates", [])
                if t not in metrics_before.get("exercised_templates", [])
            ],
        },
        "remaining_limitations": limitations,
        "taxonomy_coverage_summary": {
            "total_templates": 9,
            "reachable_in_scope_after": len(POST_ALIGNMENT_REACHABLE),
            "excluded_from_scope": sorted(REACHABLE_OUTSIDE_SCOPE),
            "internal_fallback_only": sorted(INTERNAL_FALLBACK_ONLY_TEMPLATES),
            "all_accounted": cov["all_taxonomy_templates_reachable"],
        },
        "mandatory_metrics": {
            "auto_executable_violations":        0,
            "loop_decision_violations":          0,
            "is_gate_violations":                0,
            "risk_introduced_candidates":        0,
            "potential_critical_false_completed": 0,
        },
        "evaluation": "passed", "stop_reason": None, "next_subissue": 915,
    }

    out = Path("reports/mission_brain/taxonomy_bridge/914")
    out.mkdir(parents=True, exist_ok=True)
    (out / "taxonomy_bridge_coverage_914.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )

    print(json.dumps({
        "subissue": 914,
        "before_exercised": before_count,
        "after_exercised": after_count,
        "templates_gained": after_count - before_count,
        "newly_exercised": [
            t for t in metrics_after.get("exercised_templates", [])
            if t not in metrics_before.get("exercised_templates", [])
        ],
        "auto_executable_violations": 0,
        "potential_critical_false_completed": 0,
        "evaluation": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
