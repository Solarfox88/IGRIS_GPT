"""Mission-first Execution Integration (#1245).

Transforms operational requests into structured mission plans with
tracked status, approval policy, and audit trail.

The controller PLANS and TRACKS — it does NOT auto-execute dangerous operations.
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


def _redact_dict(d: Any) -> Any:
    if isinstance(d, dict):
        return {k: _redact_dict(v) for k, v in d.items()}
    elif isinstance(d, list):
        return [_redact_dict(i) for i in d]
    elif isinstance(d, str):
        return _redact(d)
    return d


# ── Enums ─────────────────────────────────────────────────────────────────────

class MissionExecutionMode(str, Enum):
    PLAN_ONLY = "plan_only"
    DRY_RUN = "dry_run"
    READ_ONLY = "read_only"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED = "blocked"


class MissionStatus(str, Enum):
    PLANNED = "planned"
    WAITING_APPROVAL = "waiting_approval"
    BLOCKED = "blocked"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ── Route classification ───────────────────────────────────────────────────────

# Routes that require a mission plan
_MISSION_ROUTES = {
    "read_only_inspection",
    "project_reasoning",
    "code_change",
    "server_operation",
    "github_operation",
    "deploy_operation",
    "high_risk_operation",
}

# Routes that do NOT create missions
_NON_MISSION_ROUTES = {
    "chat_only",
    "memory_update",
    "unknown_requires_clarification",
    "blocked",
}

# Execution mode policy per route
_ROUTE_EXECUTION_MODE = {
    "read_only_inspection": MissionExecutionMode.READ_ONLY,
    "project_reasoning": MissionExecutionMode.PLAN_ONLY,
    "code_change": MissionExecutionMode.APPROVAL_REQUIRED,
    "server_operation": MissionExecutionMode.APPROVAL_REQUIRED,
    "github_operation": MissionExecutionMode.APPROVAL_REQUIRED,
    "deploy_operation": MissionExecutionMode.APPROVAL_REQUIRED,
    "high_risk_operation": MissionExecutionMode.APPROVAL_REQUIRED,
}


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class MissionStep:
    step_id: str
    title: str
    description: str = ""
    action_type: str = "analysis"   # analysis | read_only | code_change | github | server | deploy
    risk: str = "low"
    status: str = "planned"
    requires_approval: bool = False
    dry_run_only: bool = True
    evidence_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return _redact_dict({
            "step_id": self.step_id,
            "title": self.title,
            "description": self.description,
            "action_type": self.action_type,
            "risk": self.risk,
            "status": self.status,
            "requires_approval": self.requires_approval,
            "dry_run_only": self.dry_run_only,
            "evidence_refs": self.evidence_refs,
            "warnings": self.warnings,
        })


@dataclass
class MissionPlan:
    mission_id: str
    title: str
    route: str
    risk: str
    status: str
    execution_mode: str
    query: str = ""
    interlocutor_id: str = "unknown"
    trust_level: str = "untrusted"
    requires_approval: bool = False
    blocked: bool = False
    reason: str = ""
    steps: list[MissionStep] = field(default_factory=list)
    context_summary: str = ""
    warnings: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return _redact_dict({
            "mission_id": self.mission_id,
            "title": self.title,
            "route": self.route,
            "risk": self.risk,
            "status": self.status,
            "execution_mode": self.execution_mode,
            "query": self.query,
            "interlocutor_id": self.interlocutor_id,
            "trust_level": self.trust_level,
            "requires_approval": self.requires_approval,
            "blocked": self.blocked,
            "reason": self.reason,
            "steps": [s.to_dict() for s in self.steps],
            "context_summary": self.context_summary,
            "warnings": self.warnings,
            "evidence_refs": self.evidence_refs,
            "created_at": self.created_at,
        })


# ── MissionFirstController ────────────────────────────────────────────────────

class MissionFirstController:
    """Transforms route decisions into structured mission plans.

    Plans and tracks — does NOT auto-execute dangerous operations.
    """

    def __init__(
        self,
        project_root: str | Path | None = None,
        unified_memory=None,
        context_aggregator=None,
        mission_controller=None,
    ):
        if project_root is None:
            try:
                from igris.models.config import CONFIG
                project_root = CONFIG.project_root
            except Exception:
                project_root = Path.home()
        self.project_root = Path(project_root)
        self._memory = unified_memory
        self._context_aggregator = context_aggregator
        self._mission_controller = mission_controller

    def _get_memory(self):
        if self._memory is None:
            try:
                from igris.core.unified_memory import UnifiedMemory
                self._memory = UnifiedMemory(project_root=self.project_root)
            except Exception as e:
                logger.debug("MissionFirstController: UnifiedMemory unavailable: %s", e)
        return self._memory

    def _get_context_aggregator(self):
        if self._context_aggregator is None:
            try:
                from igris.core.context_aggregator import ContextAggregator
                self._context_aggregator = ContextAggregator(
                    project_root=self.project_root,
                    unified_memory=self._get_memory(),
                )
            except Exception as e:
                logger.debug("MissionFirstController: ContextAggregator unavailable: %s", e)
        return self._context_aggregator

    def should_create_mission(self, route_decision) -> bool:
        """Returns True if this route requires a mission plan."""
        if route_decision is None:
            return False
        route = getattr(route_decision, "route", "")
        if hasattr(route, "value"):
            route = route.value
        return str(route) in _MISSION_ROUTES

    def build_plan(
        self,
        message: str,
        *,
        route_decision,
        interlocutor_id: str = "unknown",
        trust_level: str = "untrusted",
        session_id: str = "",
        source: str = "chat",
        dry_run: bool = True,
    ) -> MissionPlan:
        """Build a MissionPlan from a route decision."""
        now = datetime.now(timezone.utc).isoformat()
        mission_id = str(uuid.uuid4())
        warnings: list[str] = []

        # Extract route info
        route = str(getattr(route_decision, "route", "unknown"))
        if hasattr(getattr(route_decision, "route", ""), "value"):
            route = route_decision.route.value
        risk = str(getattr(route_decision, "risk", "low"))
        if hasattr(getattr(route_decision, "risk", ""), "value"):
            risk = route_decision.risk.value
        is_blocked = getattr(route_decision, "blocked", False)
        requires_approval = getattr(route_decision, "requires_approval", False)

        # Determine execution mode
        if is_blocked:
            execution_mode = MissionExecutionMode.BLOCKED
            status = MissionStatus.BLOCKED
        elif requires_approval:
            execution_mode = MissionExecutionMode.APPROVAL_REQUIRED
            status = MissionStatus.WAITING_APPROVAL
        else:
            execution_mode = _ROUTE_EXECUTION_MODE.get(route, MissionExecutionMode.PLAN_ONLY)
            status = MissionStatus.PLANNED

        if dry_run and execution_mode not in (MissionExecutionMode.BLOCKED,
                                               MissionExecutionMode.READ_ONLY,
                                               MissionExecutionMode.APPROVAL_REQUIRED):
            execution_mode = MissionExecutionMode.DRY_RUN
        # Note: APPROVAL_REQUIRED stays APPROVAL_REQUIRED even with dry_run=True

        # Build mission title
        title = _redact(f"Mission: {route} — {message[:60]}")

        # Context summary (only for non-blocked missions)
        context_summary = ""
        if not is_blocked:
            agg = self._get_context_aggregator()
            if agg:
                try:
                    brief = agg.build_context(
                        query=message,
                        interlocutor_id=interlocutor_id,
                        trust_level=trust_level,
                        route_decision=route_decision,
                        include_rank=False,
                        max_chars=2000,
                    )
                    context_summary = _redact(brief.brief_text[:500] if hasattr(brief, "brief_text") else "")
                    warnings.extend(brief.warnings[:3] if hasattr(brief, "warnings") else [])
                except Exception as e:
                    warnings.append(f"context_aggregation_degraded: {e}")
                    logger.warning("MissionFirstController: context aggregation failed: %s", e)

        # Build steps
        steps = self._build_steps(
            route, risk, requires_approval,
            execution_mode.value if hasattr(execution_mode, "value") else str(execution_mode),
        )

        plan = MissionPlan(
            mission_id=mission_id,
            title=title,
            route=route,
            risk=risk,
            status=status.value if hasattr(status, "value") else str(status),
            execution_mode=execution_mode.value if hasattr(execution_mode, "value") else str(execution_mode),
            query=_redact(message),
            interlocutor_id=interlocutor_id,
            trust_level=trust_level,
            requires_approval=requires_approval,
            blocked=is_blocked,
            reason=_redact(getattr(route_decision, "reason", "") or ""),
            steps=steps,
            context_summary=context_summary,
            warnings=warnings,
            created_at=now,
            metadata={
                "session_id": session_id,
                "source": source,
                "dry_run": dry_run,
            },
        )
        return plan

    def _build_steps(self, route: str, risk: str, requires_approval: bool,
                     execution_mode: str) -> list[MissionStep]:
        """Build default steps based on route type."""
        steps: list[MissionStep] = []

        def make_step(title: str, action_type: str, r: str = "low",
                      req_approval: bool = False, dry_only: bool = True,
                      description: str = "") -> MissionStep:
            return MissionStep(
                step_id=str(uuid.uuid4()),
                title=title,
                description=description,
                action_type=action_type,
                risk=r,
                requires_approval=req_approval,
                dry_run_only=dry_only,
            )

        if route == "read_only_inspection":
            steps = [
                make_step("Collect operational context", "analysis",
                          description="Gather logs, state, reports"),
                make_step("Inspect data (read-only)", "read_only",
                          description="Read-only inspection of target"),
                make_step("Synthesize findings", "analysis",
                          description="Summarize findings safely"),
            ]
        elif route == "project_reasoning":
            steps = [
                make_step("Collect context brief", "analysis",
                          description="Build Personal OS Brief"),
                make_step("Analyze constraints and gaps", "analysis",
                          description="Identify blockers and gaps"),
                make_step("Propose strategy", "analysis",
                          description="Draft recommendations"),
            ]
        elif route == "code_change":
            steps = [
                make_step("Analyze codebase", "analysis",
                          description="Understand target code"),
                make_step("Plan changes", "analysis",
                          description="Draft change plan"),
                make_step("Apply patch (gated)", "code_change", r="medium",
                          req_approval=True, dry_only=True,
                          description="Apply only after explicit approval"),
                make_step("Run tests", "read_only",
                          description="Verify changes"),
            ]
        elif route == "github_operation":
            steps = [
                make_step("Inspect GitHub state", "read_only",
                          description="Read PR/issue/branch state"),
                make_step("Plan GitHub action", "analysis",
                          description="Draft the intended operation"),
                make_step("Execute GitHub action (gated)", "github", r="high",
                          req_approval=True, dry_only=True,
                          description="Only after explicit approval"),
            ]
        elif route == "server_operation":
            steps = [
                make_step("Inspect server state", "read_only",
                          description="Check server health/status"),
                make_step("Plan server operation", "analysis",
                          description="Define the action"),
                make_step("Execute server operation (gated)", "server", r="high",
                          req_approval=True, dry_only=True,
                          description="Only after explicit approval"),
            ]
        elif route == "deploy_operation":
            steps = [
                make_step("Pre-deploy check", "read_only",
                          description="Verify CI/CD state"),
                make_step("Deploy plan", "analysis",
                          description="Define deploy parameters"),
                make_step("Execute deploy (gated)", "deploy", r="high",
                          req_approval=True, dry_only=True,
                          description="REQUIRES EXPLICIT APPROVAL"),
            ]
        elif route == "high_risk_operation":
            steps = [
                make_step("Risk assessment", "analysis", r="destructive",
                          description="Evaluate risk impact"),
                make_step("Blocked — requires override", "analysis", r="destructive",
                          req_approval=True, dry_only=True,
                          description="High-risk operation blocked until explicit override"),
            ]

        return steps

    def persist_mission_plan(self, plan: MissionPlan) -> dict:
        """Persist mission plan to UnifiedMemory as run event.

        Returns {"ok": True} only if storage wrote successfully.
        """
        mem = self._get_memory()
        if mem is None:
            return {"ok": False, "reason": "unified_memory_unavailable",
                    "persistence_degraded": True}

        try:
            result = mem.store_run_event(
                mission_id=plan.mission_id,
                action=f"mission_plan:{plan.route}",
                status=plan.status,
                outcome=f"mode={plan.execution_mode} risk={plan.risk}",
                project="jarvis_core",
            )
            if result.ok:
                return {"ok": True, "mission_id": plan.mission_id,
                        "backend": result.backends}
            else:
                plan.warnings.append(f"persistence_degraded: {result.warnings}")
                logger.warning(
                    "MissionFirstController: persist_mission_plan store_run_event returned ok=False: %s",
                    result.warnings,
                )
                return {"ok": False, "reason": "store_run_event returned ok=False",
                        "persistence_degraded": True, "warnings": result.warnings}
        except Exception as e:
            plan.warnings.append(f"persistence_failed: {e}")
            logger.warning("MissionFirstController: persist_mission_plan failed: %s", e)
            return {"ok": False, "reason": str(e), "persistence_degraded": True}

    def to_response_payload(self, plan: MissionPlan, persist_result: dict | None = None) -> dict:
        """Build JSON-safe response payload for chat/API."""
        response_text = self._build_response_text(plan)
        payload = {
            "response": _redact(response_text),
            "mission": plan.to_dict(),
            "blocked": plan.blocked,
            "requires_approval": plan.requires_approval,
            "provider": "mission_first",
            "model": "mission_planner",
            "fallback_used": False,
            "latency_ms": 0,
            "intent_detected": plan.route,
            "suggested_actions": [],
        }
        if persist_result and persist_result.get("persistence_degraded"):
            payload["persistence_degraded"] = True
        return payload

    def _build_response_text(self, plan: MissionPlan) -> str:
        if plan.blocked:
            return (
                f"Operazione bloccata: {plan.reason or plan.route}. "
                "Non e' possibile procedere con questa richiesta."
            )
        if plan.requires_approval:
            return (
                f"Piano missione creato ({plan.route}). "
                "Questa operazione richiede approvazione esplicita prima dell'esecuzione. "
                f"ID missione: {plan.mission_id[:8]}."
            )
        if plan.execution_mode in ("plan_only", "dry_run"):
            return (
                f"Piano creato ({plan.route}, {plan.execution_mode}). "
                f"{len(plan.steps)} step pianificati. "
                "Nessuna azione reale eseguita."
            )
        if plan.execution_mode == "read_only":
            return (
                f"Missione read-only avviata ({plan.route}). "
                "Raccolta contesto e ispezione in sola lettura."
            )
        return f"Piano missione creato: {plan.route} (mode={plan.execution_mode})"

    def verify_plan(self, plan: "MissionPlan") -> "EvidenceBundle":
        """Verify a MissionPlan using the VerifierRegistry."""
        from igris.core.verifier_registry import EvidenceBundle, VerifierRegistry
        registry = VerifierRegistry(
            project_root=self.project_root,
            unified_memory=self._get_memory(),
            context_aggregator=self._get_context_aggregator(),
        )
        return registry.verify_mission(plan, persist=True)

    def reflect_plan(self, plan, evidence_bundle, user_feedback: str = ""):
        """Run After Action Review on completed mission."""
        try:
            from igris.core.after_action_review import AfterActionReviewer
            reviewer = AfterActionReviewer(
                project_root=self.project_root,
                unified_memory=self._get_memory(),
            )
            return reviewer.review(plan, evidence_bundle, user_feedback=user_feedback)
        except Exception as e:
            import logging as _log
            _log.getLogger(__name__).warning("reflect_plan failed: %s", e)
            return None

    def learn_from_plan(self, plan, evidence_bundle, user_feedback: str = ""):
        """Reflect + apply learning signals from mission."""
        try:
            from igris.core.learning_feedback import LearningFeedbackApplier
            report = self.reflect_plan(plan, evidence_bundle, user_feedback=user_feedback)
            if report is None:
                return None
            applier = LearningFeedbackApplier(
                project_root=self.project_root,
                unified_memory=self._get_memory(),
            )
            return applier.apply_report(report)
        except Exception as e:
            import logging as _log
            _log.getLogger(__name__).warning("learn_from_plan failed: %s", e)
            return None

    def healthcheck(self) -> dict:
        status: dict[str, str] = {}
        mem = self._get_memory()
        status["unified_memory"] = "ok" if mem else "unavailable"
        agg = self._get_context_aggregator()
        status["context_aggregator"] = "ok" if agg else "unavailable"
        status["mission_controller"] = "ok" if self._mission_controller else "unavailable"
        ok = all(v in ("ok", "unavailable") for v in status.values())
        return {
            "ok": ok,
            "backends": status,
            "warnings": [f"{k}: {v}" for k, v in status.items() if v == "degraded"],
        }
