#!/usr/bin/env python3
"""EPIC #904 — #905: Define selected advisory report targets and activation config.

Validates:
  - SelectedAdvisoryConfig default is disabled.
  - make_selected_monitoring_config() / make_selected_activation_config() work.
  - SELECTED_ADVISORY_REPORT_TARGETS are correctly defined.
  - is_gate=False enforced.
  - should_emit / should_compute semantics correct.
  - Excluded run statuses (passed, completed) are blocked.
  - Rollback (strip_selected_advisory) verified.
  - Template coverage taxonomy documented.

Writes: reports/mission_brain/selected_advisory/905/selected_advisory_targets_905.json

Usage:
    python scripts/run_selected_advisory_targets_905.py
"""
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.selected_advisory import (
    ALL_TAXONOMY_TEMPLATES,
    BRIDGE_OUTPUTS_WITHOUT_TAXONOMY_TEMPLATE,
    DEFAULT_SELECTED_CONFIG,
    EXCLUDED_BY_SCOPE_TEMPLATES,
    EXCLUDED_RUN_STATUSES,
    REACHABLE_IN_SCOPE_TEMPLATES,
    SELECTED_ADVISORY_REPORT_TARGETS,
    SELECTED_ADVISORY_RUN_STATUSES,
    UNREACHABLE_FROM_BRIDGE_TEMPLATES,
    SelectedAdvisoryConfig,
    is_excluded_status,
    make_selected_activation_config,
    make_selected_monitoring_config,
    should_compute,
    should_enrich,
    strip_selected_advisory,
)


def _gate_fail(msg: str) -> int:
    print(json.dumps({"STOP": msg}, indent=2))
    return 1


