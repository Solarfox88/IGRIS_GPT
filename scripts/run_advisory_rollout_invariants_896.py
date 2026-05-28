#!/usr/bin/env python3
"""EPIC #892 — #896: Verify rollback/default-off/no-auto-execution invariants (rewritten).

Usage:
    python scripts/run_advisory_rollout_invariants_896.py
"""
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.advisory_rollout import (
    DEFAULT_ADVISORY_CONFIG,
    aggregate_advisory_cycles,
    enrich_cycle_with_advisory,
    enrich_report_with_advisory,
    has_advisory,
    make_advisory_enabled_config,
    rollback,
    should_emit_for_run,
    validate_advisory_output,
    validate_no_original_fields_modified,
)


def _load(rel: str) -> list:
    return json.loads(Path(rel).read_text(encoding="utf-8"))


def main() -> int:
    all_cycles = (
        _load("reports/mission_brain/shadow_monitoring/847/shadow_batch1_cycles_847.json")
        + _load("reports/mission_brain/shadow_monitoring/849/shadow_batch2_cycles_849.json")
        + _load("reports/mission_brain/shadow_monitoring/859/extended_shadow_batch1_cycles_859.json")
        + _load("reports/mission_brain/shadow_monitoring/860/extended_shadow_batch2_cycles_860.json")
    )
    assert len(all_cycles) == 30

    cfg = make_advisory_enabled_config()
    inv_results = []

    # INV-1: Default OFF
    enriched_default = [enrich_cycle_with_advisory(c, advisory_config=DEFAULT_ADVISORY_CONFIG) for c in all_cycles]
    cnt_default = sum(1 for r in enriched_default if has_advisory(r))
    inv1 = cnt_default == 0
    inv_results.append({"id": "INV-1", "name": "Default OFF",
        "description": "No advisory with DEFAULT_ADVISORY_CONFIG (enabled=False)",
        "passed": inv1, "detail": f"cycles_with_advisory={cnt_default}/30"})
    if not inv1:
        print(json.dumps({"STOP": "INV-1 failed: default config should not emit advisory"}, indent=2))
        return 1

    # INV-2: Enabled → all in-scope cycles have advisory (all 30 are failed+partial)
    enriched_enabled = [enrich_cycle_with_advisory(c, advisory_config=cfg) for c in all_cycles]
    cnt_enabled = sum(1 for r in enriched_enabled if has_advisory(r))
    inv2 = cnt_enabled == 30
    inv_results.append({"id": "INV-2", "name": "Enabled → all in-scope cycles get advisory",
        "description": "With advisory enabled, all 30 failed+partial cycles get advisory",
        "passed": inv2, "detail": f"cycles_with_advisory={cnt_enabled}/30"})
    if not inv2:
        print(json.dumps({"STOP": f"INV-2 failed: expected 30, got {cnt_enabled}"}, indent=2))
        return 1

    # INV-3: Rollback removes advisory and bridge_diagnostics
    rolled_back = [rollback(r) for r in enriched_enabled]
    rb_adv   = sum(1 for r in rolled_back if has_advisory(r))
    rb_bridge = sum(1 for r in rolled_back if "bridge_diagnostics" in r)
    inv3 = rb_adv == 0 and rb_bridge == 0
    inv_results.append({"id": "INV-3", "name": "Rollback removes advisory and bridge_diagnostics",
        "description": "After rollback(), neither recovery_recommendation nor bridge_diagnostics remain",
        "passed": inv3, "detail": f"advisory_remaining={rb_adv}, bridge_remaining={rb_bridge}"})
    if not inv3:
        print(json.dumps({"STOP": "INV-3 failed: rollback incomplete"}, indent=2))
        return 1

    # INV-4: No auto-execution violations
    auto_exec_viol = sum(
        1 for r in enriched_enabled
        if has_advisory(r) and r["recovery_recommendation"].get("auto_executable") is not False
    )
    inv4 = auto_exec_viol == 0
    inv_results.append({"id": "INV-4", "name": "No auto-execution",
        "description": "auto_executable=False for all advisory recommendations",
        "passed": inv4, "detail": f"auto_exec_violations={auto_exec_viol}"})
    if not inv4:
        print(json.dumps({"STOP": f"INV-4 failed: auto_exec_violations={auto_exec_viol}"}, indent=2))
        return 1

    # INV-5: Loop decision unchanged (affects_loop_decision=False)
    loop_viol = sum(
        1 for r in enriched_enabled
        if "bridge_diagnostics" in r
        and r["bridge_diagnostics"].get("affects_loop_decision") is not False
    )
    inv5 = loop_viol == 0
    inv_results.append({"id": "INV-5", "name": "Loop decision unchanged",
        "description": "bridge_diagnostics.affects_loop_decision=False for all",
        "passed": inv5, "detail": f"loop_decision_violations={loop_viol}"})
    if not inv5:
        print(json.dumps({"STOP": f"INV-5 failed: loop_decision_violations={loop_viol}"}, indent=2))
        return 1

    # INV-6: is_gate=False always
    gate_viol = sum(
        1 for r in enriched_enabled
        if "bridge_diagnostics" in r
        and r["bridge_diagnostics"].get("is_gate") is not False
    )
    inv6 = gate_viol == 0
    inv_results.append({"id": "INV-6", "name": "Not a gate",
        "description": "bridge_diagnostics.is_gate=False for all",
        "passed": inv6, "detail": f"is_gate_violations={gate_viol}"})
    if not inv6:
        print(json.dumps({"STOP": f"INV-6 failed: is_gate_violations={gate_viol}"}, indent=2))
        return 1

    # INV-7: Original fields preserved
    field_viol = sum(
        1 for orig, enr in zip(all_cycles, enriched_enabled)
        if not validate_no_original_fields_modified(orig, enr)
    )
    inv7 = field_viol == 0
    inv_results.append({"id": "INV-7", "name": "Original fields preserved",
        "description": "Enrichment is additive — no existing fields modified",
        "passed": inv7, "detail": f"field_violation_count={field_viol}"})
    if not inv7:
        print(json.dumps({"STOP": f"INV-7 failed: field_violation_count={field_viol}"}, indent=2))
        return 1

    # INV-8: Scope filter — passed+completed → no advisory (even when enabled)
    base_pc = {"run_id": "pc-test", "outcome": "passed"}
    r_pc = enrich_report_with_advisory(base_pc, run_status="passed", goal_status="completed", advisory_config=cfg)
    inv8 = not has_advisory(r_pc)
    inv_results.append({"id": "INV-8", "name": "Scope filter: passed+completed excluded",
        "description": "passed+completed runs do not receive advisory (no recovery needed)",
        "passed": inv8, "detail": f"has_advisory={has_advisory(r_pc)} (expected False)"})
    if not inv8:
        print(json.dumps({"STOP": "INV-8 failed: passed+completed should not get advisory"}, indent=2))
        return 1

    all_passed = all(i["passed"] for i in inv_results)

    result = {
        "epic": 892, "subissue": 896,
        "title": "Advisory Rollout Invariant Verification",
        "invariants_checked":  len(inv_results),
        "invariants_passed":   sum(1 for i in inv_results if i["passed"]),
        "all_invariants_passed": all_passed,
        "auto_executable_violations":  0,
        "loop_decision_violations":    0,
        "is_gate_violations":          0,
        "invariant_results": inv_results,
        "guardrails": {
            "default_off":        True,
            "no_auto_execution":  True,
            "advisory_only":      True,
            "loop_decision_unchanged":   True,
            "rollback_immediate":        True,
            "original_fields_preserved": True,
            "scope_filter_active":       True,
        },
        "evaluation": "passed", "stop_reason": None, "next_subissue": 897,
    }

    out_dir = Path("reports/mission_brain/advisory_rollout/896")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "advisory_rollout_invariants_896.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    md = [
        "# Advisory Rollout Invariant Verification — #896",
        "## EPIC #892",
        "",
        "| ID | Invariant | Passed |",
        "|----|-----------|--------|",
    ]
    for inv in inv_results:
        md.append(f"| {inv['id']} | {inv['name']} | {'✅' if inv['passed'] else '❌'} |")
    md += ["", "## Evaluation: passed"]
    (out_dir / "advisory_rollout_invariants_896.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({
        "subissue": 896,
        "invariants_checked": len(inv_results),
        "all_invariants_passed": all_passed,
        "evaluation": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
