from __future__ import annotations

from typing import Any, Dict

# Allowed decisions for extended monitoring (Epic #857).
# "candidate for controlled rollout" is retained for backward compatibility
# with #845 callers but maps to the new decision set in decide_extended().
ALLOWED_DECISIONS = frozenset({
    "keep shadow mode",
    "extend monitoring again",
    "start disagreement calibration",
    "remediate again",
    "do not integrate",
})

# Decisions that are NOT allowed regardless of metrics.
FORBIDDEN_DECISIONS = frozenset({
    "enable by default",
    "controlled rollout activation",
    "mandatory gate integration",
    "remove current loop behavior",
})


def decide_shadow_monitoring_outcome(metrics: Dict[str, Any]) -> str:
    """Original decision function (Epic #845 compatible).

    Retained unchanged for backward compatibility with existing scripts.
    New code should use decide_extended_shadow_outcome().
    """
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


def decide_extended_shadow_outcome(
    metrics: Dict[str, Any],
    cumulative_cycles: int = 0,
    previous_agreement_rate: float | None = None,
) -> str:
    """Extended decision function for Epic #857.

    Uses the five allowed decisions from the extended protocol:
    - keep shadow mode
    - extend monitoring again
    - start disagreement calibration
    - remediate again
    - do not integrate

    Args:
        metrics: aggregate metrics dict (from aggregate_shadow_cycles).
        cumulative_cycles: total cycles observed so far (including this batch).
        previous_agreement_rate: agreement_rate from the previous batch, used
            to detect improving trend.
    """
    critical = int(metrics.get("potential_critical_false_completed", 0) or 0)
    risk = int(metrics.get("risk_introduced_candidates", 0) or 0)
    rollback_status = str(metrics.get("rollback_path_status", "ok"))
    agreement = float(metrics.get("agreement_rate", 0.0) or 0.0)
    disagreement = float(metrics.get("disagreement_rate", 0.0) or 0.0)
    rep_score = float(metrics.get("sample_representativeness_score", 0.0) or 0.0)
    trend = str(metrics.get("final_readiness_trend", "stable"))

    # Hard stops — safety first
    if critical > 0:
        return "do not integrate"
    if rollback_status == "failed":
        return "remediate again"
    if risk > 0 and disagreement > 0.4:
        return "remediate again"

    # Not enough data yet
    if cumulative_cycles < 30:
        return "extend monitoring again"

    # Low representativeness → keep collecting diverse samples
    if rep_score < 0.5:
        return "extend monitoring again"

    # Divergence is total and stable → understand why before calibrating
    if agreement == 0.0 and trend == "stable":
        # We have enough cycles with zero agreement and no risk → calibrate
        if cumulative_cycles >= 30 and rep_score >= 0.5:
            return "start disagreement calibration"
        return "extend monitoring again"

    # Partial agreement improving toward threshold
    if agreement > 0.0 and trend == "improving":
        if previous_agreement_rate is not None and agreement > previous_agreement_rate:
            return "keep shadow mode"

    # Degrading trend without hard-stop criteria
    if trend == "degrading":
        return "remediate again"

    # Default: keep observing
    return "keep shadow mode"
