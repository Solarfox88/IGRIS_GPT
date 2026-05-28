from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _mean(values: List[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def _p95(values: List[float]) -> float:
    if not values:
        return 0.0
    arr = sorted(values)
    idx = max(0, min(len(arr) - 1, int(round(0.95 * (len(arr) - 1)))))
    return round(arr[idx], 3)


def aggregate_shadow_cycles(cycles: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(cycles)
    total = len(rows)
    agreements = sum(1 for r in rows if bool(r.get("agreement", False)))
    disagreements = total - agreements
    prevented = sum(1 for r in rows if bool(r.get("prevented_error_candidate", False)))
    risk = sum(1 for r in rows if bool(r.get("risk_introduced_candidate", False)))
    pfc = sum(1 for r in rows if bool(r.get("potential_false_completed", False)))
    pcfc = sum(1 for r in rows if bool(r.get("potential_critical_false_completed", False)))
    pfp = sum(1 for r in rows if bool(r.get("potential_false_partial", False)))
    pff = sum(1 for r in rows if bool(r.get("potential_false_failed", False)))

    usefulness = [float(r.get("report_usefulness_score", 0.0) or 0.0) for r in rows]
    lat_ms = [float(r.get("latency_overhead_ms", 0.0) or 0.0) for r in rows]
    cost_usd = [float(r.get("cost_overhead_usd", 0.0) or 0.0) for r in rows]

    rollback_statuses = [str(r.get("rollback_path_status", "ok")) for r in rows]
    rollback_path_status = "ok"
    if any(s == "failed" for s in rollback_statuses):
        rollback_path_status = "failed"
    elif any(s == "degraded" for s in rollback_statuses):
        rollback_path_status = "degraded"

    final_readiness_trend = "stable"
    if pcfc > 0 or risk > max(1, total // 3):
        final_readiness_trend = "degrading"
    elif agreements >= max(1, int(0.8 * total)):
        final_readiness_trend = "improving"

    return {
        "total_shadow_cycles": total,
        "mission_brain_decision": "mixed",
        "current_loop_decision": "mixed",
        "agreement_rate": round((agreements / total), 3) if total else 0.0,
        "disagreement_rate": round((disagreements / total), 3) if total else 0.0,
        "prevented_error_candidates": prevented,
        "risk_introduced_candidates": risk,
        "potential_false_completed": pfc,
        "potential_critical_false_completed": pcfc,
        "potential_false_partial": pfp,
        "potential_false_failed": pff,
        "report_usefulness_score": _mean(usefulness),
        "latency_overhead": {
            "mean_ms": _mean(lat_ms),
            "p95_ms": _p95(lat_ms),
        },
        "cost_overhead": {
            "total_usd": round(sum(cost_usd), 6),
            "mean_usd": _mean(cost_usd),
        },
        "rollback_path_status": rollback_path_status,
        "final_readiness_trend": final_readiness_trend,
    }

