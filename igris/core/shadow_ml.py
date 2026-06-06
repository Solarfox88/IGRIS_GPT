"""Shadow ML — ML-light in shadow/evaluation mode only (#1248).

SAFE BY DEFAULT:
- shadow_only=True always
- changed_decision=False always for operational output
- No route override, no trust escalation, no approval bypass
- No policy/verifier/mission-plan mutation
- No external ML dependencies (heuristic/weighted scoring only)
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

class ShadowDecisionSource(str, Enum):
    HEURISTIC = "heuristic"
    MEMORY_FEEDBACK = "memory_feedback"
    SYNTHETIC_PRIOR = "synthetic_prior"
    INSUFFICIENT_DATA = "insufficient_data"


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ShadowScore:
    item_id: str
    score: float
    confidence: float = 0.0
    reason: str = ""
    source: str = ShadowDecisionSource.HEURISTIC.value
    features: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return _redact_any({
            "item_id": self.item_id,
            "score": self.score,
            "confidence": self.confidence,
            "reason": self.reason,
            "source": self.source,
            "features": self.features,
            "warnings": self.warnings,
        })


@dataclass
class ShadowReport:
    report_id: str
    kind: str
    ok: bool = True
    shadow_only: bool = True
    changed_decision: bool = False   # MUST stay False for operational output
    query: str = ""
    baseline_decision: dict[str, Any] = field(default_factory=dict)
    shadow_decision: dict[str, Any] = field(default_factory=dict)
    scores: list[ShadowScore] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return _redact_any({
            "report_id": self.report_id,
            "kind": self.kind,
            "ok": self.ok,
            "shadow_only": self.shadow_only,
            "changed_decision": self.changed_decision,
            "query": self.query,
            "baseline_decision": self.baseline_decision,
            "shadow_decision": self.shadow_decision,
            "scores": [s.to_dict() for s in self.scores],
            "metrics": self.metrics,
            "warnings": self.warnings,
            "generated_at": self.generated_at,
            "metadata": self.metadata,
        })

    def summary_text(self, max_chars: int = 4000) -> str:
        lines = [
            "[SHADOW REPORT]",
            f"Kind: {self.kind} | shadow_only={self.shadow_only} | changed_decision={self.changed_decision}",
            f"OK: {self.ok} | Generated: {self.generated_at}",
        ]
        if self.query:
            lines.append(f"Query: {_redact(self.query[:100])}")
        if self.baseline_decision:
            lines.append(f"Baseline: {str(self.baseline_decision)[:200]}")
        if self.shadow_decision:
            lines.append(f"Shadow:   {str(self.shadow_decision)[:200]}")
        if self.scores:
            lines.append(f"Scores ({len(self.scores)}):")
            for s in self.scores[:5]:
                lines.append(f"  [{s.item_id[:12]}] score={s.score:.3f} src={s.source}")
        if self.metrics:
            lines.append(f"Metrics: {str(self.metrics)[:200]}")
        if self.warnings:
            lines.append(f"Warnings: {'; '.join(self.warnings[:3])}")
        text = _redact("\n".join(lines))
        return text[:max_chars] + ("\n[TRUNCATED]" if len(text) > max_chars else "")


# ── Intent / risk patterns for shadow classification ─────────────────────────

_DESTRUCTIVE_PATTERNS = [
    re.compile(r'\b(cancella|delete|drop|truncate|rm\s+-rf|wipe|distruggi|elimina\s+tutto)\b', re.I),
    re.compile(r'\b(destroy|purge|nuke|obliterate)\b', re.I),
]
_DEPLOY_PATTERNS = [
    re.compile(r'\b(deploy|rilascia|release|push\s+to\s+prod|manda\s+in\s+prod|go\s+live)\b', re.I),
    re.compile(r'\b(rollout|ship\s+it|production\s+push)\b', re.I),
]
_MEMORY_UPDATE_PATTERNS = [
    re.compile(r'\b(ricordati|remember|salva|tieni\s+a\s+mente|memorizza|from\s+now\s+on)\b', re.I),
    re.compile(r'\b(preferisco|voglio\s+sempre|da\s+ora|save\s+this)\b', re.I),
]
_SERVER_PATTERNS = [
    re.compile(r'\b(riavvia|restart|ricarica|reload|stop\s+server|start\s+server)\b', re.I),
    re.compile(r'\b(systemctl|nginx|docker\s+down|docker\s+up|supervisord)\b', re.I),
]
_GITHUB_PATTERNS = [
    re.compile(r'\b(apri\s+pr|crea\s+pr|merge\s+pr|open\s+pr|pull\s+request|push\s+branch)\b', re.I),
    re.compile(r'\b(gh\s+pr|git\s+push|create\s+issue)\b', re.I),
]
_READ_PATTERNS = [
    re.compile(r'\b(controlla|leggi|mostra|lista|ispeziona|check|inspect|show|list|read)\b', re.I),
    re.compile(r'\b(log|status|report|descrivi|explain|analizza)\b', re.I),
]
_CODE_PATTERNS = [
    re.compile(r'\b(fix|correggi|modifica|aggiorna|aggiungere|refactor|implementa)\b', re.I),
    re.compile(r'\b(scrivi\s+codice|write\s+code|create\s+file|patch)\b', re.I),
]


def _classify_shadow_route(message: str) -> tuple[str, str, float]:
    """Returns (shadow_route, shadow_risk, confidence)."""
    msg = message.lower()

    if any(p.search(msg) for p in _DESTRUCTIVE_PATTERNS):
        return "high_risk_operation", "destructive", 0.9
    if any(p.search(msg) for p in _DEPLOY_PATTERNS):
        return "deploy_operation", "high", 0.85
    if any(p.search(msg) for p in _SERVER_PATTERNS):
        return "server_operation", "high", 0.8
    if any(p.search(msg) for p in _GITHUB_PATTERNS):
        return "github_operation", "medium", 0.75
    if any(p.search(msg) for p in _CODE_PATTERNS):
        return "code_change", "medium", 0.7
    if any(p.search(msg) for p in _MEMORY_UPDATE_PATTERNS):
        return "memory_update", "low", 0.8
    if any(p.search(msg) for p in _READ_PATTERNS):
        return "read_only_inspection", "low", 0.75
    return "chat_only", "low", 0.5


# ── IntentRiskShadowModel ─────────────────────────────────────────────────────

class IntentRiskShadowModel:
    """Shadow model for intent/risk classification.

    SAFE: Never modifies baseline_route_decision. shadow_only=True always.
    Risk shadow NEVER downgrades operational policy.
    """

    def __init__(self, project_root: "str | Path | None" = None):
        if project_root is None:
            try:
                from igris.models.config import CONFIG
                project_root = CONFIG.project_root
            except Exception:
                project_root = Path.home()
        self.project_root = Path(project_root)

    def evaluate(
        self,
        message: str,
        *,
        baseline_route_decision: Any = None,
        trust_level: str = "untrusted",
    ) -> ShadowReport:
        """Classify intent/risk in shadow mode. Never modifies baseline."""
        report = ShadowReport(
            report_id=str(uuid.uuid4()),
            kind="intent_risk_shadow",
            query=_redact(str(message)[:500]),
        )

        try:
            shadow_route, shadow_risk, confidence = _classify_shadow_route(message)

            report.shadow_decision = {
                "route": shadow_route,
                "risk": shadow_risk,
                "confidence": confidence,
                "source": ShadowDecisionSource.HEURISTIC.value,
            }

            # Capture baseline (read-only, never modify)
            if baseline_route_decision is not None:
                baseline_route = str(getattr(baseline_route_decision, "route", ""))
                baseline_risk = str(getattr(baseline_route_decision, "risk", ""))
                report.baseline_decision = {
                    "route": baseline_route,
                    "risk": baseline_risk,
                }

                # Check agreement
                route_agrees = shadow_route == baseline_route
                risk_agrees = shadow_risk == baseline_risk
                agreement = route_agrees and risk_agrees

                report.metadata["route_agreement"] = route_agrees
                report.metadata["risk_agreement"] = risk_agrees
                report.metadata["agreement"] = agreement

                if not agreement:
                    report.warnings.append(
                        f"shadow_disagrees_with_baseline: shadow={shadow_route}/{shadow_risk} "
                        f"baseline={baseline_route}/{baseline_risk}"
                    )

                # SAFETY: shadow risk must NEVER operationally downgrade policy
                # We only note disagreement, never act on it
                # changed_decision stays False — baseline is the real decision
                report.changed_decision = False

            report.metrics["shadow_confidence"] = confidence
            report.metrics["trust_level"] = trust_level
            report.ok = True

        except Exception as e:
            logger.warning("IntentRiskShadowModel.evaluate failed: %s", e)
            report.ok = False
            report.warnings.append(f"evaluation_failed: {_redact(str(e))}")

        return report

    def healthcheck(self) -> dict:
        return {"ok": True, "component": "intent_risk_shadow_model"}


# ── StrategySelectorShadow ────────────────────────────────────────────────────

_DEPLOY_ROUTE_RE = re.compile(r'\b(deploy|server_operation|github_operation|high_risk)\b', re.I)
_HIGH_RISK_RE = re.compile(r'\b(destructive|high|critical)\b', re.I)

class StrategySelectorShadow:
    """Shadow strategy selector. Suggests execution strategy but NEVER modifies MissionPlan.

    shadow_only=True, changed_decision=False always.
    """

    STRATEGIES = (
        "chat_only", "plan_only", "read_only", "approval_required",
        "blocked", "dry_run", "verify_first", "reflect_first", "human_review",
    )

    def __init__(self, project_root: "str | Path | None" = None):
        if project_root is None:
            try:
                from igris.models.config import CONFIG
                project_root = CONFIG.project_root
            except Exception:
                project_root = Path.home()
        self.project_root = Path(project_root)

    def suggest_strategy(
        self,
        mission_plan: Any,
        evidence_bundle: Any = None,
        reflection_report: Any = None,
    ) -> ShadowReport:
        """Suggest a strategy. NEVER modifies mission_plan."""
        report = ShadowReport(
            report_id=str(uuid.uuid4()),
            kind="strategy_selector_shadow",
        )

        try:
            strategy = "plan_only"
            reason = "default"

            if mission_plan is not None:
                blocked = getattr(mission_plan, "blocked", False)
                requires_approval = getattr(mission_plan, "requires_approval", False)
                route = str(getattr(mission_plan, "route", ""))
                risk = str(getattr(mission_plan, "risk", ""))
                status = str(getattr(mission_plan, "status", ""))

                if blocked:
                    strategy = "blocked"
                    reason = "mission blocked by security gate"
                elif requires_approval or status == "waiting_approval":
                    strategy = "approval_required"
                    reason = "mission requires explicit approval"
                elif _DEPLOY_ROUTE_RE.search(route) or _HIGH_RISK_RE.search(risk):
                    strategy = "approval_required"
                    reason = f"route={route!r} risk={risk!r} requires approval"
                elif evidence_bundle is not None:
                    bundle_ok = getattr(evidence_bundle, "ok", None)
                    bundle_status = str(getattr(evidence_bundle, "status", ""))
                    if bundle_status == "failed" or bundle_ok is False:
                        strategy = "verify_first"
                        reason = "evidence bundle failed — verify before proceeding"
                    elif bundle_status == "warning":
                        strategy = "reflect_first"
                        reason = "evidence warnings — reflect before proceeding"

            # Override with reflection confidence if available
            if reflection_report is not None and strategy not in ("blocked", "approval_required"):
                confidence = getattr(reflection_report, "confidence", 1.0)
                outcome = str(getattr(reflection_report, "outcome", ""))
                if confidence < 0.5 or outcome == "failure":
                    strategy = "human_review"
                    reason = f"low reflection confidence={confidence:.2f} outcome={outcome}"
                elif outcome == "partial":
                    strategy = "reflect_first"
                    reason = "partial reflection outcome"

            report.shadow_decision = {
                "strategy": strategy,
                "reason": reason,
                "source": ShadowDecisionSource.HEURISTIC.value,
            }
            report.metrics["suggested_strategy"] = strategy
            report.changed_decision = False  # NEVER changes real plan
            report.ok = True

        except Exception as e:
            logger.warning("StrategySelectorShadow.suggest_strategy failed: %s", e)
            report.ok = False
            report.warnings.append(f"strategy_selection_failed: {_redact(str(e))}")

        return report

    def healthcheck(self) -> dict:
        return {"ok": True, "component": "strategy_selector_shadow"}


# ── ShadowMLCoordinator ───────────────────────────────────────────────────────

class ShadowMLCoordinator:
    """Aggregates shadow ML reports from all sub-components.

    Produces a unified ShadowReport. NEVER modifies operational decisions.
    shadow_only=True, changed_decision=False always.
    """

    def __init__(
        self,
        project_root: "str | Path | None" = None,
        unified_memory: Any = None,
    ):
        if project_root is None:
            try:
                from igris.models.config import CONFIG
                project_root = CONFIG.project_root
            except Exception:
                project_root = Path.home()
        self.project_root = Path(project_root)
        self._memory = unified_memory
        self._intent_model = IntentRiskShadowModel(project_root=self.project_root)
        self._strategy_selector = StrategySelectorShadow(project_root=self.project_root)

    def evaluate_request(
        self,
        message: str,
        *,
        route_decision: Any = None,
        memory_items: "list[dict[str, Any]] | None" = None,
        mission_plan: Any = None,
        evidence_bundle: Any = None,
        reflection_report: Any = None,
        trust_level: str = "untrusted",
    ) -> ShadowReport:
        """Aggregate shadow evaluation from intent, ranking, and strategy sub-models."""
        report = ShadowReport(
            report_id=str(uuid.uuid4()),
            kind="shadow_coordinator",
            query=_redact(str(message)[:500]),
        )

        sub_warnings: list[str] = []
        sub_reports: dict[str, Any] = {}

        # 1. Intent/risk shadow
        try:
            intent_report = self._intent_model.evaluate(
                message,
                baseline_route_decision=route_decision,
                trust_level=trust_level,
            )
            sub_reports["intent_risk"] = intent_report.to_dict()
            sub_warnings.extend(intent_report.warnings)
        except Exception as e:
            logger.warning("ShadowMLCoordinator: intent_model failed: %s", e)
            sub_warnings.append(f"intent_risk_degraded: {_redact(str(e))}")
            sub_reports["intent_risk"] = {"ok": False, "error": _redact(str(e))}

        # 2. Strategy shadow
        try:
            strategy_report = self._strategy_selector.suggest_strategy(
                mission_plan, evidence_bundle, reflection_report
            )
            sub_reports["strategy"] = strategy_report.to_dict()
            sub_warnings.extend(strategy_report.warnings)
        except Exception as e:
            logger.warning("ShadowMLCoordinator: strategy_selector failed: %s", e)
            sub_warnings.append(f"strategy_selector_degraded: {_redact(str(e))}")
            sub_reports["strategy"] = {"ok": False, "error": _redact(str(e))}

        # 3. Ranking shadow (via LearningRanker if memory_items provided)
        if memory_items:
            try:
                from igris.core.learning_ranker import LearningRanker
                ranker = LearningRanker(
                    project_root=self.project_root,
                    unified_memory=self._memory,
                )
                rank_report = ranker.rank_items(message, memory_items, shadow_only=True)
                sub_reports["ranking"] = rank_report.to_dict()
                report.scores.extend(rank_report.scores)
                sub_warnings.extend(rank_report.warnings)
            except Exception as e:
                logger.warning("ShadowMLCoordinator: ranker failed: %s", e)
                sub_warnings.append(f"ranking_degraded: {_redact(str(e))}")
                sub_reports["ranking"] = {"ok": False, "error": _redact(str(e))}

        report.metadata["sub_reports"] = sub_reports
        report.warnings = sub_warnings
        report.changed_decision = False  # INVARIANT
        report.shadow_only = True        # INVARIANT

        all_ok = all(
            sr.get("ok", True) if isinstance(sr, dict) else True
            for sr in sub_reports.values()
        )
        report.ok = all_ok
        if not all_ok:
            report.warnings.append("one_or_more_shadow_components_degraded")

        report.metrics["sub_component_count"] = len(sub_reports)
        report.metrics["trust_level"] = trust_level

        return report

    def healthcheck(self) -> dict:
        intent_h = self._intent_model.healthcheck()
        strategy_h = self._strategy_selector.healthcheck()
        all_ok = intent_h.get("ok") and strategy_h.get("ok")
        return {
            "ok": bool(all_ok),
            "intent_risk_shadow": intent_h.get("ok", False),
            "strategy_selector_shadow": strategy_h.get("ok", False),
        }
