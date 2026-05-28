from __future__ import annotations

from typing import Any, Dict


def decide_integration_readiness(
    *,
    risky_mismatch_count: int,
    agreement_rate: float,
    critical_false_completed_count: int,
    rollback_policy_working: bool,
) -> str:
    """Return final decision for controlled deeper integration readiness."""
    if critical_false_completed_count > 0:
        return "do not integrate"

    if (
        risky_mismatch_count == 0
        and agreement_rate >= 0.80
        and rollback_policy_working
    ):
        return "controlled rollout candidate"

    if rollback_policy_working:
        return "keep shadow mode"

    return "remediate again"


def build_readiness_payload(
    shadow_summary: Dict[str, Any],
    rollback_summary: Dict[str, Any],
    critical_false_completed_count: int = 0,
) -> Dict[str, Any]:
    risky = int(shadow_summary.get("risky_mismatch_count", 0) or 0)
    agreement = float(shadow_summary.get("agreement_rate", 0.0) or 0.0)
    rollback_ok = int(rollback_summary.get("wrapper_effective_count", 0) or 0) > 0
    decision = decide_integration_readiness(
        risky_mismatch_count=risky,
        agreement_rate=agreement,
        critical_false_completed_count=critical_false_completed_count,
        rollback_policy_working=rollback_ok,
    )
    return {
        "shadow_summary": shadow_summary,
        "rollback_summary": rollback_summary,
        "critical_false_completed_count": critical_false_completed_count,
        "decision": decision,
    }

