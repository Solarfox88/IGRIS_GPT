#!/usr/bin/env python3
"""EPIC #904 — #907: Run controlled monitoring on real failed/partial/blocked reports.

Runs compute_selected_metrics() over all cycles in monitoring_only mode.
Does NOT surface advisory in reports — purely analytical.

Cycles:
  - 30 shadow (failed+partial, diagnostic) — real data
  - 10 synthetic blocked+partial          — validated in #900/#901
  - 10 synthetic hard_failure (failed+failed)
  - 10 synthetic insufficient_context (failed+unknown)
  -  5 synthetic fallback (blocked+failed)
  -  5 synthetic excluded (passed+completed) — must be skipped
  Total: 65 in-scope + 5 excluded = 70 total

Stop conditions checked:
  - auto_executable_violations > 0
  - loop_decision_violations > 0
  - is_gate_violations > 0
  - risk_introduced_candidates > 0
  - potential_critical_false_completed > 0
  - monitoring mode surfaces advisory

Writes: reports/mission_brain/selected_advisory/907/selected_advisory_monitoring_907.json

Usage:
    python scripts/run_selected_advisory_monitoring_907.py
"""
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.advisory_rollout import has_advisory
from igris.agent.mission.selected_advisory import (
    compute_selected_metrics,
    enrich_cycle_selected,
    make_selected_monitoring_config,
    make_synthetic_blocked_cycles,
    make_synthetic_excluded_cycles,
    make_synthetic_fallback_cycles,
    make_synthetic_hard_failure_cycles,
    make_synthetic_insufficient_context_cycles,
)


def _load(rel: str) -> list:
    return json.loads(Path(rel).read_text(encoding="utf-8"))


def _gate_fail(msg: str, **kw) -> int:
    print(json.dumps({"STOP": msg, **kw}, indent=2))
    return 1


