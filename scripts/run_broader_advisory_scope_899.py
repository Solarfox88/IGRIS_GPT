#!/usr/bin/env python3
"""EPIC #898 — #899: Define broader advisory rollout scope and activation config.

Usage:
    python scripts/run_broader_advisory_scope_899.py
"""
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.broader_advisory import (
    BROADER_ADVISORY_REPORT_TYPES,
    DEFAULT_BROADER_CONFIG,
    BroaderAdvisoryConfig,
    compute_monitoring_metrics,
    make_broader_activation_config,
    make_broader_monitoring_config,
    make_synthetic_blocked_cycles,
    should_compute_for_run_broader,
    should_emit_for_run_broader,
)


def _load(path: str) -> list:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def main() -> int:
    shadow_cycles = (
        _load("reports/mission_brain/shadow_monitoring/847/shadow_batch1_cycles_847.json")
        + _load("reports/mission_brain/shadow_monitoring/849/shadow_batch2_cycles_849.json")
        + _load("reports/mission_brain/shadow_monitoring/859/extended_shadow_batch1_cycles_859.json")
        + _load("reports/mission_brain/shadow_monitoring/860/extended_shadow_batch2_cycles_860.json")
    )
    if not shadow_cycles:
        print(json.dumps({"STOP": "no shadow data"}, indent=2)); return 1

    # --- Invariant checks ---
    assert DEFAULT_BROADER_CONFIG.enabled is False
    assert DEFAULT_BROADER_CONFIG.is_gate is False
    assert DEFAULT_BROADER_CONFIG.should_emit is False
    assert DEFAULT_BROADER_CONFIG.should_compute is False

    mon = make_broader_monitoring_config()
    assert mon.enabled is True and mon.monitoring_only is True and mon.should_emit is False
    assert mon.is_gate is False

    act = make_broader_activation_config()
    assert act.enabled is True and act.monitoring_only is False and act.should_emit is True
    assert act.is_gate is False

    act_blocked = make_broader_activation_config(include_blocked=True)
    assert "blocked" in act_blocked.effective_run_statuses
    assert act_blocked.is_gate is False

    # Scope checks
    assert should_emit_for_run_broader("failed",  act) is True
    assert should_emit_for_run_broader("blocked", act) is False        # include_blocked=False default
    assert should_emit_for_run_broader("blocked", act_blocked) is True
    assert should_emit_for_run_broader("passed",  act) is False
    assert should_emit_for_run_broader("failed",  DEFAULT_BROADER_CONFIG) is False

    # Preview what monitoring would look like on shadow data (failed-only)
    metrics_failed = compute_monitoring_metrics(shadow_cycles, config=mon)
    assert metrics_failed["auto_executable_violations"] == 0

    # Define rollout stages
    rollout_stages = [
        {
            "stage": 1,
            "name": "monitoring_only_failed",
            "config": make_broader_monitoring_config(include_blocked=False).to_dict(),
            "description": "Compute advisory for failed runs. Do NOT surface. Collect metrics.",
            "blocked_included": False,
            "surfaces_advisory": False,
        },
        {
            "stage": 2,
            "name": "validate_blocked",
            "config": make_broader_activation_config(include_blocked=True).to_dict(),
            "description": "Validate blocked-status advisory on synthetic data (#900).",
            "blocked_included": True,
            "surfaces_advisory": True,  # in test only
        },
        {
            "stage": 3,
            "name": "activate_selected_reports",
            "config": make_broader_activation_config(include_blocked=True).to_dict(),
            "description": "Surface advisory in mission_execution + diagnostic reports (#901).",
            "blocked_included": True,
            "surfaces_advisory": True,
        },
        {
            "stage": 4,
            "name": "controlled_monitoring",
            "config": make_broader_monitoring_config(include_blocked=True).to_dict(),
            "description": "Run monitoring on all available cycles (#902). Verify metrics.",
            "blocked_included": True,
            "surfaces_advisory": False,
        },
    ]

    result = {
        "epic": 898, "subissue": 899,
        "title": "Broader Advisory Rollout Scope and Activation Config",
        "scope": {
            "selected_report_types": sorted(BROADER_ADVISORY_REPORT_TYPES),
            "default_run_statuses": ["failed"],
            "blocked_status": "pending validation in #900",
            "include_passed_goal_incomplete": False,
            "monitoring_mode_available": True,
        },
        "rollout_stages": rollout_stages,
        "config_variants": {
            "default": DEFAULT_BROADER_CONFIG.to_dict(),
            "monitoring_failed_only": make_broader_monitoring_config(include_blocked=False).to_dict(),
            "activation_failed_only": make_broader_activation_config(include_blocked=False).to_dict(),
            "activation_with_blocked": make_broader_activation_config(include_blocked=True).to_dict(),
        },
        "shadow_preview": {
            "total_cycles": metrics_failed["total_cycles"],
            "cycles_in_scope": metrics_failed["cycles_in_scope"],
            "coverage_rate": metrics_failed["coverage_rate"],
            "action_distribution": metrics_failed["action_distribution"],
            "auto_executable_violations": 0,
        },
        "scope_invariants": [
            "enabled=False by default — never auto-enabled",
            "is_gate=False always — never a gate",
            "advisory_only=True always — never executed automatically",
            "monitoring_only=True by default — compute without surfacing",
            "blocked included only after explicit validation (#900)",
            "loop_decision unchanged — never modifies loop output",
        ],
        "guardrails": {
            "default_off": True, "no_mandatory_gate": True, "no_auto_execution": True,
            "advisory_only": True, "monitoring_only_default": True,
            "blocked_requires_validation": True, "loop_decision_unchanged": True,
        },
        "evaluation": "passed", "stop_reason": None, "next_subissue": 900,
    }

    out = Path("reports/mission_brain/broader_advisory/899")
    out.mkdir(parents=True, exist_ok=True)
    (out / "broader_advisory_scope_899.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    md = [
        "# Broader Advisory Rollout Scope — #899",
        "## EPIC #898",
        "",
        f"- Selected report types: {sorted(BROADER_ADVISORY_REPORT_TYPES)}",
        "- Default run statuses: [failed]",
        "- Blocked: pending validation (#900)",
        "- monitoring_only=True by default",
        "",
        "## Rollout Stages",
        "",
        "| Stage | Name | Surfaces Advisory | Blocked |",
        "|-------|------|-------------------|---------|",
    ]
    for s in rollout_stages:
        md.append(f"| {s['stage']} | {s['name']} | {s['surfaces_advisory']} | {s['blocked_included']} |")
    md += ["", "## Evaluation: passed"]
    (out / "broader_advisory_scope_899.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({
        "subissue": 899,
        "scope_report_types": sorted(BROADER_ADVISORY_REPORT_TYPES),
        "shadow_cycles_in_scope": metrics_failed["cycles_in_scope"],
        "auto_executable_violations": 0,
        "evaluation": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
