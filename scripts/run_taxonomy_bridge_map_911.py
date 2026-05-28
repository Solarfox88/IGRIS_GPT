#!/usr/bin/env python3
"""EPIC #910 — #911: Map all bridge combined_statuses to taxonomy templates.

Documents the full before/after mapping, identifies all gaps, validates
alignment invariants, and verifies advisory scope does NOT change.

Writes: reports/mission_brain/taxonomy_bridge/911/taxonomy_bridge_map_911.json

Usage:
    python scripts/run_taxonomy_bridge_map_911.py
"""
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.taxonomy_bridge import (
    ALL_TAXONOMY_TEMPLATES,
    BRIDGE_TO_TAXONOMY_ALIGNMENT,
    INTERNAL_FALLBACK_ONLY_TEMPLATES,
    NEWLY_ALIGNED_BRIDGE_OUTPUTS,
    NEWLY_REACHABLE_IN_SCOPE_TEMPLATES,
    POST_ALIGNMENT_REACHABLE,
    PRE_ALIGNMENT_REACHABLE,
    REACHABLE_OUTSIDE_SCOPE,
    compute_alignment_coverage,
    get_bridge_to_taxonomy_report,
    validate_alignment_invariants,
)
from igris.agent.mission.status_bridge import COMBINED_STATUSES


def _gate_fail(msg: str, **kw) -> int:
    print(json.dumps({"STOP": msg, **kw}, indent=2))
    return 1


def main() -> int:
    # --- Validate invariants ---
    violations = validate_alignment_invariants()
    if violations:
        return _gate_fail("alignment invariant violations", violations=violations)

    # --- Coverage analysis ---
    cov = compute_alignment_coverage()
    if not cov["all_bridge_outputs_have_template"]:
        return _gate_fail(
            "bridge outputs without template after alignment",
            missing=cov["bridge_outputs_without_template"],
        )
    if cov["unaccounted_templates"]:
        return _gate_fail(
            "taxonomy templates not accounted for",
            unaccounted=cov["unaccounted_templates"],
        )

    # --- Template count assertions ---
    assert cov["total_taxonomy_templates"] == 9
    assert cov["pre_alignment_in_scope_count"] == 4
    assert cov["post_alignment_in_scope_count"] == 6
    assert cov["newly_reachable_count"] == 2
    assert cov["excluded_from_scope_count"] == 2
    assert cov["internal_fallback_only_count"] == 1
    assert cov["all_taxonomy_templates_reachable"] is True

    # --- Advisory scope unchanged: only failed/blocked run statuses ---
    # run_passed_goal_partial is only from passed runs (excluded from advisory scope)
    assert "run_passed_goal_partial" in REACHABLE_OUTSIDE_SCOPE
    # completed is excluded
    assert "completed" in REACHABLE_OUTSIDE_SCOPE
    # unknown_status is internal-only
    assert "unknown_status" in INTERNAL_FALLBACK_ONLY_TEMPLATES

    # --- Full mapping report ---
    mapping_report = get_bridge_to_taxonomy_report()
    assert len(mapping_report) == len(COMBINED_STATUSES)

    result = {
        "epic": 910, "subissue": 911,
        "title": "Bridge-to-Taxonomy Full Mapping Analysis",
        "coverage": cov,
        "mapping_report": mapping_report,
        "alignment_map": BRIDGE_TO_TAXONOMY_ALIGNMENT,
        "invariant_violations": 0,
        "scope_unchanged": True,  # only failed/blocked scope, no new statuses
        "advisory_scope_note": (
            "Advisory scope unchanged: failed/blocked run statuses only. "
            "run_passed_goal_partial reachable only from passed runs (excluded). "
            "completed excluded by is_excluded_status(). "
            "Alignment only improves template specificity for in-scope cycles."
        ),
        "evaluation": "passed", "stop_reason": None, "next_subissue": 912,
    }

    out = Path("reports/mission_brain/taxonomy_bridge/911")
    out.mkdir(parents=True, exist_ok=True)
    (out / "taxonomy_bridge_map_911.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )

    print(json.dumps({
        "subissue": 911,
        "pre_alignment_in_scope": 4,
        "post_alignment_in_scope": 6,
        "newly_reachable": sorted(NEWLY_REACHABLE_IN_SCOPE_TEMPLATES),
        "all_bridge_outputs_have_template": True,
        "all_templates_accounted": True,
        "invariant_violations": 0,
        "scope_unchanged": True,
        "evaluation": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