def main() -> int:
    # --- Load shadow cycles ---
    shadow = (
        _load("reports/mission_brain/shadow_monitoring/847/shadow_batch1_cycles_847.json")
        + _load("reports/mission_brain/shadow_monitoring/849/shadow_batch2_cycles_849.json")
        + _load("reports/mission_brain/shadow_monitoring/859/extended_shadow_batch1_cycles_859.json")
        + _load("reports/mission_brain/shadow_monitoring/860/extended_shadow_batch2_cycles_860.json")
    )
    assert len(shadow) == 30
    for c in shadow:
        c.setdefault("report_type", "diagnostic")

    # --- Synthetic cycles ---
    blocked   = make_synthetic_blocked_cycles(n=10, goal_status="partial")
    hard_fail = make_synthetic_hard_failure_cycles(n=10, goal_status="failed")
    insuf_ctx = make_synthetic_insufficient_context_cycles(n=10, run_status="failed")
    fallback  = make_synthetic_fallback_cycles(n=5)
    excluded  = make_synthetic_excluded_cycles(n=5)

    in_scope  = shadow + blocked + hard_fail + insuf_ctx + fallback   # 65
    all_cycles = in_scope + excluded                                    # 70

    mon_cfg = make_selected_monitoring_config(include_blocked=True)
    assert mon_cfg.monitoring_only is True
    assert mon_cfg.should_emit is False
    assert mon_cfg.should_compute is True

    # --- Monitoring-mode enrichment: advisory must NOT be surfaced ---
    mon_enriched = [enrich_cycle_selected(c, config=mon_cfg) for c in all_cycles]
    surfaced = sum(1 for r in mon_enriched if has_advisory(r))
    if surfaced > 0:
        return _gate_fail(f"advisory surfaced in monitoring mode: {surfaced}")

    # --- Compute metrics (analytics only) ---
    metrics_shadow = compute_selected_metrics(
        shadow,
        config=make_selected_monitoring_config(include_blocked=False),
    )
    metrics_all = compute_selected_metrics(all_cycles, config=mon_cfg)

    # --- Stop condition checks ---
    if metrics_all["auto_executable_violations"] > 0:
        return _gate_fail(
            f"auto_exec_violations={metrics_all['auto_executable_violations']}"
        )
    if metrics_all["loop_decision_violations"] > 0:
        return _gate_fail(
            f"loop_decision_violations={metrics_all['loop_decision_violations']}"
        )
    if metrics_all["is_gate_violations"] > 0:
        return _gate_fail(
            f"is_gate_violations={metrics_all['is_gate_violations']}"
        )
    if metrics_all["risk_introduced_candidates"] > 0:
        return _gate_fail(
            f"risk_introduced_candidates={metrics_all['risk_introduced_candidates']}"
        )
    if metrics_all["potential_critical_false_completed"] > 0:
        return _gate_fail(
            f"potential_critical_false_completed="
            f"{metrics_all['potential_critical_false_completed']}"
        )

    # --- Coverage checks ---
    if metrics_all["in_scope_coverage_rate"] != 1.0:
        return _gate_fail(
            f"in_scope_coverage_rate={metrics_all['in_scope_coverage_rate']} (expected 1.0)"
        )
    if metrics_all["skipped_passed_completed_count"] == 0:
        # 5 excluded cycles should be counted
        return _gate_fail("skipped_passed_completed_count should be > 0")

    # --- Passed+completed must never surface ---
    if metrics_all["potential_critical_false_completed"] != 0:
        return _gate_fail("false_completed guard failed")

    result = {
        "epic": 904, "subissue": 907,
        "title": "Controlled Monitoring on Real Failed/Partial/Blocked Report Generation",
        "total_cycles":              len(all_cycles),
        "in_scope_cycles":           len(in_scope),
        "shadow_cycles":             len(shadow),
        "synthetic_blocked_cycles":  len(blocked),
        "synthetic_hard_failure":    len(hard_fail),
        "synthetic_insufficient_context": len(insuf_ctx),
        "synthetic_fallback":        len(fallback),
        "excluded_cycles":           len(excluded),
        "monitoring_mode_surfaced":  surfaced,
        "metrics_shadow_only":       metrics_shadow,
        "metrics_all_cycles":        metrics_all,
        "coverage_summary": {
            "shadow_coverage":      metrics_shadow.get("in_scope_coverage_rate", 0.0),
            "all_cycles_coverage":  metrics_all["in_scope_coverage_rate"],
            "excluded_skipped":     metrics_all["skipped_passed_completed_count"],
        },
        "risk_assessment": {
            "auto_exec_risk": "none — 0 violations across all 70 cycles",
            "loop_modification_risk": "none — affects_loop_decision=False enforced",
            "gate_risk": "none — is_gate=False enforced at module level",
            "false_completion_risk": (
                "none — passed+completed excluded from scope; "
                f"potential_critical_false_completed="
                f"{metrics_all['potential_critical_false_completed']}"
            ),
        },
        "guardrails": {
            "monitoring_mode_silent": True,
            "no_auto_execution": True,
            "advisory_only": True,
            "loop_decision_unchanged": True,
            "default_off": True,
            "excluded_statuses_blocked": True,
            "rollback_available": True,
        },
        "evaluation": "passed", "stop_reason": None, "next_subissue": 908,
    }

    out = Path("reports/mission_brain/selected_advisory/907")
    out.mkdir(parents=True, exist_ok=True)
    (out / "selected_advisory_monitoring_907.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )

    print(json.dumps({
        "subissue": 907,
        "total_cycles": len(all_cycles),
        "monitoring_mode_surfaced": surfaced,
        "auto_executable_violations": 0,
        "in_scope_coverage_rate": metrics_all["in_scope_coverage_rate"],
        "skipped_passed_completed": metrics_all["skipped_passed_completed_count"],
        "exercised_templates": metrics_all["exercised_templates"],
        "evaluation": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
