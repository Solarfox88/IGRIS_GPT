"""Learning Feedback Applier — persists learning signals via UnifiedMemory (#1247).

SAFE BY DEFAULT:
- Policy recommendations are skipped unless explicitly enabled
- Signals requiring human review are skipped by default
- ok=True only if real storage writes succeed
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from igris.core.redaction import redact as _redact, redact_nested as _redact_any  # noqa: F401

logger = logging.getLogger(__name__)


@dataclass
class LearningApplyResult:
    ok: bool
    report_id: str = ""
    applied_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    applied: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    persistence_degraded: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return _redact_any({
            "ok": self.ok,
            "report_id": self.report_id,
            "applied_count": self.applied_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "applied": self.applied,
            "skipped": self.skipped,
            "failed": self.failed,
            "warnings": self.warnings,
            "persistence_degraded": self.persistence_degraded,
        })


class LearningFeedbackApplier:
    """Applies ReflectionReport signals to UnifiedMemory.

    ok=True if applied_count>0 and failed_count==0,
         or if all signals are safely skipped (requires_review/policy)
    ok=False if storage fails for non-policy signals
    """

    def __init__(self, project_root: "str | Path | None" = None, unified_memory=None):
        if project_root is None:
            try:
                from igris.models.config import CONFIG
                project_root = CONFIG.project_root
            except Exception:
                project_root = Path.home()
        self.project_root = Path(project_root)
        self._memory = unified_memory

    def _get_memory(self):
        if self._memory is None:
            try:
                from igris.core.unified_memory import UnifiedMemory
                self._memory = UnifiedMemory(project_root=self.project_root)
            except Exception as e:
                logger.debug("LearningFeedbackApplier: UnifiedMemory unavailable: %s", e)
        return self._memory

    def apply_signal(self, signal) -> dict:
        """Apply a single LearningSignal to UnifiedMemory. Returns status dict."""
        from igris.core.after_action_review import LearningSignalKind

        mem = self._get_memory()
        if mem is None:
            return {"ok": False, "reason": "unified_memory_unavailable",
                    "signal_id": signal.signal_id}

        text = _redact(signal.text)
        kind = signal.kind

        try:
            if kind in (LearningSignalKind.LESSON.value, LearningSignalKind.FAILURE_PATTERN.value):
                r = mem.store_lesson(text=text, project=signal.project,
                                      confidence=signal.confidence)
            elif kind == LearningSignalKind.DECISION_UPDATE.value:
                r = mem.store_decision(text=text, project=signal.project,
                                        confidence=signal.confidence)
            elif kind == LearningSignalKind.CORRECTION.value:
                r = mem.store_correction(text=text)
            elif kind == LearningSignalKind.MEMORY_FEEDBACK.value:
                r = mem.record_feedback(
                    memory_id=signal.signal_id, used=True,
                    outcome="success", notes=text[:200],
                )
            elif kind == LearningSignalKind.RUN_EVENT.value:
                r = mem.store_run_event(
                    mission_id=signal.signal_id,
                    action="learning_signal",
                    status="recorded",
                    outcome=text[:200],
                    project=signal.project,
                )
            else:
                return {"ok": True, "status": "skipped", "reason": f"unknown kind {kind!r}",
                        "signal_id": signal.signal_id}

            if r.ok:
                return {"ok": True, "status": "applied", "signal_id": signal.signal_id, "kind": kind}
            else:
                logger.warning("LearningFeedbackApplier: store returned ok=False for %s: %s",
                               signal.signal_id, r.warnings)
                return {"ok": False, "status": "failed", "reason": str(r.warnings),
                        "signal_id": signal.signal_id}

        except Exception as e:
            logger.warning("LearningFeedbackApplier: apply_signal failed for %s: %s",
                           signal.signal_id, e)
            return {"ok": False, "status": "failed", "reason": str(e),
                    "signal_id": signal.signal_id}

    def apply_report(
        self,
        report,
        *,
        apply_policy_recommendations: bool = False,
        require_review_for_low_confidence: bool = True,
        min_confidence: float = 0.5,
    ) -> LearningApplyResult:
        """Apply all applicable signals from a ReflectionReport."""
        from igris.core.after_action_review import LearningSignalKind

        result = LearningApplyResult(ok=False, report_id=report.report_id)
        signals = report.all_signals()

        for signal in signals:
            # Skip policy recommendations by default (require explicit enable)
            if signal.kind == LearningSignalKind.POLICY_RECOMMENDATION.value:
                if not apply_policy_recommendations:
                    result.skipped.append({"signal_id": signal.signal_id,
                                            "reason": "policy_recommendation_requires_explicit_enable"})
                    result.skipped_count += 1
                    result.warnings.append("policy_recommendation skipped — requires human review")
                    continue

            # Skip signals requiring human review
            if signal.requires_human_review:
                result.skipped.append({"signal_id": signal.signal_id,
                                        "reason": "requires_human_review"})
                result.skipped_count += 1
                continue

            # Skip low confidence signals if required
            if require_review_for_low_confidence and signal.confidence < min_confidence:
                result.skipped.append({"signal_id": signal.signal_id,
                                        "reason": f"low_confidence={signal.confidence:.2f}"})
                result.skipped_count += 1
                continue

            # Skip non-safe signals
            if not signal.safe_to_persist:
                result.skipped.append({"signal_id": signal.signal_id,
                                        "reason": "not_safe_to_persist"})
                result.skipped_count += 1
                continue

            # Apply signal
            apply_result = self.apply_signal(signal)
            if apply_result.get("ok"):
                result.applied.append(apply_result)
                result.applied_count += 1
            else:
                result.failed.append(apply_result)
                result.failed_count += 1
                if not result.persistence_degraded:
                    result.persistence_degraded = True
                    result.warnings.append(f"Storage failed for signal {signal.signal_id}: "
                                            f"{apply_result.get('reason', '')}")

        # Determine ok
        if result.failed_count > 0:
            result.ok = False
        elif result.applied_count > 0:
            result.ok = True
        else:
            # All skipped — ok=True with warning
            result.ok = True
            if result.skipped_count > 0 and not result.warnings:
                result.warnings.append(f"{result.skipped_count} signal(s) require human review")

        return result

    def healthcheck(self) -> dict:
        mem = self._get_memory()
        return {"ok": True, "unified_memory": "ok" if mem else "unavailable"}