def main() -> int:
    errors = []

    # --- Default config ---
    if DEFAULT_SELECTED_CONFIG.enabled is not False:
        errors.append("DEFAULT.enabled must be False")
    if DEFAULT_SELECTED_CONFIG.is_gate is not False:
        errors.append("DEFAULT.is_gate must be False")
    if DEFAULT_SELECTED_CONFIG.should_emit is not False:
        errors.append("DEFAULT.should_emit must be False")
    if DEFAULT_SELECTED_CONFIG.should_compute is not False:
        errors.append("DEFAULT.should_compute must be False")
    if DEFAULT_SELECTED_CONFIG.monitoring_only is not True:
        errors.append("DEFAULT.monitoring_only must be True")

    # --- Report targets ---
    for rt in ("diagnostic", "mission_execution", "adoption", "shadow", "hardening"):
        if rt not in SELECTED_ADVISORY_REPORT_TARGETS:
            errors.append(f"Report target {rt!r} missing from SELECTED_ADVISORY_REPORT_TARGETS")

    # --- Monitoring config ---
    mon_cfg = make_selected_monitoring_config(include_blocked=True)
    if mon_cfg.enabled is not True:
        errors.append("monitoring_cfg.enabled must be True")
    if mon_cfg.monitoring_only is not True:
        errors.append("monitoring_cfg.monitoring_only must be True")
    if mon_cfg.should_emit is not False:
        errors.append("monitoring_cfg.should_emit must be False")
    if mon_cfg.should_compute is not True:
        errors.append("monitoring_cfg.should_compute must be True")
    if mon_cfg.is_gate is not False:
        errors.append("monitoring_cfg.is_gate must be False")

    # --- Activation config ---
    act_cfg = make_selected_activation_config(include_blocked=True)
    if act_cfg.enabled is not True:
        errors.append("activation_cfg.enabled must be True")
    if act_cfg.monitoring_only is not False:
        errors.append("activation_cfg.monitoring_only must be False")
    if act_cfg.should_emit is not True:
        errors.append("activation_cfg.should_emit must be True")
    if act_cfg.is_gate is not False:
        errors.append("activation_cfg.is_gate must be False")

    # --- Run status scope ---
    if "failed" not in SELECTED_ADVISORY_RUN_STATUSES:
        errors.append("'failed' missing from SELECTED_ADVISORY_RUN_STATUSES")
    if "blocked" not in SELECTED_ADVISORY_RUN_STATUSES:
        errors.append("'blocked' missing from SELECTED_ADVISORY_RUN_STATUSES")
    if "passed" not in EXCLUDED_RUN_STATUSES:
        errors.append("'passed' missing from EXCLUDED_RUN_STATUSES")

    # --- should_enrich semantics ---
    if not should_enrich("failed", "partial", "diagnostic", act_cfg):
        errors.append("should_enrich: failed+partial+diagnostic must be True for activation")
    if not should_enrich("blocked", "partial", "diagnostic", act_cfg):
        errors.append("should_enrich: blocked+partial+diagnostic must be True for activation")
    if should_enrich("passed", "completed", "diagnostic", act_cfg):
        errors.append("should_enrich: passed+completed must be False (excluded)")
    if should_enrich("passed", "partial", "diagnostic", act_cfg):
        errors.append("should_enrich: passed+partial must be False (run not in scope)")
    if should_enrich("failed", "partial", "unknown_report", act_cfg):
        errors.append("should_enrich: unknown report_type must be False")
    if should_enrich("failed", "partial", "diagnostic", DEFAULT_SELECTED_CONFIG):
        errors.append("should_enrich: default config must always be False")

    # --- should_compute (monitoring mode) ---
    if not should_compute("failed", "partial", "diagnostic", mon_cfg):
        errors.append("should_compute: failed+partial+diagnostic must be True for monitoring")
    if should_compute("passed", "completed", "diagnostic", mon_cfg):
        errors.append("should_compute: passed+completed must be False")
    if should_compute("failed", "partial", "diagnostic", DEFAULT_SELECTED_CONFIG):
        errors.append("should_compute: default config must be False")

    # --- is_excluded_status ---
    if not is_excluded_status("passed", "completed"):
        errors.append("is_excluded_status: passed+completed must be True")
    if is_excluded_status("failed", "partial"):
        errors.append("is_excluded_status: failed+partial must be False")
    if is_excluded_status("blocked", "partial"):
        errors.append("is_excluded_status: blocked+partial must be False")

    # --- Rollback ---
    enriched = {
        "run_id": "test",
        "outcome": "failed",
        "bridge_diagnostics": {"is_gate": False},
        "recovery_recommendation": {"action": "diagnose", "auto_executable": False},
        "_advisory_template_used": "hard_failure",
    }
    rolled = strip_selected_advisory(enriched)
    if "recovery_recommendation" in rolled:
        errors.append("strip_selected_advisory: recovery_recommendation not removed")
    if "bridge_diagnostics" in rolled:
        errors.append("strip_selected_advisory: bridge_diagnostics not removed")
    if "_advisory_template_used" in rolled:
        errors.append("strip_selected_advisory: _advisory_template_used not removed")
    if rolled.get("run_id") != "test":
        errors.append("strip_selected_advisory: original fields not preserved")

    # --- Template coverage taxonomy ---
    if len(ALL_TAXONOMY_TEMPLATES) != 9:
        errors.append(f"ALL_TAXONOMY_TEMPLATES must have 9 templates, got {len(ALL_TAXONOMY_TEMPLATES)}")
    if len(REACHABLE_IN_SCOPE_TEMPLATES) != 4:
        errors.append(f"REACHABLE_IN_SCOPE_TEMPLATES must have 4, got {len(REACHABLE_IN_SCOPE_TEMPLATES)}")
    if len(EXCLUDED_BY_SCOPE_TEMPLATES) != 1:
        errors.append(f"EXCLUDED_BY_SCOPE_TEMPLATES must have 1, got {len(EXCLUDED_BY_SCOPE_TEMPLATES)}")
    if len(UNREACHABLE_FROM_BRIDGE_TEMPLATES) != 4:
        errors.append(f"UNREACHABLE_FROM_BRIDGE_TEMPLATES must have 4, got {len(UNREACHABLE_FROM_BRIDGE_TEMPLATES)}")
    if len(BRIDGE_OUTPUTS_WITHOUT_TAXONOMY_TEMPLATE) != 4:
        errors.append(f"BRIDGE_OUTPUTS_WITHOUT_TAXONOMY_TEMPLATE must have 4, got {len(BRIDGE_OUTPUTS_WITHOUT_TAXONOMY_TEMPLATE)}")

    if errors:
        return _gate_fail(f"scope validation errors: {errors}")

    # --- 4 Rollout stages ---
    rollout_stages = [
        {
            "stage": 1,
            "name": "Monitoring only (monitoring_only=True)",
            "description": "Compute advisory internally; do NOT surface in reports. Analytics only.",
            "config": "make_selected_monitoring_config(include_blocked=True)",
            "status": "ready",
        },
        {
            "stage": 2,
            "name": "Activation for selected report types (monitoring_only=False)",
            "description": (
                "Surface advisory in diagnostic, mission_execution, adoption, "
                "shadow, hardening reports. Failed+blocked in scope. "
                "Passed+completed excluded."
            ),
            "config": "make_selected_activation_config(include_blocked=True)",
            "status": "ready",
        },
        {
            "stage": 3,
            "name": "Template coverage expansion",
            "description": (
                "Validate all 4 reachable in-scope templates on real+synthetic data. "
                "Document 4 orphaned templates. Plan taxonomy alignment fix."
            ),
            "config": "make_selected_activation_config(include_blocked=True)",
            "status": "pending — requires diverse real run outcomes",
        },
        {
            "stage": 4,
            "name": "Consolidated decision",
            "description": (
                "Review template coverage, usefulness scores, zero-violation proof. "
                "Decide: keep / expand / calibrate / remediate."
            ),
            "config": "N/A",
            "status": "pending",
        },
    ]

    result = {
        "epic": 904, "subissue": 905,
        "title": "Selected Advisory Report Targets and Activation Config",
        "selected_report_targets": sorted(SELECTED_ADVISORY_REPORT_TARGETS),
        "selected_run_statuses": sorted(SELECTED_ADVISORY_RUN_STATUSES),
        "excluded_run_statuses": sorted(EXCLUDED_RUN_STATUSES),
        "taxonomy_overview": {
            "total_templates": len(ALL_TAXONOMY_TEMPLATES),
            "all_templates": sorted(ALL_TAXONOMY_TEMPLATES),
            "reachable_in_scope": sorted(REACHABLE_IN_SCOPE_TEMPLATES),
            "excluded_by_scope": sorted(EXCLUDED_BY_SCOPE_TEMPLATES),
            "unreachable_from_bridge": sorted(UNREACHABLE_FROM_BRIDGE_TEMPLATES),
            "bridge_outputs_without_template": sorted(BRIDGE_OUTPUTS_WITHOUT_TAXONOMY_TEMPLATE),
        },
        "config_variants": {
            "default": DEFAULT_SELECTED_CONFIG.to_dict(),
            "monitoring": make_selected_monitoring_config().to_dict(),
            "activation": make_selected_activation_config().to_dict(),
        },
        "rollout_stages": rollout_stages,
        "guardrails": {
            "advisory_only": True,
            "no_auto_execution": True,
            "no_mandatory_gate": True,
            "flag_required": True,
            "no_global_default": True,
            "rollback_immediate": True,
            "passed_completed_excluded": True,
            "monitoring_mode_available": True,
        },
        "validation_errors": 0,
        "evaluation": "passed",
        "stop_reason": None,
        "next_subissue": 906,
    }

    out = Path("reports/mission_brain/selected_advisory/905")
    out.mkdir(parents=True, exist_ok=True)
    (out / "selected_advisory_targets_905.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )

    print(json.dumps({
        "subissue": 905,
        "selected_report_targets": sorted(SELECTED_ADVISORY_REPORT_TARGETS),
        "total_taxonomy_templates": 9,
        "reachable_in_scope": 4,
        "unreachable_from_bridge": 4,
        "validation_errors": 0,
        "evaluation": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
