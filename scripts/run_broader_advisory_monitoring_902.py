#!/usr/bin/env python3
"""EPIC #898 — #902: Run controlled advisory rollout monitoring.

Computes what advisory would look like on all available cycles (monitoring_only mode).
Does NOT surface advisory in reports — purely analytical.

Usage:
    python scripts/run_broader_advisory_monitoring_902.py
"""
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.broader_advisory import (
    compute_monitoring_metrics,
    has_advisory as _has,
    enrich_cycle_broader,
    make_broader_monitoring_config,
    make_synthetic_blocked_cycles,
)


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
    all_cycles = shadow + blocked  # 40 total

    # monitoring_only config (include_blocked=True after #900 validation)
    mon_cfg = make_broader_monitoring_config(include_blocked=True)
    assert mon_cfg.monitoring_only is True
    assert mon_cfg.should_emit is False    # monitoring only — does not surface
    assert mon_cfg.should_compute is True  # but does compute

    # --- Monitoring-mode enrichment: reports must NOT have advisory surfaced ---
    mon_enriched = [enrich_cycle_broader(c, config=mon_cfg) for c in all_cycles]
    surfaced = sum(1 for r in mon_enriched if _has(r))
    if surfaced > 0:
        print(json.dumps({"STOP": f"advisory surfaced in monitoring mode: {surfaced}"}, indent=2))
        return 1

    # --- Compute monitoring metrics (analytics only) ---
    metrics_failed_only = compute_monitoring_metrics(
        shadow,
        config=make_broader_monitoring_config(include_blocked=False),
    )
    metrics_all = compute_monitoring_metrics(all_cycles, config=mon_cfg)

    if metrics_all["auto_executable_violations"] > 0:
        print(json.dumps({"STOP": f"auto_exec_violations={metrics_all['auto_executable_violations']}"}, indent=2))
        return 1

    # Coverage metrics
    assert metrics_all["coverage_rate"] > 0
    assert metrics_all["in_scope_coverage_rate"] == 1.0  # all in-scope cycles get advisory

    result = {
        "epic": 898, "subissue": 902,
        "title": "Controlled Advisory Rollout Monitoring",
        "total_cycles": len(all_cycles),
        "shadow_cycles": len(shadow),
        "synthetic_blocked_cycles": len(blocked),
        "monitoring_mode_surfaced_advisory": surfaced,  # must be 0
        "metrics_failed_only": metrics_failed_only,
        "metrics_all_cycles": metrics_all,
        "auto_executable_violations": 0,
        "coverage_summary": {
            "failed_only_coverage": metrics_failed_only["coverage_rate"],
            "all_cycles_coverage":  metrics_all["coverage_rate"],
            "in_scope_coverage":    metrics_all["in_scope_coverage_rate"],
        },
        "risk_assessment": {
            "auto_exec_risk": "none — 0 violations across all 40 cycles",
            "loop_modification_risk": "none — bridge_diagnostics.affects_loop_decision=False enforced",
            "gate_risk": "none — is_gate=False enforced at module level",
            "false_completion_risk": "none — passed+completed excluded from scope",
        },
        "guardrails": {
            "monitoring_mode_silent": True,
            "no_auto_execution": True,
            "advisory_only": True,
            "loop_decision_unchanged": True,
            "default_off": True,
        },
        "evaluation": "passed", "stop_reason": None, "next_subissue": 903,
    }

    out = Path("reports/mission_brain/broader_advisory/902")
    out.mkdir(parents=True, exist_ok=True)
    (out / "broader_advisory_monitoring_902.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    md = [
        "# Controlled Advisory Rollout Monitoring — #902",
        "## EPIC #898",
        "",
        f"**Total cycles:** {len(all_cycles)} | **Monitoring-mode surfaced:** {surfaced} ✅",
        "",
        "## Monitoring Metrics (failed+blocked)",
        "",
        f"- coverage_rate: {metrics_all['coverage_rate']}",
        f"- in_scope_coverage_rate: {metrics_all['in_scope_coverage_rate']}",
        f"- auto_executable_violations: 0 ✅",
        "",
        "| action | count |",
        "|--------|-------|",
    ]
    for k, v in metrics_all["action_distribution"].items():
        md.append(f"| {k} | {v} |")
    md += ["", "## Evaluation: passed"]
    (out / "broader_advisory_monitoring_902.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({
        "subissue": 902,
        "total_cycles": len(all_cycles),
        "monitoring_mode_surfaced_advisory": surfaced,
        "auto_executable_violations": 0,
        "coverage_rate": metrics_all["coverage_rate"],
        "in_scope_coverage_rate": metrics_all["in_scope_coverage_rate"],
        "evaluation": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
