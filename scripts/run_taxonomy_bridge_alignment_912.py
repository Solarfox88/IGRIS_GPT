#!/usr/bin/env python3
"""EPIC #910 — #912: Validate taxonomy_bridge alignment module.

Tests all 9 bridge combined_statuses resolve to a taxonomy template via alignment.
Tests all advisory invariants hold (auto_executable=False, advisory_only=True) for
all aligned templates. Tests reachability predicates.

Writes: reports/mission_brain/taxonomy_bridge/912/taxonomy_bridge_alignment_912.json

Usage:
    python scripts/run_taxonomy_bridge_alignment_912.py
"""
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.advisory_rollout import validate_advisory_output, has_advisory
from igris.agent.mission.selected_advisory import (
    enrich_cycle_selected,
    make_selected_aligned_activation_config,
    make_selected_aligned_monitoring_config,
)
from igris.agent.mission.taxonomy_bridge import (
    ALL_TAXONOMY_TEMPLATES,
    BRIDGE_TO_TAXONOMY_ALIGNMENT,
    NEWLY_REACHABLE_IN_SCOPE_TEMPLATES,
    POST_ALIGNMENT_REACHABLE,
    PRE_ALIGNMENT_REACHABLE,
    compute_alignment_coverage,
    get_aligned_template,
    get_aligned_template_key,
    validate_alignment_invariants,
)
from igris.agent.mission.status_bridge import COMBINED_STATUSES, bridge as _bridge


def _gate_fail(msg: str, **kw) -> int:
    print(json.dumps({"STOP": msg, **kw}, indent=2))
    return 1


