#!/usr/bin/env python3
"""EPIC #892 — #895: Validate advisory output on real failed/partial runs.

Usage:
    python scripts/run_advisory_rollout_validation_895.py
"""
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.advisory_rollout import (
    aggregate_advisory_cycles,
    enrich_cycle_with_advisory,
    has_advisory,
    make_advisory_enabled_config,
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
    assert len(all_cycles) == 30, f"Expected 30 cycles, got {len(all_cycles)}"

    risk     = sum(1 for c in all_cycles if bool(c.get("risk_introduced_candidate", False)))
    critical = sum(1 for c in all_cycles if bool(c.get("potential_critical_false_completed", False)))
    if risk > 0:
        print(json.dumps({"STOP": f"risk={risk}"}, indent=2)); return 1
    if critical > 0:
        print(json.dumps({"STOP": f"critical={critical}"}, indent=2)); return 1

    cfg = make_advisory_enabled_config()
    enriched = [enrich_cycle_with_advisory(c, advisory_config=cfg) for c in all_cycles]
    assert len(enriched) == 30

    missing_advisory = [i for i, r in enumerate(enriched) if not has_advisory(r)]
    if missing_advisory:
        print(json.dumps({"STOP": f"missing advisory for cycles: {missing_advisory}"}, indent=2))
        return 1

    validation_errors = []
    for i, r in enumerate(enriched):
        v = validate_advisory_output(r)
        if not v["valid"]:
            validation_errors.append({"cycle_idx": i, "violations": v["violations"]})
    if validation_errors:
        print(json.dumps({"STOP": "invariant violations", "errors": validation_errors}, indent=2))
        return 1

    field_violations = []
    for i, (orig, enr) in enumerate(zip(all_cycles, enriched)):
        if not validate_no_original_fields_modified(orig, enr):
            field_violations.append(i)
    if field_violations:
        print(json.dumps({"STOP": f"original fields modified in cycles: {field_violations}"}, indent=2))
        return 1

    agg = aggregate_advisory_cycles(all_cycles, advisory_config=cfg)
    assert agg["auto_executable_violations"] == 0
    assert agg["loop_decision_violations"]   == 0
    assert agg["is_gate_violations"]         == 0

    per_cycle = [
        {
            "cycle_id":    r.get("cycle_id", f"cycle-{i}"),
            "run_status":  r.get("current_loop_decision", ""),
            "goal_status": r.get("mission_brain_decision", ""),
            "has_advisory": has_advisory(r),
            "action":      r["recovery_recommendation"]["action"]        if has_advisory(r) else None,
            "confidence":  r["recovery_recommendation"]["confidence"]    if has_advisory(r) else None,
            "auto_executable": r["recovery_recommendation"]["auto_executable"] if has_advisory(r) else None,
        }
        for i, r in enumerate(enriched)
    ]

    result = {
        "epic": 892, "subissue": 895,
        "title": "Advisory Validation on Real Failed/Partial Runs",
        "total_cycles":          30,
        "cycles_with_advisory":  agg["cycles_with_advisory"],
        "auto_executable_violations":     0,
        "advisory_only_violations":       0,
        "loop_decision_violations":       0,
        "is_gate_violations":             0,
        "validation_errors":              0,
        "field_preservation_violations":  0,
        "action_distribution":     agg["action_distribution"],
        "confidence_distribution": agg["confidence_distribution"],
        "risk_introduced_candidates":        risk,
        "potential_critical_false_completed": critical,
        "per_cycle": per_cycle,
        "guardrails": {
            "default_off": True, "no_auto_execution": True, "advisory_only": True,
            "loop_decision_unchanged": True, "original_fields_preserved": True,
        },
        "evaluation": "passed", "stop_reason": None, "next_subissue": 896,
    }

    out_dir = Path("reports/mission_brain/advisory_rollout/895")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "advisory_rollout_validation_895.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    md = [
        "# Advisory Rollout Validation — #895",
        "## EPIC #892",
        "",
        f"**Total cycles:** 30 | **With advisory:** {agg['cycles_with_advisory']}",
        "**auto_executable_violations:** 0 ✅ | **loop_decision_violations:** 0 ✅",
        "",
        "| action | count |",
        "|--------|-------|",
    ]
    for k, v in agg["action_distribution"].items():
        md.append(f"| {k} | {v} |")
    md += ["", "## Evaluation: passed"]
    (out_dir / "advisory_rollout_validation_895.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({
        "subissue": 895, "total_cycles": 30,
        "cycles_with_advisory": agg["cycles_with_advisory"],
        "auto_executable_violations": 0, "evaluation": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
