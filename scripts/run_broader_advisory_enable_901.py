#!/usr/bin/env python3
"""EPIC #898 — #901: Enable advisory enrichment for selected diagnostic reports behind flag.

Validates that with activation config (monitoring_only=False, include_blocked=True):
  - All failed shadow cycles receive advisory.
  - All synthetic blocked cycles receive advisory.
  - 0 auto_exec / loop / gate violations.
  - Original fields preserved (additive).
  - With monitoring_only=True: reports unchanged (advisory not surfaced).

Usage:
    python scripts/run_broader_advisory_enable_901.py
"""
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.broader_advisory import (
    DEFAULT_BROADER_CONFIG,
    aggregate_broader_cycles,
    enrich_cycle_broader,
    has_advisory as _has,
    make_broader_activation_config,
    make_broader_monitoring_config,
    make_synthetic_blocked_cycles,
)
from igris.agent.mission.advisory_rollout import validate_advisory_output, validate_no_original_fields_modified


def _load(rel: str) -> list:
    return json.loads(Path(rel).read_text(encoding="utf-8"))


def main() -> int:
    shadow = (
        _load("reports/mission_brain/shadow_monitoring/847/shadow_batch1_cycles_847.json")
        + _load("reports/mission_brain/shadow_monitoring/849/shadow_batch2_cycles_849.json")
        + _load("reports/mission_brain/shadow_monitoring/859/extended_shadow_batch1_cycles_859.json")
        + _load("reports/mission_brain/shadow_monitoring/860/extended_shadow_batch2_cycles_860.json")
    )
    assert len(shadow) == 30

    blocked = make_synthetic_blocked_cycles(n=10, goal_status="partial")
    all_cycles = shadow + blocked
    assert len(all_cycles) == 40

    act_cfg = make_broader_activation_config(include_blocked=True)  # emit mode
    mon_cfg = make_broader_monitoring_config(include_blocked=True)   # monitoring mode (silent)

    # --- With activation config: all in-scope cycles get advisory ---
    enriched = [enrich_cycle_broader(c, config=act_cfg) for c in all_cycles]

    # 30 shadow (failed+partial) + 10 synthetic (blocked+partial) → all 40 in scope
    missing = [i for i, r in enumerate(enriched) if not _has(r)]
    if missing:
        print(json.dumps({"STOP": f"missing advisory for cycles: {missing}"}, indent=2))
        return 1

    # Validate invariants
    inv_errors = []
    for i, r in enumerate(enriched):
        v = validate_advisory_output(r)
        if not v["valid"]:
            inv_errors.append({"idx": i, "violations": v["violations"]})
    if inv_errors:
        print(json.dumps({"STOP": "invariant violations", "errors": inv_errors}, indent=2))
        return 1

    # Original fields preserved
    field_viol = sum(
        1 for orig, enr in zip(all_cycles, enriched)
        if not validate_no_original_fields_modified(orig, enr)
    )
    if field_viol > 0:
        print(json.dumps({"STOP": f"original fields modified: {field_viol} cycles"}, indent=2))
        return 1

    # Aggregate stats
    agg = aggregate_broader_cycles(all_cycles, config=act_cfg)
    assert agg["auto_executable_violations"] == 0
    assert agg["loop_decision_violations"]   == 0
    assert agg["is_gate_violations"]         == 0

    # --- With monitoring_only config: reports unchanged (advisory NOT surfaced) ---
    mon_enriched = [enrich_cycle_broader(c, config=mon_cfg) for c in all_cycles]
    surfaced_in_monitoring = sum(1 for r in mon_enriched if _has(r))
    if surfaced_in_monitoring > 0:
        print(json.dumps({"STOP": f"advisory surfaced in monitoring mode: {surfaced_in_monitoring}"}, indent=2))
        return 1

    # --- With default config: nothing surfaced ---
    default_enriched = [enrich_cycle_broader(c, config=DEFAULT_BROADER_CONFIG) for c in all_cycles]
    surfaced_default = sum(1 for r in default_enriched if _has(r))
    if surfaced_default > 0:
        print(json.dumps({"STOP": f"advisory surfaced with default config: {surfaced_default}"}, indent=2))
        return 1

    per_cycle = [
        {
            "cycle_id":    r.get("cycle_id", f"cycle-{i}"),
            "run_status":  r.get("current_loop_decision", ""),
            "action":      r["recovery_recommendation"]["action"],
            "auto_executable": r["recovery_recommendation"]["auto_executable"],
        }
        for i, r in enumerate(enriched)
    ]

    result = {
        "epic": 898, "subissue": 901,
        "title": "Enable Advisory Enrichment for Selected Diagnostic Reports",
        "total_cycles":          40,
        "shadow_cycles":         30,
        "synthetic_blocked":     10,
        "cycles_with_advisory":  agg["cycles_with_advisory"],
        "auto_executable_violations": 0,
        "loop_decision_violations":   0,
        "is_gate_violations":         0,
        "field_preservation_violations": 0,
        "monitoring_mode_silent":  surfaced_in_monitoring == 0,
        "default_mode_silent":     surfaced_default == 0,
        "action_distribution":    agg["action_distribution"],
        "per_cycle": per_cycle,
        "guardrails": {
            "default_off": True, "no_auto_execution": True, "advisory_only": True,
            "loop_decision_unchanged": True, "monitoring_mode_does_not_surface": True,
            "original_fields_preserved": True,
        },
        "evaluation": "passed", "stop_reason": None, "next_subissue": 902,
    }

    out = Path("reports/mission_brain/broader_advisory/901")
    out.mkdir(parents=True, exist_ok=True)
    (out / "broader_advisory_enable_901.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    md = [
        "# Advisory Enrichment Enabled — #901",
        "## EPIC #898",
        "",
        "**Total cycles:** 40 (30 shadow + 10 synthetic blocked)",
        f"**With advisory (activation mode):** {agg['cycles_with_advisory']} ✅",
        "**Monitoring mode silent:** True ✅ | **Default mode silent:** True ✅",
        "**auto_exec_violations:** 0 ✅ | **loop_violations:** 0 ✅",
        "",
        "| action | count |",
        "|--------|-------|",
    ]
    for k, v in agg["action_distribution"].items():
        md.append(f"| {k} | {v} |")
    md += ["", "## Evaluation: passed"]
    (out / "broader_advisory_enable_901.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({
        "subissue": 901,
        "total_cycles": 40,
        "cycles_with_advisory": agg["cycles_with_advisory"],
        "auto_executable_violations": 0,
        "monitoring_mode_silent": True,
        "evaluation": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
