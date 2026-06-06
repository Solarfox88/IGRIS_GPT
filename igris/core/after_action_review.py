"""After Action Review — reflection and learning signals after missions (#1247).

AfterActionReviewer analyzes MissionPlan + EvidenceBundle and produces
ReflectionReport with learning signals.

SAFE BY DEFAULT:
- Does not modify policy/security automatically
- Does not auto-execute operations
- Policy recommendations require human review
- All outputs are redacted
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Secret redaction ──────────────────────────────────────────────────────────

_SECRET_RE = re.compile(
    r'(token|passphrase|password|secret|api[_\s]?key|private[_\s]?key|bearer|auth[_\s]?key)'
    r'\s*[=:]\s*\S+',
    re.IGNORECASE,
)

def _redact(text: str) -> str:
    return _SECRET_RE.sub(r'\1=<REDACTED>', str(text)) if text else text

def _redact_any(val: Any) -> Any:
    if isinstance(val, dict):
        return {k: _redact_any(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [_redact_any(i) for i in val]
    elif isinstance(val, str):
        return _redact(val)
    return val

# ── Enums ─────────────────────────────────────────────────────────────────────

class ReflectionOutcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    WAITING_APPROVAL = "waiting_approval"
    INCONCLUSIVE = "inconclusive"


class LearningSignalKind(str, Enum):
    LESSON = "lesson"
    FAILURE_PATTERN = "failure_pattern"
    DECISION_UPDATE = "decision_update"
    CORRECTION = "correction"
    MEMORY_FEEDBACK = "memory_feedback"
    POLICY_RECOMMENDATION = "policy_recommendation"
    RUN_EVENT = "run_event"


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class LearningSignal:
    signal_id: str
    kind: str
    text: str
    scope: str = "project"
    project: str = "jarvis_core"
    source: str = "after_action_review"
    confidence: float = 0.7
    severity: str = "info"  # info | warning | error | critical
    safe_to_persist: bool = True
    requires_human_review: bool = False
    evidence_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return _redact_any({
            "signal_id": self.signal_id,
            "kind": self.kind,
            "text": self.text,
            "scope": self.scope,
            "project": self.project,
            "confidence": self.confidence,
            "severity": self.severity,
            "safe_to_persist": self.safe_to_persist,
            "requires_human_review": self.requires_human_review,
            "evidence_ids": self.evidence_ids,
            "warnings": self.warnings,
        })

    @classmethod
    def make(cls, kind: str, text: str, confidence: float = 0.7,
              requires_review: bool = False, safe_persist: bool = True,
              severity: str = "info") -> "LearningSignal":
        return cls(
            signal_id=str(uuid.uuid4()),
            kind=kind,
            text=_redact(text),
            confidence=confidence,
            severity=severity,
            safe_to_persist=safe_persist,
            requires_human_review=requires_review,
        )


@dataclass
class ReflectionReport:
    report_id: str
    mission_id: str
    route: str = ""
    outcome: str = "inconclusive"
    confidence: float = 0.0
    summary: str = ""
    what_worked: list[str] = field(default_factory=list)
    what_failed: list[str] = field(default_factory=list)
    lessons: list[LearningSignal] = field(default_factory=list)
    failure_patterns: list[LearningSignal] = field(default_factory=list)
    corrections: list[LearningSignal] = field(default_factory=list)
    decision_updates: list[LearningSignal] = field(default_factory=list)
    memory_feedback: list[LearningSignal] = field(default_factory=list)
    policy_recommendations: list[LearningSignal] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def all_signals(self) -> list[LearningSignal]:
        return (self.lessons + self.failure_patterns + self.corrections +
                self.decision_updates + self.memory_feedback + self.policy_recommendations)

    def to_dict(self) -> dict:
        return _redact_any({
            "report_id": self.report_id,
            "mission_id": self.mission_id,
            "route": self.route,
            "outcome": self.outcome,
            "confidence": self.confidence,
            "summary": self.summary,
            "what_worked": self.what_worked,
            "what_failed": self.what_failed,
            "lessons": [s.to_dict() for s in self.lessons],
            "failure_patterns": [s.to_dict() for s in self.failure_patterns],
            "corrections": [s.to_dict() for s in self.corrections],
            "decision_updates": [s.to_dict() for s in self.decision_updates],
            "memory_feedback": [s.to_dict() for s in self.memory_feedback],
            "policy_recommendations": [s.to_dict() for s in self.policy_recommendations],
            "warnings": self.warnings,
            "generated_at": self.generated_at,
        })

    def summary_text(self, max_chars: int = 4000) -> str:
        lines = [
            "[REFLECTION REPORT]",
            f"Mission: {self.mission_id[:8]} | Route: {self.route} | Outcome: {self.outcome}",
            f"Confidence: {self.confidence:.0%} | Generated: {self.generated_at}",
            "",
        ]
        if self.summary:
            lines.append(f"Summary: {self.summary[:200]}")
            lines.append("")
        if self.what_worked:
            lines.append("What worked:")
            for w in self.what_worked[:3]:
                lines.append(f"  + {w[:100]}")
        if self.what_failed:
            lines.append("What failed:")
            for f in self.what_failed[:3]:
                lines.append(f"  - {f[:100]}")
        all_sigs = self.all_signals()
        if all_sigs:
            lines.append(f"\nLearning signals ({len(all_sigs)}):")
            for sig in all_sigs[:5]:
                icon = "[REVIEW]" if sig.requires_human_review else "[PIN]"
                lines.append(f"  {icon} [{sig.kind}] {sig.text[:100]}")
        if self.warnings:
            lines.append(f"\nWarnings: {'; '.join(self.warnings[:3])}")
        text = _redact("\n".join(lines))
        return text[:max_chars] + ("\n[TRUNCATED]" if len(text) > max_chars else "")


# ── User feedback pattern matching ────────────────────────────────────────────

_CORRECTION_PATTERNS = [
    re.compile(r'\b(questa correzione|correggi|correction|sbagliato|non intendevo)\b', re.I),
    re.compile(r'\b(no,|wait no|actually|ah no|mi sbagliavo)\b', re.I),
]
_REMEMBER_PATTERNS = [
    re.compile(r'\b(ricordati|tieni a mente|remember|salva questo|non dimenticare)\b', re.I),
    re.compile(r'\b(da ora in poi|from now on|sempre)\b', re.I),
    re.compile(r'\b(preferisco|prefer|voglio sempre)\b', re.I),
]
_NEGATIVE_PATTERNS = [
    re.compile(r'\b(non fare più|don\'t do again|mai più|stop doing|non usare più)\b', re.I),
]
_POLICY_RELATED = [
    re.compile(r'\b(security|sicurezza|approval|approve|policy|trust|permission|gate)\b', re.I),
]


# ── AfterActionReviewer ───────────────────────────────────────────────────────

class AfterActionReviewer:
    """Analyzes mission + evidence and produces ReflectionReport.

    SAFE: Does not execute operations or modify policies automatically.
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

    def infer_outcome(self, mission_plan: Any, evidence_bundle: Any) -> str:
        """Derive outcome from mission plan and evidence bundle."""
        # Blocked mission
        if mission_plan is not None and getattr(mission_plan, "blocked", False):
            return ReflectionOutcome.BLOCKED.value
        # Waiting approval
        if mission_plan is not None:
            status = str(getattr(mission_plan, "status", ""))
            if status == "waiting_approval" or getattr(mission_plan, "requires_approval", False):
                return ReflectionOutcome.WAITING_APPROVAL.value
        # From bundle
        if evidence_bundle is not None:
            bundle_status = str(getattr(evidence_bundle, "status", ""))
            bundle_ok = getattr(evidence_bundle, "ok", None)
            if bundle_status == "passed" and bundle_ok:
                return ReflectionOutcome.SUCCESS.value
            elif bundle_status == "blocked":
                return ReflectionOutcome.BLOCKED.value
            elif bundle_status == "warning":
                return ReflectionOutcome.PARTIAL.value
            elif bundle_status == "failed" or bundle_ok is False:
                return ReflectionOutcome.FAILURE.value
            elif bundle_status == "inconclusive":
                return ReflectionOutcome.INCONCLUSIVE.value
        return ReflectionOutcome.INCONCLUSIVE.value

    def extract_learning_signals(
        self,
        mission_plan: Any,
        evidence_bundle: Any,
        *,
        user_feedback: str = "",
    ) -> list[LearningSignal]:
        signals = []
        route = str(getattr(mission_plan, "route", "")) if mission_plan is not None else ""
        mission_id = str(getattr(mission_plan, "mission_id", ""))[:12] if mission_plan is not None else ""
        outcome = self.infer_outcome(mission_plan, evidence_bundle)

        if outcome == ReflectionOutcome.SUCCESS.value:
            signals.append(LearningSignal.make(
                LearningSignalKind.LESSON.value,
                f"Route {route!r} completed with verified outcome: success.",
                confidence=0.85,
            ))
            if route == "read_only_inspection":
                signals.append(LearningSignal.make(
                    LearningSignalKind.LESSON.value,
                    "Read-only inspection handled safely through mission-first path.",
                    confidence=0.9,
                ))
            elif route == "project_reasoning":
                signals.append(LearningSignal.make(
                    LearningSignalKind.LESSON.value,
                    "Project reasoning missions should remain plan-only unless explicit approval provided.",
                    confidence=0.8,
                ))
            signals.append(LearningSignal.make(
                LearningSignalKind.MEMORY_FEEDBACK.value,
                f"Mission {mission_id} verification passed.",
                confidence=0.85,
            ))

        elif outcome == ReflectionOutcome.FAILURE.value:
            bundle_results = getattr(evidence_bundle, "results", []) or [] if evidence_bundle is not None else []
            failed_reasons = [
                r.summary for r in bundle_results
                if not getattr(r, "passed", True)
            ]
            reason = "; ".join(failed_reasons[:2]) if failed_reasons else "verification failed"
            signals.append(LearningSignal.make(
                LearningSignalKind.FAILURE_PATTERN.value,
                f"Mission route {route!r} failed verification: {reason}.",
                confidence=0.8, severity="warning",
            ))
            signals.append(LearningSignal.make(
                LearningSignalKind.LESSON.value,
                f"Do not mark {route!r} missions complete without passing verifier evidence.",
                confidence=0.75,
            ))

        elif outcome == ReflectionOutcome.BLOCKED.value:
            signals.append(LearningSignal.make(
                LearningSignalKind.LESSON.value,
                "Blocked high-risk mission was safely stopped before execution.",
                confidence=0.9,
            ))
            signals.append(LearningSignal.make(
                LearningSignalKind.MEMORY_FEEDBACK.value,
                f"Security gate correctly blocked mission {mission_id}.",
                confidence=0.9,
            ))

        elif outcome == ReflectionOutcome.WAITING_APPROVAL.value:
            signals.append(LearningSignal.make(
                LearningSignalKind.LESSON.value,
                f"Mission route {route!r} requires explicit approval before execution.",
                confidence=0.85,
            ))
            # Policy recommendation — requires human review, NOT auto-applied
            signals.append(LearningSignal.make(
                LearningSignalKind.POLICY_RECOMMENDATION.value,
                f"Keep approval gate enabled for {route!r}.",
                confidence=0.8,
                requires_review=True,
                safe_persist=False,  # not auto-applied
                severity="info",
            ))

        elif outcome == ReflectionOutcome.PARTIAL.value:
            signals.append(LearningSignal.make(
                LearningSignalKind.LESSON.value,
                f"Mission route {route!r} partially verified — review warnings.",
                confidence=0.6,
            ))

        # Process user feedback
        if user_feedback and user_feedback.strip():
            fb_clean = _redact(user_feedback.strip())
            is_policy = any(p.search(user_feedback) for p in _POLICY_RELATED)

            if any(p.search(user_feedback) for p in _NEGATIVE_PATTERNS):
                signals.append(LearningSignal.make(
                    LearningSignalKind.CORRECTION.value,
                    f"User instruction: {fb_clean[:150]}",
                    confidence=0.8,
                    requires_review=is_policy,
                    safe_persist=not is_policy,
                ))
            elif any(p.search(user_feedback) for p in _CORRECTION_PATTERNS):
                signals.append(LearningSignal.make(
                    LearningSignalKind.CORRECTION.value,
                    f"User correction: {fb_clean[:150]}",
                    confidence=0.75,
                    requires_review=is_policy,
                    safe_persist=not is_policy,
                ))
            elif any(p.search(user_feedback) for p in _REMEMBER_PATTERNS):
                kind = LearningSignalKind.LESSON.value
                signals.append(LearningSignal.make(
                    kind,
                    f"User preference: {fb_clean[:150]}",
                    confidence=0.7,
                    requires_review=is_policy,
                    safe_persist=not is_policy,
                ))

        return signals

    def review(
        self,
        mission_plan: Any,
        evidence_bundle: Any,
        *,
        user_feedback: str = "",
        context: Any = None,
    ) -> ReflectionReport:
        """Run after-action review and produce ReflectionReport."""
        report = ReflectionReport(
            report_id=str(uuid.uuid4()),
            mission_id=str(getattr(mission_plan, "mission_id", "unknown")) if mission_plan is not None else "unknown",
            route=str(getattr(mission_plan, "route", "")) if mission_plan is not None else "",
        )

        try:
            report.outcome = self.infer_outcome(mission_plan, evidence_bundle)
        except Exception as e:
            report.warnings.append(f"infer_outcome failed: {e}")
            logger.warning("AfterActionReviewer.infer_outcome failed: %s", e)
            report.outcome = ReflectionOutcome.INCONCLUSIVE.value

        # What worked / what failed from bundle
        try:
            if evidence_bundle is not None:
                results = getattr(evidence_bundle, "results", []) or []
                for r in results:
                    if getattr(r, "passed", False):
                        report.what_worked.append(_redact(r.summary)[:100])
                    else:
                        report.what_failed.append(_redact(r.summary)[:100])
        except Exception as e:
            report.warnings.append(f"bundle analysis failed: {e}")
            logger.warning("AfterActionReviewer: bundle analysis failed: %s", e)

        # Extract signals
        try:
            all_signals = self.extract_learning_signals(
                mission_plan, evidence_bundle, user_feedback=user_feedback
            )
            for sig in all_signals:
                kind = sig.kind
                if kind == LearningSignalKind.LESSON.value:
                    report.lessons.append(sig)
                elif kind == LearningSignalKind.FAILURE_PATTERN.value:
                    report.failure_patterns.append(sig)
                elif kind == LearningSignalKind.CORRECTION.value:
                    report.corrections.append(sig)
                elif kind == LearningSignalKind.DECISION_UPDATE.value:
                    report.decision_updates.append(sig)
                elif kind == LearningSignalKind.MEMORY_FEEDBACK.value:
                    report.memory_feedback.append(sig)
                elif kind == LearningSignalKind.POLICY_RECOMMENDATION.value:
                    report.policy_recommendations.append(sig)
        except Exception as e:
            report.warnings.append(f"signal extraction failed: {e}")
            logger.warning("AfterActionReviewer: signal extraction failed: %s", e)

        # Confidence
        total = len(report.all_signals())
        report.confidence = min(0.9, 0.5 + 0.1 * total) if total > 0 else 0.3

        # Summary
        report.summary = _redact(
            f"Mission {report.mission_id[:8]} ({report.route}) — "
            f"outcome: {report.outcome}, "
            f"{len(report.all_signals())} learning signal(s)"
        )

        return report

    def healthcheck(self) -> dict:
        mem = self._memory
        if mem is None:
            try:
                from igris.core.unified_memory import UnifiedMemory
                mem = UnifiedMemory(project_root=self.project_root)
            except Exception as e:
                logger.warning("AfterActionReviewer.healthcheck: UnifiedMemory unavailable: %s", e)
                return {"ok": False, "unified_memory": "unavailable", "error": str(e)}
        return {
            "ok": True,
            "unified_memory": "ok" if mem else "unavailable",
        }
