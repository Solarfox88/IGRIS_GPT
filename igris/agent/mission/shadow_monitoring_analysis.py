from __future__ import annotations

from typing import Any, Dict, Iterable, List


def analyze_disagreements(cycles: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = list(cycles)
    mismatch_classes: Dict[str, int] = {}
    for r in rows:
        cls = str(r.get("mismatch_class") or "unknown")
        mismatch_classes[cls] = mismatch_classes.get(cls, 0) + 1

    total = len(rows)
    disagreements = [r for r in rows if not bool(r.get("agreement", False))]
    prevented = sum(1 for r in rows if bool(r.get("prevented_error_candidate", False)))
    risk = sum(1 for r in rows if bool(r.get("risk_introduced_candidate", False)))
    potential_false_completed = sum(1 for r in rows if bool(r.get("potential_false_completed", False)))
    potential_false_partial = sum(1 for r in rows if bool(r.get("potential_false_partial", False)))
    potential_false_failed = sum(1 for r in rows if bool(r.get("potential_false_failed", False)))

    dominant = "none"
    if mismatch_classes:
        dominant = max(mismatch_classes.items(), key=lambda kv: kv[1])[0]

    return {
        "total_cycles": total,
        "disagreement_count": len(disagreements),
        "disagreement_rate": round((len(disagreements) / total), 3) if total else 0.0,
        "mismatch_classes": mismatch_classes,
        "dominant_mismatch_class": dominant,
        "prevented_error_candidates": prevented,
        "risk_introduced_candidates": risk,
        "potential_false_completed": potential_false_completed,
        "potential_false_partial": potential_false_partial,
        "potential_false_failed": potential_false_failed,
        "recommendation_focus": (
            "stabilize disagreement taxonomy"
            if len(disagreements) > 0
            else "maintain current shadow policy"
        ),
    }

