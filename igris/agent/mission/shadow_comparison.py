from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List


@dataclass
class ShadowComparisonSummary:
    total_runs: int
    agreement_count: int
    disagreement_count: int
    agreement_rate: float
    risky_mismatch_count: int
    safe_mismatch_count: int
    mismatch_classes: Dict[str, int]
    quality_gate_pass_rate: float
    satisfaction_gate_pass_rate: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_runs": self.total_runs,
            "agreement_count": self.agreement_count,
            "disagreement_count": self.disagreement_count,
            "agreement_rate": self.agreement_rate,
            "risky_mismatch_count": self.risky_mismatch_count,
            "safe_mismatch_count": self.safe_mismatch_count,
            "mismatch_classes": self.mismatch_classes,
            "quality_gate_pass_rate": self.quality_gate_pass_rate,
            "satisfaction_gate_pass_rate": self.satisfaction_gate_pass_rate,
        }


def classify_mismatch(loop_decision: str, mission_brain_decision: str) -> str:
    loop_d = (loop_decision or "").strip().lower()
    mb_d = (mission_brain_decision or "").strip().lower()

    if loop_d == mb_d:
        return "agreement"
    if loop_d == "completed" and mb_d in {"partial", "failed"}:
        return "risky_false_completed_candidate"
    if loop_d in {"partial", "failed"} and mb_d == "completed":
        return "risky_overclaim_by_mission_brain"
    if loop_d == "partial" and mb_d == "failed":
        return "safe_more_conservative_mission_brain"
    if loop_d == "failed" and mb_d == "partial":
        return "safe_more_optimistic_mission_brain"
    return "other_mismatch"


def compare_shadow_records(records: Iterable[Dict[str, Any]]) -> ShadowComparisonSummary:
    rows: List[Dict[str, Any]] = list(records)
    total = len(rows)
    agreements = 0
    quality_pass = 0
    satisfaction_pass = 0
    mismatch_classes: Dict[str, int] = {}

    for row in rows:
        loop_decision = str(row.get("loop_decision") or "")
        mb_decision = str(row.get("mission_brain_decision") or "")
        klass = classify_mismatch(loop_decision, mb_decision)
        mismatch_classes[klass] = mismatch_classes.get(klass, 0) + 1
        if klass == "agreement":
            agreements += 1
        if bool(row.get("quality_gate_passed", False)):
            quality_pass += 1
        if bool(row.get("satisfaction_gate_passed", False)):
            satisfaction_pass += 1

    disagreements = total - agreements
    risky = sum(
        mismatch_classes.get(k, 0)
        for k in ("risky_false_completed_candidate", "risky_overclaim_by_mission_brain")
    )
    safe = sum(
        mismatch_classes.get(k, 0)
        for k in (
            "safe_more_conservative_mission_brain",
            "safe_more_optimistic_mission_brain",
            "other_mismatch",
        )
    )
    return ShadowComparisonSummary(
        total_runs=total,
        agreement_count=agreements,
        disagreement_count=disagreements,
        agreement_rate=round((agreements / total), 3) if total else 0.0,
        risky_mismatch_count=risky,
        safe_mismatch_count=safe,
        mismatch_classes=mismatch_classes,
        quality_gate_pass_rate=round((quality_pass / total), 3) if total else 0.0,
        satisfaction_gate_pass_rate=round((satisfaction_pass / total), 3) if total else 0.0,
    )

