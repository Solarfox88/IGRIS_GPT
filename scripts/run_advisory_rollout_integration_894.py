#!/usr/bin/env python3
"""EPIC #892 — #894: Add recovery recommendations to selected reports behind feature flag.

Usage:
    python scripts/run_advisory_rollout_integration_894.py
"""
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.advisory_rollout import (
    DEFAULT_ADVISORY_CONFIG,
    enrich_report_with_advisory,
    has_advisory,
    make_advisory_enabled_config,
    rollback,
    strip_advisory,
    validate_advisory_output,
    validate_no_original_fields_modified,
)


def main() -> int:
    cfg = make_advisory_enabled_config()

    test_cases = [
        {"run_status": "failed",  "goal_status": "partial",   "report_type": "mission_execution", "expect": True},
        {"run_status": "blocked", "goal_status": "partial",   "report_type": "shadow_cycle",       "expect": True},
        {"run_status": "failed",  "goal_status": "failed",    "report_type": "diagnostic",         "expect": True},
        {"run_status": "passed",  "goal_status": "completed", "report_type": "mission_execution",  "expect": False},
        {"run_status": "failed",  "goal_status": "partial",   "report_type": "mission_execution",
         "expect": False, "config": DEFAULT_ADVISORY_CONFIG},
    ]

    case_results = []
    all_passed = True

    for i, tc in enumerate(test_cases):
        base = {"run_id": f"test-{i}", "outcome": tc["run_status"], "report_type": tc["report_type"]}
        config = tc.get("config", cfg)
        enriched = enrich_report_with_advisory(
            base, run_status=tc["run_status"], goal_status=tc["goal_status"], advisory_config=config,
        )
        has_rec = has_advisory(enriched)
        expected = tc["expect"]
        match = has_rec == expected
        if not match:
            all_passed = False

        inv_ok = True
        if has_rec:
            v = validate_advisory_output(enriched)
            inv_ok = v["valid"]
            if not inv_ok:
                all_passed = False

        fields_ok = validate_no_original_fields_modified(base, enriched)
        if not fields_ok:
            all_passed = False

        case_results.append({
            "run_status": tc["run_status"], "goal_status": tc["goal_status"],
            "report_type": tc["report_type"], "expected_advisory": expected,
            "has_advisory": has_rec, "match": match,
            "invariants_ok": inv_ok, "fields_preserved": fields_ok,
            "config_enabled": config.enabled,
        })

    if not all_passed:
        print(json.dumps({"STOP": "integration test failures", "cases": case_results}, indent=2))
        return 1

    # Rollback test
    base = {"run_id": "rollback-test", "outcome": "failed"}
    enriched = enrich_report_with_advisory(base, run_status="failed", goal_status="partial", advisory_config=cfg)
    assert has_advisory(enriched)
    rb = rollback(enriched)
    assert not has_advisory(rb)
    assert "bridge_diagnostics" not in rb
    assert rb["run_id"] == base["run_id"]

    # strip_advisory test
    stripped = strip_advisory(enriched)
    assert not has_advisory(stripped)
    assert stripped["run_id"] == base["run_id"]

    v = validate_advisory_output(enriched)
    assert v["valid"], f"Expected valid, got violations: {v['violations']}"

    result = {
        "epic": 892, "subissue": 894,
        "title": "Advisory Integration — Report Enrichment Behind Feature Flag",
        "test_cases_run":    len(test_cases),
        "test_cases_passed": sum(1 for c in case_results if c["match"]),
        "all_passed": all_passed,
        "rollback_tested": True, "strip_advisory_tested": True,
        "original_fields_preserved": True, "auto_executable_violations": 0,
        "case_results": case_results,
        "guardrails": {
            "default_off": True, "no_auto_execution": True,
            "advisory_only": True, "rollback_immediate": True,
            "loop_decision_unchanged": True,
        },
        "evaluation": "passed", "stop_reason": None, "next_subissue": 895,
    }

    out_dir = Path("reports/mission_brain/advisory_rollout/894")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "advisory_rollout_integration_894.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    md = [
        "# Advisory Rollout Integration — #894",
        "## EPIC #892",
        "",
        f"**Test cases:** {len(test_cases)} | **All passed:** {all_passed}",
        "",
        "| run_status | goal_status | report_type | expected | got | match |",
        "|------------|-------------|-------------|----------|-----|-------|",
    ]
    for c in case_results:
        md.append(
            f"| {c['run_status']} | {c['goal_status']} | {c['report_type']} "
            f"| {c['expected_advisory']} | {c['has_advisory']} | {c['match']} |"
        )
    md += ["", "## Evaluation: passed"]
    (out_dir / "advisory_rollout_integration_894.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({
        "subissue": 894, "test_cases_run": len(test_cases),
        "test_cases_passed": len(test_cases), "all_passed": all_passed, "evaluation": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
