"""Teacher/Governor Anti-Loop — Epic #46.

Definitive anti-loop enforcement: no semantic duplicates, no
remediation loops, forced strategy shift after family saturation.

The Teacher/Governor has hard powers:
- Block incoherent fallbacks
- Reject duplicate tasks
- Produce escalation reports
- Materialize alternative tasks
- Explain differentiator if repeating a family

Integrates with anti_loop, semantic_dedup, decision_memory, and
the GOAP planner's family saturation tracking.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from igris.core import anti_loop, semantic_dedup
from igris.core.safety import redact_secrets


# ---------------------------------------------------------------------------
# Extended family list (per Epic #46 spec)
# ---------------------------------------------------------------------------

TASK_FAMILIES = (
    "observation", "synthesis", "repo_diff_discovery", "patch_strategy",
    "branch_pr_plan", "review_gate", "candidate_materialization",
    "mastery_cycle", "mastery_gate", "school_report", "grading_diagnosis",
    "stabilization_audit", "devops_deploy", "server_diagnosis",
    "test_repair", "code_patch", "documentation", "security_audit", "other",
)

# Strategy shift mappings: when family X is saturated, shift to Y
STRATEGY_SHIFTS = {
    "observation": ["synthesis", "code_patch"],
    "synthesis": ["code_patch", "documentation"],
    "code_patch": ["test_repair", "review_gate"],
    "test_repair": ["stabilization_audit", "grading_diagnosis"],
    "patch_strategy": ["review_gate", "branch_pr_plan"],
    "branch_pr_plan": ["review_gate", "documentation"],
    "review_gate": ["code_patch", "stabilization_audit"],
    "documentation": ["code_patch", "observation"],
    "devops_deploy": ["server_diagnosis", "stabilization_audit"],
    "server_diagnosis": ["devops_deploy", "security_audit"],
    "stabilization_audit": ["test_repair", "grading_diagnosis"],
    "grading_diagnosis": ["code_patch", "stabilization_audit"],
    "security_audit": ["code_patch", "documentation"],
    "mastery_cycle": ["mastery_gate", "school_report"],
    "mastery_gate": ["code_patch", "documentation"],
    "school_report": ["grading_diagnosis", "code_patch"],
    "candidate_materialization": ["review_gate", "patch_strategy"],
    "repo_diff_discovery": ["synthesis", "patch_strategy"],
    "other": ["observation", "code_patch"],
}


# ---------------------------------------------------------------------------
# Semantic fingerprint for deduplication
# ---------------------------------------------------------------------------

@dataclass
class TaskFingerprint:
    """Rich fingerprint for semantic deduplication.

    Considers family, intent, file target, expected effect,
    block cause, and success criteria.
    """
    family: str = ""
    intent: str = ""
    file_target: str = ""
    expected_effect: str = ""
    block_cause: str = ""
    success_criteria: str = ""

    def compute_hash(self) -> str:
        parts = [
            self.family.lower().strip(),
            self.intent.lower().strip(),
            self.file_target.lower().strip(),
            self.expected_effect.lower().strip(),
            self.block_cause.lower().strip(),
            self.success_criteria.lower().strip(),
        ]
        combined = "|".join(parts)
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, str]:
        return {
            "family": self.family,
            "intent": self.intent,
            "file_target": self.file_target,
            "expected_effect": self.expected_effect,
            "block_cause": self.block_cause,
            "success_criteria": self.success_criteria,
            "hash": self.compute_hash(),
        }


# ---------------------------------------------------------------------------
# Governor decision
# ---------------------------------------------------------------------------

@dataclass
class GovernorDecision:
    """Decision from the Teacher/Governor."""
    action: str = ""  # approve | reject | shift | escalate | materialize
    family: str = ""
    reason: str = ""
    differentiator: str = ""
    alternative_family: str = ""
    alternative_task: Optional[Dict[str, Any]] = None
    saturation_info: Dict[str, int] = field(default_factory=dict)
    blocked_families: List[str] = field(default_factory=list)
    escalation: bool = False
    trace_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "family": self.family,
            "reason": redact_secrets(self.reason),
            "differentiator": self.differentiator,
            "alternative_family": self.alternative_family,
            "alternative_task": self.alternative_task,
            "saturation_info": self.saturation_info,
            "blocked_families": self.blocked_families,
            "escalation": self.escalation,
            "trace_id": self.trace_id,
        }


# ---------------------------------------------------------------------------
# Teacher/Governor
# ---------------------------------------------------------------------------

class TeacherGovernor:
    """Anti-loop Teacher/Governor with hard powers.

    Hard powers:
    1. Block incoherent fallbacks
    2. Reject duplicate tasks
    3. Produce escalation reports
    4. Materialize alternative tasks
    5. Explain differentiator if repeating family
    """

    SATURATION_THRESHOLD = 3

    def __init__(
        self,
        project_root: Optional[str] = None,
        threshold: int = 3,
    ):
        import os
        self.project_root = Path(project_root) if project_root else Path(os.environ.get("PROJECT_ROOT", "."))
        self.threshold = threshold
        self._history: List[str] = []
        self._family_history: List[str] = []  # explicit family tags
        self._fingerprints: Dict[str, TaskFingerprint] = {}
        self._escalation_log: List[Dict[str, Any]] = []
        self._blocked_families: Set[str] = set()
        self._forced_shifts: int = 0

    # -- History management --

    def record_task(self, description: str, family: str = "") -> None:
        """Record a task execution in history."""
        if not family:
            family = anti_loop.classify_task_family(description)
        self._history.append(description)
        self._family_history.append(family)

    def get_history(self) -> List[str]:
        return list(self._history)

    # -- Family saturation --

    def get_family_counts(self) -> Dict[str, int]:
        """Get current family execution counts from explicit tags."""
        from collections import Counter
        recent = self._family_history[-20:] if self._family_history else []
        return dict(Counter(recent))

    def get_saturated_families(self) -> List[str]:
        """Get families that have reached saturation threshold."""
        counts = self.get_family_counts()
        return [fam for fam, n in counts.items() if n >= self.threshold]

    def is_family_saturated(self, family: str) -> bool:
        return family in self.get_saturated_families()

    # -- Semantic deduplication --

    def register_fingerprint(self, task_id: str, fp: TaskFingerprint) -> None:
        """Register a task fingerprint for dedup."""
        self._fingerprints[task_id] = fp

    def is_semantic_duplicate(self, description: str) -> bool:
        """Check if a task is a semantic duplicate of recent history."""
        return semantic_dedup.is_semantic_duplicate(description, self._history)

    def check_fingerprint_duplicate(self, fp: TaskFingerprint) -> Optional[str]:
        """Check if a fingerprint matches any registered fingerprint.

        Returns matching task_id or None.
        """
        fp_hash = fp.compute_hash()
        for task_id, existing in self._fingerprints.items():
            if existing.compute_hash() == fp_hash:
                return task_id
        return None

    # -- Core governance: evaluate a proposed task --

    def evaluate_task(
        self,
        description: str,
        family: str = "",
        differentiator: str = "",
        success_criteria: Optional[List[str]] = None,
        fingerprint: Optional[TaskFingerprint] = None,
        trace_id: str = "",
    ) -> GovernorDecision:
        """Evaluate whether a proposed task should be approved.

        This is the main governance check. Returns a decision with
        action: approve, reject, shift, or escalate.
        """
        if not family:
            family = anti_loop.classify_task_family(description)

        counts = self.get_family_counts()
        saturated = self.get_saturated_families()
        decision = GovernorDecision(
            family=family,
            saturation_info=counts,
            blocked_families=list(self._blocked_families),
            trace_id=trace_id,
        )

        # Check blocked families
        if family in self._blocked_families:
            decision.action = "reject"
            decision.reason = f"Family '{family}' is blocked by governor"
            return decision

        # Check semantic duplication
        if self.is_semantic_duplicate(description):
            decision.action = "reject"
            decision.reason = "Task is a semantic duplicate of recent history"
            return decision

        # Check fingerprint dedup
        if fingerprint:
            dup_id = self.check_fingerprint_duplicate(fingerprint)
            if dup_id:
                decision.action = "reject"
                decision.reason = f"Fingerprint matches existing task {dup_id}"
                return decision

        # Check family saturation
        if family in saturated:
            if differentiator and len(differentiator.strip()) >= 10:
                decision.action = "approve"
                decision.reason = f"Family '{family}' is saturated but has valid differentiator"
                decision.differentiator = differentiator
                return decision

            # Force strategy shift
            alternatives = STRATEGY_SHIFTS.get(family, [])
            available_alt = [alt for alt in alternatives if alt not in saturated and alt not in self._blocked_families]

            if available_alt:
                decision.action = "shift"
                decision.alternative_family = available_alt[0]
                decision.reason = (
                    f"Family '{family}' is saturated ({counts.get(family, 0)} recent). "
                    f"Shifting to '{available_alt[0]}'"
                )
                self._forced_shifts += 1
                return decision

            # All alternatives saturated → escalate
            decision.action = "escalate"
            decision.escalation = True
            decision.reason = f"Family '{family}' saturated and all alternatives exhausted"
            self._escalation_log.append({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "family": family,
                "reason": decision.reason,
                "trace_id": trace_id,
            })
            return decision

        # Check success criteria
        if not success_criteria:
            decision.action = "reject"
            decision.reason = "success_criteria are required"
            return decision

        decision.action = "approve"
        decision.reason = "Task passes all governance checks"
        return decision

    # -- Hard power: block a family --

    def block_family(self, family: str, reason: str = "") -> GovernorDecision:
        """Block a family from future task selection."""
        self._blocked_families.add(family)
        return GovernorDecision(
            action="reject",
            family=family,
            reason=f"Family '{family}' blocked: {reason}",
            blocked_families=list(self._blocked_families),
        )

    def unblock_family(self, family: str) -> None:
        self._blocked_families.discard(family)

    # -- Hard power: materialize alternative task --

    def materialize_alternative(
        self,
        original_family: str,
        mission_id: str = "",
        trace_id: str = "",
    ) -> GovernorDecision:
        """Materialize an alternative task when current family is stuck."""
        saturated = self.get_saturated_families()
        alternatives = STRATEGY_SHIFTS.get(original_family, ["observation", "documentation"])
        available = [f for f in alternatives if f not in saturated and f not in self._blocked_families]

        if not available:
            available = [f for f in TASK_FAMILIES if f not in saturated and f not in self._blocked_families]

        target_family = available[0] if available else "other"

        alt_task = {
            "title": f"Alternative: shift from {original_family} to {target_family}",
            "family": target_family,
            "description": f"Governor forced strategy shift from '{original_family}' (saturated) to '{target_family}'",
            "success_criteria": [f"Complete a {target_family} task successfully"],
            "risk": "low",
            "mission_id": mission_id,
            "trace_id": trace_id,
        }

        return GovernorDecision(
            action="materialize",
            family=target_family,
            reason=f"Materialized alternative: {original_family} → {target_family}",
            alternative_family=target_family,
            alternative_task=alt_task,
            trace_id=trace_id,
        )

    # -- Hard power: escalation report --

    def generate_escalation_report(self, trace_id: str = "") -> Dict[str, Any]:
        """Generate an escalation report with all governance state."""
        return {
            "report_id": f"esc-{uuid.uuid4().hex[:8]}",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "family_counts": self.get_family_counts(),
            "saturated_families": self.get_saturated_families(),
            "blocked_families": list(self._blocked_families),
            "forced_shifts": self._forced_shifts,
            "escalation_count": len(self._escalation_log),
            "escalation_log": self._escalation_log[-10:],
            "recent_history": self._history[-10:],
            "fingerprint_count": len(self._fingerprints),
            "trace_id": trace_id,
            "recommendation": self._recommend_action(),
        }

    def _recommend_action(self) -> str:
        saturated = self.get_saturated_families()
        if not saturated:
            return "No saturated families. Proceed normally."
        unsaturated = [f for f in TASK_FAMILIES if f not in saturated and f not in self._blocked_families]
        if unsaturated:
            return f"Switch to unsaturated family: {unsaturated[0]}"
        return "All families saturated or blocked. Human intervention recommended."

    # -- Summary --

    def get_summary(self) -> Dict[str, Any]:
        return {
            "family_counts": self.get_family_counts(),
            "saturated_families": self.get_saturated_families(),
            "blocked_families": list(self._blocked_families),
            "forced_shifts": self._forced_shifts,
            "escalation_count": len(self._escalation_log),
            "history_length": len(self._history),
            "fingerprint_count": len(self._fingerprints),
            "threshold": self.threshold,
        }

    # -- Persistence --

    def save_state(self) -> Path:
        state_dir = self.project_root / ".igris" / "governor"
        state_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "history": self._history,
            "family_history": self._family_history,
            "blocked_families": list(self._blocked_families),
            "forced_shifts": self._forced_shifts,
            "escalation_log": self._escalation_log,
            "threshold": self.threshold,
        }
        path = state_dir / "state.json"
        path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        return path

    def load_state(self) -> bool:
        path = self.project_root / ".igris" / "governor" / "state.json"
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._history = data.get("history", [])
            self._family_history = data.get("family_history", [])
            self._blocked_families = set(data.get("blocked_families", []))
            self._forced_shifts = data.get("forced_shifts", 0)
            self._escalation_log = data.get("escalation_log", [])
            self.threshold = data.get("threshold", 3)
            return True
        except Exception:
            return False
