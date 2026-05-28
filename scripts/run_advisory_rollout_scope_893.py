#!/usr/bin/env python3
"""EPIC #892 — #893: Define advisory rollout scope, report targets and feature flag.

Usage:
    python scripts/run_advisory_rollout_scope_893.py
"""
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.advisory_rollout import (
    ADVISORY_DEFAULT_RUN_STATUSES,
    ADVISORY_REPORT_TARGETS,
    DEFAULT_ADVISORY_CONFIG,
    make_advisory_enabled_config,
    should_emit_for_run,
)


def _load(path: str) -> list:
    p = Path(path)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return []


def main() -> int:
    all_cycles = (
        _load("reports/mission_brain/shadow_monitoring/847/shadow_batch1_cycles_847.json")
        + _load("reports/mission_brain/shadow_monitoring/849/shadow_batch2_cycles_849.json")
        + _load("reports/mission_brain/shadow_monitoring/859/extended_shadow_batch1_cycles_859.json")
        + _load("reports/mission_brain/shadow_monitoring/860/extended_shadow_batch2_cycles_860.json")
    )

    if not all_cycles:
        print(json.dumps({"STOP": "no shadow cycle data available"}, indent=2))
        return 1

    run_dist: dict = {}
    for c in all_cycles:
        rs = str(c.get("current_loop_decision") or "unknown")
        run_dist[rs] = run_dist.get(rs, 0) + 1

    goal_dist: dict = {}
    for c in all_cycles:
        gs = str(c.get("mission_brain_decision") or "unknown")
        goal_dist[gs] = goal_dist.get(gs, 0) + 1

    # Invariant checks
    assert DEFAULT_ADVISORY_CONFIG.enabled is False
    assert DEFAULT_ADVISORY_CONFIG.is_gate is False
    assert DEFAULT_ADVISORY_CONFIG.should_emit is False

    cfg = make_advisory_enabled_config()
    assert cfg.enabled is True
    assert cfg.is_gate is False
    assert cfg.should_emit is True

    assert should_emit_for_run("failed",  "partial",   cfg) is True
    assert should_emit_for_run("blocked", "partial",   cfg) is True
    assert should_emit_for_run("passed",  "completed", cfg) is False
    assert should_emit_for_run("failed",  "partial",   DEFAULT_ADVISORY_CONFIG) is False

    cycles_in_scope = sum(
        v for rs, v in run_dist.items()
        if rs in ADVISORY_DEFAULT_RUN_STATUSES
    )

    result = {
        "epic": 892, "subissue": 893,
        "title": "Advisory Rollout Scope, Report Targets and Feature Flag",
        "scope": {
            "target_run_statuses": sorted(ADVISORY_DEFAULT_RUN_STATUSES),
            "target_report_types": sorted(ADVISORY_REPORT_TARGETS),
            "include_passed_goal_incomplete_default": False,
            "scope_rationale": {
                "failed":  "Run failed — recovery guidance most relevant",
                "blocked": "Run blocked — escalation guidance relevant",
                "passed+completed": "NOT included — no recovery needed",
                "passed+partial": "NOT included by default — anomaly case, conservative",
            },
        },
        "scope_invariants": [
            "enabled=False by default — never auto-enabled",
            "is_gate=False always — never a gate",
            "advisory_only=True always — never executed automatically",
            "auto_executable=False always — never triggers actions",
            "loop_decision unchanged — scope never modifies loop output",
        ],
        "shadow_data_run_distribution":  run_dist,
        "shadow_data_goal_distribution": goal_dist,
        "shadow_cycles_in_scope": cycles_in_scope,
        "total_shadow_cycles":    len(all_cycles),
        "feature_flag": {
            "name":        "ADVISORY_ROLLOUT_ENABLED",
            "default":     False,
            "env_var":     "ADVISORY_ROLLOUT_ENABLED",
            "valid_values": ["true", "1", "yes"],
            "description": "Set to 'true' to enable advisory recommendations in reports. Default: off.",
        },
        "guardrails": {
            "default_off":             True,
            "no_mandatory_gate":       True,
            "no_auto_execution":       True,
            "advisory_only":           True,
            "loop_decision_unchanged": True,
            "rollback_immediate":      True,
        },
        "evaluation": "passed", "stop_reason": None, "next_subissue": 894,
    }

    out_dir = Path("reports/mission_brain/advisory_rollout/893")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "advisory_rollout_scope_893.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    md = [
        "# Advisory Rollout Scope — #893",
        "## EPIC #892 Mission Brain Advisory Recovery Rollout",
        "",
        "## Scope",
        "",
        f"- Target run statuses: {sorted(ADVISORY_DEFAULT_RUN_STATUSES)}",
        f"- Target report types: {sorted(ADVISORY_REPORT_TARGETS)}",
        "- include_passed_goal_incomplete: False (conservative default)",
        "",
        "## Feature Flag",
        "",
        "- Env var: `ADVISORY_ROLLOUT_ENABLED`",
        "- Default: **OFF**",
        "- Set to `true` to enable.",
        "",
        f"## Shadow data cycles in scope: {cycles_in_scope}/{len(all_cycles)}",
        "",
        "## Guardrails",
        "",
        "- default_off: ✅  |  no_mandatory_gate: ✅  |  no_auto_execution: ✅",
        "",
        "## Evaluation: passed",
    ]
    (out_dir / "advisory_rollout_scope_893.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({
        "subissue": 893,
        "scope_target_run_statuses": sorted(ADVISORY_DEFAULT_RUN_STATUSES),
        "scope_target_report_types": sorted(ADVISORY_REPORT_TARGETS),
        "shadow_cycles_in_scope": cycles_in_scope,
        "total_shadow_cycles": len(all_cycles),
        "evaluation": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
