#!/usr/bin/env python3
"""Mission Brain EPIC #880 — #882: Add bridge output to reports/logs in non-blocking mode.

Validates bridge_reporter module: default off, shadow no-emit, diagnostic emits,
additive, non-blocking, is_gate always False.

Usage:
    python scripts/run_bridge_report_enrichment_882.py
"""
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.bridge_config import DEFAULT_BRIDGE_CONFIG, make_diagnostic_config, make_shadow_config
from igris.agent.mission.bridge_reporter import (
    enrich_report, enrich_report_from_cycle, is_enriched,
    strip_bridge_diagnostics, validate_bridge_diagnostics,
)
from igris.agent.mission.status_bridge import COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS


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

    risk = sum(1 for c in all_cycles if bool(c.get("risk_introduced_candidate", False)))
    critical = sum(1 for c in all_cycles if bool(c.get("potential_critical_false_completed", False)))
    if risk > 0:
        print(json.dumps({"STOP": f"risk={risk}"}, indent=2)); return 1
    if critical > 0:
        print(json.dumps({"STOP": f"critical={critical}"}, indent=2)); return 1

    base_report = {"run_id": "test-001", "outcome": "failed", "score": 0.9}
    diag_cfg = make_diagnostic_config()

    # default config → no enrichment
    r1 = enrich_report(base_report, run_status="failed", goal_status="partial", config=DEFAULT_BRIDGE_CONFIG)
    assert r1 == base_report
    assert not is_enriched(r1)

    # shadow config → no enrichment
    r2 = enrich_report(base_report, run_status="failed", goal_status="partial", config=make_shadow_config())
    assert r2 == base_report

    # diagnostic config → enrichment
    r3 = enrich_report(base_report, run_status="failed", goal_status="partial", config=diag_cfg)
    assert is_enriched(r3)
    bd = r3["bridge_diagnostics"]
    assert bd["combined_status"] == COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS
    assert bd["is_gate"] is False
    assert bd["affects_loop_decision"] is False
    assert validate_bridge_diagnostics(bd)

    # original fields preserved
    for k, v in base_report.items():
        assert r3[k] == v

    # strip restores original
    assert strip_bridge_diagnostics(r3) == base_report

    # error resilience — None inputs still work
    r4 = enrich_report({"run_id": "x"}, run_status=None, goal_status=None, config=diag_cfg)
    assert is_enriched(r4)
    assert r4["bridge_diagnostics"]["is_gate"] is False

    # Enrich all 30 cycles
    enriched = [enrich_report_from_cycle(dict(c), c, config=diag_cfg) for c in all_cycles]
    assert len(enriched) == 30
    assert all(is_enriched(r) for r in enriched)

    combined_counts: dict = {}
    for r in enriched:
        cs = r["bridge_diagnostics"]["combined_status"]
        combined_counts[cs] = combined_counts.get(cs, 0) + 1

    gate_violations = [r for r in enriched if r["bridge_diagnostics"]["is_gate"]]
    loop_violations = [r for r in enriched if r["bridge_diagnostics"]["affects_loop_decision"]]
    assert not gate_violations
    assert not loop_violations

    result = {
        "epic": 880, "subissue": 882,
        "title": "Bridge Report Enrichment — Non-blocking Mode",
        "total_cycles_enriched": len(enriched),
        "combined_status_distribution": combined_counts,
        "is_gate_violations": 0,
        "affects_loop_decision_violations": 0,
        "validation_results": {
            "default_config_no_enrichment": True,
            "shadow_config_no_enrichment": True,
            "diagnostic_config_enriches": True,
            "original_fields_preserved": True,
            "strip_restores_original": True,
            "error_resilient": True,
            "is_gate_always_false": True,
            "affects_loop_decision_always_false": True,
        },
        "risk_introduced_candidates": risk,
        "potential_critical_false_completed": critical,
        "guardrails": {
            "additive_only": True, "non_blocking": True,
            "feature_flagged": True, "is_gate": False, "affects_loop_decision": False,
        },
        "evaluation": "passed", "stop_reason": None, "next_subissue": 883,
    }

    out_dir = Path("reports/mission_brain/rollout/882")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "bridge_report_enrichment_882.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    md = [
        "# Bridge Report Enrichment — #882",
        "## EPIC #880",
        "",
        f"**Cycles enriched:** {len(enriched)}",
        "",
        "| check | result |",
        "|-------|--------|",
    ]
    for k, v in result["validation_results"].items():
        md.append(f"| {k} | {'✅' if v else '❌'} |")
    md += ["", "## Evaluation: passed"]
    (out_dir / "bridge_report_enrichment_882.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({
        "subissue": 882, "total_cycles_enriched": len(enriched),
        "is_gate_violations": 0, "validation": "all passed", "evaluation": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
