"""Taxonomy-Bridge Alignment — EPIC #910 (#911-#912).

Provides an explicit mapping from status_bridge combined_status values to
recovery_taxonomy template keys. Resolves the naming mismatch identified in
EPIC #904 (#908) where 4 taxonomy templates were orphaned and 4 bridge outputs
produced the fallback template (await_clarification) instead of a specific
recovery recommendation.

Design constraints:
  - Advisory scope does NOT change: only failed/blocked run statuses.
  - No new run_statuses or report_types are introduced.
  - advisory_only=True and auto_executable=False enforced via taxonomy templates.
  - 'unknown_status' taxonomy template is internal-fallback-only (used when
    bridge result is missing combined_status key).
  - Pure functions only — no side effects.

Before alignment (EPIC #904):
  Reachable in advisory scope: 4 templates
  Falling back (await_clarification): 2 bridge outputs within scope

After alignment (EPIC #910):
  Reachable in advisory scope: 6 templates
  Falling back: 0 within scope (unknown_status only for edge cases)
  Still excluded from scope: run_passed_goal_partial (passed runs excluded)
  Internal-fallback-only: unknown_status
"""
from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Optional

from igris.agent.mission.recovery_taxonomy import (
    RECOVERY_TEMPLATES,
    RecoveryTemplate,
    get_template,
)
from igris.agent.mission.status_bridge import COMBINED_STATUSES


# ---------------------------------------------------------------------------
# Alignment map: bridge combined_status → taxonomy template key
# ---------------------------------------------------------------------------

BRIDGE_TO_TAXONOMY_ALIGNMENT: Dict[str, str] = {
    # Direct matches (name identical — listed for documentation)
    "completed":                           "completed",
    "technical_failure_with_goal_progress": "technical_failure_with_goal_progress",
    "hard_failure":                        "hard_failure",
    "insufficient_context":                "insufficient_context",
    "blocked_with_goal_progress":          "blocked_with_goal_progress",
    # Previously unaligned — now explicitly mapped
    "technical_success_but_goal_incomplete": "run_passed_goal_partial",
    "blocked_goal_failed":                 "blocked_no_goal_progress",
    "goal_complete_run_failed":            "anomaly_run_passed_goal_not_completed",
    "goal_complete_run_blocked":           "anomaly_run_passed_goal_not_completed",
}

_INTERNAL_FALLBACK_TEMPLATE_KEY: str = "unknown_status"

NEWLY_ALIGNED_BRIDGE_OUTPUTS: FrozenSet[str] = frozenset({
    "technical_success_but_goal_incomplete",
    "blocked_goal_failed",
    "goal_complete_run_failed",
    "goal_complete_run_blocked",
})

NEWLY_REACHABLE_IN_SCOPE_TEMPLATES: FrozenSet[str] = frozenset({
    "blocked_no_goal_progress",
    "anomaly_run_passed_goal_not_completed",
})

PRE_ALIGNMENT_REACHABLE: FrozenSet[str] = frozenset({
    "technical_failure_with_goal_progress",
    "hard_failure",
    "insufficient_context",
    "blocked_with_goal_progress",
})

POST_ALIGNMENT_REACHABLE: FrozenSet[str] = (
    PRE_ALIGNMENT_REACHABLE | NEWLY_REACHABLE_IN_SCOPE_TEMPLATES
)

REACHABLE_OUTSIDE_SCOPE: FrozenSet[str] = frozenset({
    "run_passed_goal_partial",
    "completed",
})

INTERNAL_FALLBACK_ONLY_TEMPLATES: FrozenSet[str] = frozenset({
    "unknown_status",
})

ALL_TAXONOMY_TEMPLATES: FrozenSet[str] = frozenset(RECOVERY_TEMPLATES.keys())


# ---------------------------------------------------------------------------
# Core lookup
# ---------------------------------------------------------------------------

def get_aligned_template(combined_status: str) -> Optional[RecoveryTemplate]:
    """Get recovery template using alignment map.

    Uses BRIDGE_TO_TAXONOMY_ALIGNMENT to resolve bridge combined_status
    to the correct taxonomy template key before falling back.

    Args:
        combined_status: Bridge combined_status value.

    Returns:
        RecoveryTemplate dict, or None if no template found (edge case).
    """
    aligned_key = BRIDGE_TO_TAXONOMY_ALIGNMENT.get(combined_status, combined_status)
    tmpl = get_template(aligned_key)
    if tmpl is None:
        tmpl = get_template(combined_status)
    return tmpl


