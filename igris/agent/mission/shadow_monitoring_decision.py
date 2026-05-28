from __future__ import annotations

from typing import Any, Dict


def decide_shadow_monitoring_outcome(metrics: Dict[str, Any]) -> str:
    critical = int(metrics.get("potential_critical_false_completed", 0) or 0)
    risk = int(metrics.get("risk_introduced_candidates", 0) or 0)
    agreement = float(metrics.get("agreement_rate", 0.0) or 0.0)
    rollback_status = str(metrics.get("rollback_path_status", "ok"))
    disagreement = float(metrics.get("disagreement_rate", 0.0) or 0.0)

    if critical > 0:
        return "do not integrate"
    if rollback_status == "failed":
        return "remediate again"
    if risk > 0 and disagreement > 0.4:
        return "remediate again"
    if agreement >= 0.8 and rollback_status == "ok":
        return "candidate for controlled rollout"
    return "keep shadow mode"

