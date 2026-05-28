#!/usr/bin/env python3
"""EPIC #898 — #900: Validate blocked-status advisory behavior.

Creates synthetic blocked cycles and validates that advisory recommendations
are correct, advisory-only, and non-executing.

Usage:
    python scripts/run_broader_advisory_blocked_900.py
"""
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.broader_advisory import (
    enrich_cycle_broader,
    has_advisory as _has_advisory,
    make_broader_activation_config,
    make_synthetic_blocked_cycles,
)
from igris.agent.mission.advisory_rollout import validate_advisory_output


def main() -> int:
    # 10 synthetic blocked+partial cycles (blocked status not in shadow data)
    blocked_cycles = make_synthetic_blocked_cycles(n=10, goal_status="partial")
    assert len(blocked_cycles) == 10

    cfg = make_broader_activation_config(include_blocked=True)
    assert cfg.include_blocked is True
    assert cfg.is_gate is False
    assert cfg.should_emit is True

    enriched = [enrich_cycle_broader(c, config=cfg) for c in blocked_cycles]

    # All 10 must have advisory
    missing = [i for i, r in enumerate(enriched) if not _has_advisory(r)]
    if missing:
        print(json.dumps({"STOP": f"missing advisory for synthetic blocked cycles: {missing}"}, indent=2))
        return 1

    # All must have action=escalate_blocked
    wrong_action = [
        {"idx": i, "action": r["recovery_recommendation"]["action"]}
        for i, r in enumerate(enriched)
        if r["recovery_recommendation"]["action"] != "escalate_blocked"
    ]
    if wrong_action:
        print(json.dumps({"STOP": "wrong action for blocked cycles", "cases": wrong_action}, indent=2))
        return 1

    # Validate all invariants
    violations = []
    for i, r in enumerate(enriched):
        v = validate_advisory_output(r)
        if not v["valid"]:
            violations.append({"idx": i, "violations": v["violations"]})
    if violations:
        print(json.dumps({"STOP": "invariant violations", "errors": violations}, indent=2))
        return 1

    # auto_executable=False for all
    auto_exec_viol = sum(
        1 for r in enriched if r["recovery_recommendation"].get("auto_executable") is not False
    )
    if auto_exec_viol > 0:
        print(json.dumps({"STOP": f"auto_exec_violations={auto_exec_viol}"}, indent=2))
        return 1

    # Loop decision unchanged
    loop_viol = sum(
        1 for r in enriched
        if r.get("bridge_diagnostics", {}).get("affects_loop_decision") is not False
    )
    if loop_viol > 0:
        print(json.dumps({"STOP": f"loop_decision_violations={loop_viol}"}, indent=2))
        return 1

    # Collect per-cycle detail
    per_cycle = [
        {
            "cycle_id":      r["cycle_id"],
            "run_status":    r["current_loop_decision"],
            "goal_status":   r["mission_brain_decision"],
            "combined_status": r.get("bridge_diagnostics", {}).get("combined_status", ""),
            "action":        r["recovery_recommendation"]["action"],
            "confidence":    r["recovery_recommendation"]["confidence"],
            "auto_executable": r["recovery_recommendation"]["auto_executable"],
        }
        for r in enriched
    ]

    result = {
        "epic": 898, "subissue": 900,
        "title": "Blocked-Status Advisory Validation",
        "total_synthetic_blocked": len(blocked_cycles),
        "cycles_with_advisory": len(enriched),
        "action_verified": "escalate_blocked",
        "all_action_correct": True,
        "auto_executable_violations": 0,
        "loop_decision_violations": 0,
        "invariant_violations": 0,
        "blocked_advisory_validated": True,
        "per_cycle": per_cycle,
        "guardrails": {
            "default_off": True, "no_auto_execution": True, "advisory_only": True,
            "loop_decision_unchanged": True, "blocked_validated": True,
        },
        "evaluation": "passed", "stop_reason": None, "next_subissue": 901,
    }

    out = Path("reports/mission_brain/broader_advisory/900")
    out.mkdir(parents=True, exist_ok=True)
    (out / "broader_advisory_blocked_900.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    md = [
        "# Blocked-Status Advisory Validation — #900",
        "## EPIC #898",
        "",
        f"**Synthetic blocked cycles:** 10 | **All with advisory:** True",
        "**Action verified:** escalate_blocked ✅ | **auto_exec_violations:** 0 ✅",
        "",
        "| cycle_id | combined_status | action | auto_executable |",
        "|----------|----------------|--------|-----------------|",
    ]
    for c in per_cycle:
        md.append(f"| {c['cycle_id']} | {c['combined_status']} | {c['action']} | {c['auto_executable']} |")
    md += ["", "## Evaluation: passed"]
    (out / "broader_advisory_blocked_900.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({
        "subissue": 900,
        "synthetic_blocked_cycles": 10,
        "action_verified": "escalate_blocked",
        "auto_executable_violations": 0,
        "blocked_advisory_validated": True,
        "evaluation": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