def get_aligned_template_key(combined_status: str) -> str:
    """Return the taxonomy key that combined_status maps to via alignment.

    Returns 'fallback' if no template found after alignment.
    """
    aligned_key = BRIDGE_TO_TAXONOMY_ALIGNMENT.get(combined_status, combined_status)
    if get_template(aligned_key) is not None:
        return aligned_key
    if get_template(combined_status) is not None:
        return combined_status
    return "fallback"


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def compute_alignment_coverage() -> Dict[str, Any]:
    """Compute template coverage before and after alignment."""
    total_taxonomy  = len(ALL_TAXONOMY_TEMPLATES)
    total_bridge    = len(COMBINED_STATUSES)
    pre_count       = len(PRE_ALIGNMENT_REACHABLE)
    post_count      = len(POST_ALIGNMENT_REACHABLE)
    newly_count     = len(NEWLY_REACHABLE_IN_SCOPE_TEMPLATES)
    excl_count      = len(REACHABLE_OUTSIDE_SCOPE)
    internal_count  = len(INTERNAL_FALLBACK_ONLY_TEMPLATES)

    bridge_without_template = [
        cs for cs in COMBINED_STATUSES
        if get_aligned_template(cs) is None
    ]

    all_accounted = (
        POST_ALIGNMENT_REACHABLE
        | REACHABLE_OUTSIDE_SCOPE
        | INTERNAL_FALLBACK_ONLY_TEMPLATES
    )
    unaccounted = ALL_TAXONOMY_TEMPLATES - all_accounted

    return {
        "total_taxonomy_templates":        total_taxonomy,
        "total_bridge_combined_statuses":  total_bridge,
        "pre_alignment_in_scope_count":    pre_count,
        "post_alignment_in_scope_count":   post_count,
        "newly_reachable_count":           newly_count,
        "excluded_from_scope_count":       excl_count,
        "internal_fallback_only_count":    internal_count,
        "all_bridge_outputs_have_template": len(bridge_without_template) == 0,
        "bridge_outputs_without_template": bridge_without_template,
        "all_taxonomy_templates_reachable": len(unaccounted) == 0,
        "unaccounted_templates":           sorted(unaccounted),
        "pre_alignment_reachable":         sorted(PRE_ALIGNMENT_REACHABLE),
        "post_alignment_reachable":        sorted(POST_ALIGNMENT_REACHABLE),
        "newly_reachable":                 sorted(NEWLY_REACHABLE_IN_SCOPE_TEMPLATES),
        "excluded_from_scope":             sorted(REACHABLE_OUTSIDE_SCOPE),
        "internal_fallback_only":          sorted(INTERNAL_FALLBACK_ONLY_TEMPLATES),
    }


def get_bridge_to_taxonomy_report() -> List[Dict[str, Any]]:
    """Return full bridge combined_status → taxonomy template mapping report."""
    rows = []
    for combined_status in sorted(COMBINED_STATUSES):
        aligned_key = BRIDGE_TO_TAXONOMY_ALIGNMENT.get(combined_status, combined_status)
        tmpl = get_aligned_template(combined_status)
        was_fallback = combined_status in NEWLY_ALIGNED_BRIDGE_OUTPUTS
        rows.append({
            "bridge_combined_status": combined_status,
            "taxonomy_template_key":  aligned_key,
            "action": tmpl["action"] if tmpl else "fallback_await_clarification",
            "confidence": tmpl["confidence"] if tmpl else "low",
            "alignment_type": "direct_match" if combined_status == aligned_key else "aligned",
            "was_fallback_before": was_fallback,
            "template_found": tmpl is not None,
        })
    return rows


def validate_alignment_invariants() -> List[str]:
    """Validate all alignment invariants. Returns list of violations (empty = OK)."""
    violations = []

    for bridge_cs, taxonomy_key in BRIDGE_TO_TAXONOMY_ALIGNMENT.items():
        tmpl = get_template(taxonomy_key)
        if tmpl is None:
            violations.append(f"Alignment error: {bridge_cs!r} → {taxonomy_key!r} no template")
        elif tmpl.get("auto_executable") is not False:
            violations.append(f"Invariant: {taxonomy_key}.auto_executable must be False")
        elif tmpl.get("advisory_only") is not True:
            violations.append(f"Invariant: {taxonomy_key}.advisory_only must be True")

    if PRE_ALIGNMENT_REACHABLE | NEWLY_REACHABLE_IN_SCOPE_TEMPLATES != POST_ALIGNMENT_REACHABLE:
        violations.append("POST_ALIGNMENT_REACHABLE != PRE | NEWLY")

    all_sets = [POST_ALIGNMENT_REACHABLE, REACHABLE_OUTSIDE_SCOPE,
                INTERNAL_FALLBACK_ONLY_TEMPLATES]
    for i, s1 in enumerate(all_sets):
        for s2 in all_sets[i+1:]:
            overlap = s1 & s2
            if overlap:
                violations.append(f"Overlapping template sets: {sorted(overlap)}")

    all_accounted = (
        POST_ALIGNMENT_REACHABLE | REACHABLE_OUTSIDE_SCOPE
        | INTERNAL_FALLBACK_ONLY_TEMPLATES
    )
    missing = ALL_TAXONOMY_TEMPLATES - all_accounted
    if missing:
        violations.append(f"Templates not accounted for: {sorted(missing)}")
    extra = all_accounted - ALL_TAXONOMY_TEMPLATES
    if extra:
        violations.append(f"Unknown templates: {sorted(extra)}")

    return violations


_import_violations = validate_alignment_invariants()
if _import_violations:
    raise AssertionError(
        f"TAXONOMY-BRIDGE ALIGNMENT INVARIANT VIOLATIONS: {_import_violations}"
    )
