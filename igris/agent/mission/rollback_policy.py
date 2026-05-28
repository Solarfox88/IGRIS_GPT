from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict


RISKY_MISMATCH_CLASSES = {
    "risky_false_completed_candidate",
    "risky_overclaim_by_mission_brain",
}


def evaluate_wrapper_policy(
    *,
    requested_mode: str,
    shadow_record: Dict[str, Any],
    shadow_error: str = "",
    rollback_to_wrapper_on_guardrail: bool = True,
    auto_rollback_on_risky_mismatch: bool = True,
    force_wrapper_mode: bool = False,
) -> Dict[str, Any]:
    mode = (requested_mode or "shadow").strip().lower()
    decision: Dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "requested_mode": mode,
        "effective_mode": mode,
        "auto_rollback_triggered": False,
        "manual_force_wrapper": False,
        "reason": "no_guardrail_trigger",
        "mismatch_class": str(shadow_record.get("mismatch_class") or ""),
    }

    if force_wrapper_mode:
        decision["effective_mode"] = "wrapper"
        decision["manual_force_wrapper"] = True
        decision["reason"] = "manual_force_wrapper_mode"
        return decision

    if shadow_error and rollback_to_wrapper_on_guardrail:
        decision["effective_mode"] = "wrapper"
        decision["auto_rollback_triggered"] = True
        decision["reason"] = "shadow_execution_error"
        return decision

    mismatch_class = str(shadow_record.get("mismatch_class") or "")
    if (
        auto_rollback_on_risky_mismatch
        and rollback_to_wrapper_on_guardrail
        and mismatch_class in RISKY_MISMATCH_CLASSES
    ):
        decision["effective_mode"] = "wrapper"
        decision["auto_rollback_triggered"] = True
        decision["reason"] = "risky_mismatch_guardrail"
        return decision

    return decision


def persist_wrapper_policy_decision(project_root: str, policy_decision: Dict[str, Any]) -> str:
    out_dir = Path(project_root) / ".igris" / "mission_brain" / "shadow"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "rollback_policy_decisions.jsonl"
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(policy_decision) + "\n")
    return str(out)

