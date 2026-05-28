#!/usr/bin/env python3
"""EPIC #904 — #906: Enable advisory enrichment in selected reports behind explicit flag.

Validates with activation config (monitoring_only=False, include_blocked=True):
  - All failed shadow cycles receive advisory (30 cycles, report_type=diagnostic).
  - All synthetic blocked cycles receive advisory (10 cycles).
  - All synthetic hard_failure cycles receive advisory (10 cycles, failed+failed).
  - All synthetic insufficient_context cycles receive advisory (10 cycles, failed+unknown).
  - Synthetic fallback cycles receive advisory via fallback template (5 cycles, blocked+failed).
  - Synthetic excluded cycles (passed+completed) do NOT receive advisory.
  - 0 auto_exec / loop / gate violations.
  - Original fields preserved (additive only).
  - Template usage is logged (log_template_usage=True).
  - With monitoring_only=True: reports unchanged (advisory not surfaced).
  - With default config: nothing surfaced.

Total in-scope cycles: 30 + 10 + 10 + 10 + 5 = 65
Plus excluded (must not get advisory): 5

Writes: reports/mission_brain/selected_advisory/906/selected_advisory_enable_906.json

Usage:
    python scripts/run_selected_advisory_enable_906.py
"""
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.advisory_rollout import (
    has_advisory,
    validate_advisory_output,
    validate_no_original_fields_modified,
)
from igris.agent.mission.selected_advisory import (
    DEFAULT_SELECTED_CONFIG,
    aggregate_selected_cycles,
    enrich_cycle_selected,
    make_selected_activation_config,
    make_selected_monitoring_config,
    make_synthetic_blocked_cycles,
    make_synthetic_excluded_cycles,
    make_synthetic_fallback_cycles,
    make_synthetic_hard_failure_cycles,
    make_synthetic_insufficient_context_cycles,
    strip_selected_advisory,
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
    assert len(shadow) == 30, f"Expected 30 shadow cycles, got {len(shadow)}"

    # Tag shadow cycles with report_type
    for c in shadow:
        c.setdefault("report_type", "diagnostic")

    # --- Synthetic cycles ---
    blocked   = make_synthetic_blocked_cycles(n=10, goal_status="partial")
    hard_fail = make_synthetic_hard_failure_cycles(n=10, goal_status="failed")
    insuf_ctx = make_synthetic_insufficient_context_cycles(n=10, run_status="failed")
    fallback  = make_synthetic_fallback_cycles(n=5)    # blocked+failed → fallback
    excluded  = make_synthetic_excluded_cycles(n=5)    # passed+completed → must NOT get advisory

    in_scope = shadow + blocked + hard_fail + insuf_ctx + fallback
    all_cycles = in_scope + excluded

    assert len(in_scope) == 65, f"Expected 65 in-scope cycles, got {len(in_scope)}"
    assert len(all_cycles) == 70

    act_cfg = make_selected_activation_config(include_blocked=True)
    mon_cfg = make_selected_monitoring_config(include_blocked=True)

    # =========================================================================
    # Activation mode: all in-scope cycles must get advisory
    # =========================================================================
    enriched = [enrich_cycle_selected(c, config=act_cfg) for c in in_scope]

    missing = [i for i, r in enumerate(enriched) if not has_advisory(r)]
    if missing:
        return _gate_fail(f"missing advisory for in-scope cycles", indices=missing[:10])

    # Validate invariants
    inv_errors = []
    for i, r in enumerate(enriched):
        v = validate_advisory_output(r)
        if not v["valid"]:
            inv_errors.append({"idx": i, "violations": v["violations"]})
    if inv_errors:
        return _gate_fail("invariant violations", errors=inv_errors[:5])

    # Original fields preserved
    field_viol = 0
    for orig, enr in zip(in_scope, enriched):
        if not validate_no_original_fields_modified(orig, enr):
            field_viol += 1
    if field_viol > 0:
        return _gate_fail(f"original fields modified in {field_viol} cycles")

    # is_gate and affects_loop_decision
    gate_viol = sum(1 for r in enriched
                    if r.get("bridge_diagnostics", {}).get("is_gate") is not False)
    loop_viol = sum(1 for r in enriched
                    if r.get("bridge_diagnostics", {}).get("affects_loop_decision") is not False)
    if gate_viol > 0:
        return _gate_fail(f"is_gate_violations={gate_viol}")
    if loop_viol > 0:
        return _gate_fail(f"loop_decision_violations={loop_viol}")

    # Template logging
    no_template_log = [i for i, r in enumerate(enriched)
                       if has_advisory(r) and "_advisory_template_used" not in r]
    if no_template_log:
        return _gate_fail(f"template not logged for {len(no_template_log)} cycles")

    # =========================================================================
    # Excluded cycles MUST NOT get advisory
    # =========================================================================
    enriched_excluded = [enrich_cycle_selected(c, config=act_cfg) for c in excluded]
    got_advisory = [i for i, r in enumerate(enriched_excluded) if has_advisory(r)]
    if got_advisory:
        return _gate_fail(f"advisory surfaced on excluded (passed+completed) cycles",
                          indices=got_advisory)

    # =========================================================================
    # Monitoring mode: advisory NOT surfaced
    # =========================================================================
    mon_enriched = [enrich_cycle_selected(c, config=mon_cfg) for c in all_cycles]
    surfaced = sum(1 for r in mon_enriched if has_advisory(r))
    if surfaced > 0:
        return _gate_fail(f"advisory surfaced in monitoring mode: {surfaced}")

    # =========================================================================
    # Default config: nothing surfaced
    # =========================================================================
    default_enriched = [enrich_cycle_selected(c, config=DEFAULT_SELECTED_CONFIG)
                        for c in all_cycles]
    surfaced_default = sum(1 for r in default_enriched if has_advisory(r))
    if surfaced_default > 0:
        return _gate_fail(f"advisory surfaced with default config: {surfaced_default}")

    # =========================================================================
    # Rollback verification
    # =========================================================================
    rolled_back = [strip_selected_advisory(r) for r in enriched]
    rollback_fail = sum(
        1 for r in rolled_back
        if has_advisory(r)
        or "bridge_diagnostics" in r
        or "_advisory_template_used" in r
    )
    if rollback_fail > 0:
        return _gate_fail(f"rollback failed for {rollback_fail} cycles")

    # =========================================================================
    # Aggregate stats
    # =========================================================================
    agg = aggregate_selected_cycles(in_scope, config=act_cfg)
    assert agg["auto_executable_violations"] == 0
    assert agg["loop_decision_violations"]   == 0
    assert agg["is_gate_violations"]         == 0

    # Template distribution
    tmpl_dist = agg.get("template_distribution", {})
    action_dist = agg.get("action_distribution", {})

    # Per-cycle detail (first 70 for report)
    per_cycle = [
        {
            "cycle_id":    r.get("cycle_id", f"cycle-{i}"),
            "run_status":  r.get("current_loop_decision", ""),
            "goal_status": r.get("mission_brain_decision", ""),
            "action":      r["recovery_recommendation"]["action"],
            "template":    r.get("_advisory_template_used", "unknown"),
            "auto_executable": r["recovery_recommendation"]["auto_executable"],
        }
        for i, r in enumerate(enriched)
    ]

    result = {
        "epic": 904, "subissue": 906,
        "title": "Enable Advisory Enrichment in Selected Reports Behind Explicit Flag",
        "total_in_scope":          len(in_scope),
        "shadow_cycles":           len(shadow),
        "synthetic_blocked":       len(blocked),
        "synthetic_hard_failure":  len(hard_fail),
        "synthetic_insufficient_context": len(insuf_ctx),
        "synthetic_fallback":      len(fallback),
        "excluded_cycles":         len(excluded),
        "cycles_with_advisory":    agg["cycles_with_advisory"],
        "excluded_got_advisory":   0,
        "auto_executable_violations":   0,
        "loop_decision_violations":     0,
        "is_gate_violations":           0,
        "field_preservation_violations": 0,
        "rollback_verified":            True,
        "monitoring_mode_silent":       surfaced == 0,
        "default_mode_silent":          surfaced_default == 0,
        "template_distribution":        tmpl_dist,
        "action_distribution":          action_dist,
        "exercised_template_count":     agg.get("exercised_template_count", 0),
        "exercised_templates":          agg.get("exercised_templates", []),
        "per_cycle": per_cycle,
        "guardrails": {
            "default_off": True,
            "no_auto_execution": True,
            "advisory_only": True,
            "loop_decision_unchanged": True,
            "monitoring_mode_silent": True,
            "original_fields_preserved": True,
            "excluded_statuses_blocked": True,
            "template_usage_logged": True,
            "rollback_immediate": True,
        },
        "evaluation": "passed", "stop_reason": None, "next_subissue": 907,
    }

    out = Path("reports/mission_brain/selected_advisory/906")
    out.mkdir(parents=True, exist_ok=True)
    (out / "selected_advisory_enable_906.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )

    print(json.dumps({
        "subissue": 906,
        "total_in_scope": len(in_scope),
        "cycles_with_advisory": agg["cycles_with_advisory"],
        "excluded_got_advisory": 0,
        "auto_executable_violations": 0,
        "exercised_templates": agg.get("exercised_templates", []),
        "monitoring_mode_silent": True,
        "rollback_verified": True,
        "evaluation": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