def main() -> int:
    act_cfg = make_selected_aligned_activation_config(include_blocked=True)
    mon_cfg = make_selected_aligned_monitoring_config(include_blocked=True)

    # --- Invariant validation ---
    violations = validate_alignment_invariants()
    if violations:
        return _gate_fail("invariant violations", violations=violations)

    # --- All bridge outputs resolve to a template ---
    template_resolution = {}
    resolve_errors = []
    for cs in sorted(COMBINED_STATUSES):
        tmpl = get_aligned_template(cs)
        key  = get_aligned_template_key(cs)
        if tmpl is None:
            resolve_errors.append(f"No template for bridge output: {cs}")
        else:
            # Verify advisory invariants on each template
            if tmpl.get("auto_executable") is not False:
                resolve_errors.append(f"auto_executable!=False for {cs}")
            if tmpl.get("advisory_only") is not True:
                resolve_errors.append(f"advisory_only!=True for {cs}")
        template_resolution[cs] = {
            "taxonomy_key": key,
            "action": tmpl["action"] if tmpl else "NONE",
            "confidence": tmpl["confidence"] if tmpl else "NONE",
        }
    if resolve_errors:
        return _gate_fail("template resolution errors", errors=resolve_errors)

    # --- Reachability: test synthetic cycles for each in-scope bridge output ---
    in_scope_test_cycles = [
        # Pre-alignment: already reachable
        {"cycle_id": "t-failed-partial", "current_loop_decision": "failed",
         "mission_brain_decision": "partial", "report_type": "diagnostic"},
        {"cycle_id": "t-failed-failed", "current_loop_decision": "failed",
         "mission_brain_decision": "failed", "report_type": "diagnostic"},
        {"cycle_id": "t-failed-unknown", "current_loop_decision": "failed",
         "mission_brain_decision": "unknown", "report_type": "diagnostic"},
        {"cycle_id": "t-blocked-partial", "current_loop_decision": "blocked",
         "mission_brain_decision": "partial", "report_type": "diagnostic"},
        # Newly reachable after alignment
        {"cycle_id": "t-blocked-failed", "current_loop_decision": "blocked",
         "mission_brain_decision": "failed", "report_type": "diagnostic"},
        {"cycle_id": "t-failed-completed", "current_loop_decision": "failed",
         "mission_brain_decision": "completed", "report_type": "diagnostic"},
        {"cycle_id": "t-blocked-completed", "current_loop_decision": "blocked",
         "mission_brain_decision": "completed", "report_type": "diagnostic"},
    ]

    enriched = [enrich_cycle_selected(c, config=act_cfg) for c in in_scope_test_cycles]
    missing_advisory = [c["cycle_id"] for c, r in zip(in_scope_test_cycles, enriched)
                        if not has_advisory(r)]
    if missing_advisory:
        return _gate_fail("in-scope cycles missing advisory", cycles=missing_advisory)

    inv_errors = []
    for c, r in zip(in_scope_test_cycles, enriched):
        if not has_advisory(r):
            continue
        v = validate_advisory_output(r)
        if not v["valid"]:
            inv_errors.append({"cycle_id": c["cycle_id"], "violations": v["violations"]})
    if inv_errors:
        return _gate_fail("invariant violations in enriched cycles", errors=inv_errors)

    # --- Newly reachable templates exercised ---
    exercised_templates = {
        r.get("_advisory_template_used") for r in enriched if has_advisory(r)
    }
    for new_tmpl in NEWLY_REACHABLE_IN_SCOPE_TEMPLATES:
        if new_tmpl not in exercised_templates:
            return _gate_fail(f"newly reachable template not exercised: {new_tmpl}")

    # --- Auto-executable and loop-decision invariants ---
    auto_exec_viol = sum(
        1 for r in enriched
        if has_advisory(r) and r["recovery_recommendation"].get("auto_executable") is not False
    )
    loop_viol = sum(
        1 for r in enriched
        if r.get("bridge_diagnostics", {}).get("affects_loop_decision") is not False
    )
    is_gate_viol = sum(
        1 for r in enriched
        if r.get("bridge_diagnostics", {}).get("is_gate") is not False
    )
    if auto_exec_viol > 0: return _gate_fail(f"auto_exec_violations={auto_exec_viol}")
    if loop_viol > 0:      return _gate_fail(f"loop_decision_violations={loop_viol}")
    if is_gate_viol > 0:   return _gate_fail(f"is_gate_violations={is_gate_viol}")

    # --- Excluded (passed+completed) still does NOT get advisory ---
    excl = [
        {"cycle_id": "excl-passed-completed", "current_loop_decision": "passed",
         "mission_brain_decision": "completed", "report_type": "diagnostic"},
    ]
    excl_enriched = [enrich_cycle_selected(c, config=act_cfg) for c in excl]
    excl_got = sum(1 for r in excl_enriched if has_advisory(r))
    if excl_got > 0:
        return _gate_fail(f"advisory surfaced on excluded (passed+completed): {excl_got}")

    # --- Monitoring mode silent ---
    mon_enriched = [enrich_cycle_selected(c, config=mon_cfg) for c in in_scope_test_cycles]
    mon_surfaced = sum(1 for r in mon_enriched if has_advisory(r))
    if mon_surfaced > 0:
        return _gate_fail(f"monitoring mode surfaced advisory: {mon_surfaced}")

    # --- Template-by-template detail ---
    per_cycle = [
        {
            "cycle_id": c["cycle_id"],
            "run_status": c["current_loop_decision"],
            "goal_status": c["mission_brain_decision"],
            "bridge_combined": _bridge(
                c["current_loop_decision"], c["mission_brain_decision"]
            )["combined_status"],
            "template_used": r.get("_advisory_template_used", "none"),
            "action": r.get("recovery_recommendation", {}).get("action", "none"),
            "auto_executable": r.get("recovery_recommendation", {}).get("auto_executable"),
        }
        for c, r in zip(in_scope_test_cycles, enriched)
    ]

    cov = compute_alignment_coverage()

    result = {
        "epic": 910, "subissue": 912,
        "title": "Taxonomy-Bridge Alignment Module Validation",
        "template_resolution": template_resolution,
        "coverage": cov,
        "in_scope_cycles_tested": len(in_scope_test_cycles),
        "all_in_scope_got_advisory": len(missing_advisory) == 0,
        "exercised_templates": sorted(exercised_templates - {"fallback", "unknown", None}),
        "newly_reachable_exercised": sorted(NEWLY_REACHABLE_IN_SCOPE_TEMPLATES),
        "auto_executable_violations": 0,
        "loop_decision_violations": 0,
        "is_gate_violations": 0,
        "excluded_got_advisory": excl_got,
        "monitoring_mode_surfaced": mon_surfaced,
        "invariant_violations": 0,
        "per_cycle": per_cycle,
        "evaluation": "passed", "stop_reason": None, "next_subissue": 913,
    }

    out = Path("reports/mission_brain/taxonomy_bridge/912")
    out.mkdir(parents=True, exist_ok=True)
    (out / "taxonomy_bridge_alignment_912.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )

    print(json.dumps({
        "subissue": 912,
        "all_bridge_outputs_resolve": True,
        "in_scope_cycles_all_got_advisory": True,
        "newly_reachable_exercised": sorted(NEWLY_REACHABLE_IN_SCOPE_TEMPLATES),
        "auto_executable_violations": 0,
        "excluded_got_advisory": 0,
        "monitoring_silent": True,
        "invariant_violations": 0,
        "evaluation": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
