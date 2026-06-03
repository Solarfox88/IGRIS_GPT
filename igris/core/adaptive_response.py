"""
Adaptive Response v2 — Layer integration for the Interlocutor-Aware system (issue #526).

Full pipeline: identity → state → intent → auth → judgment → proactive → audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from igris.core.authorization_gate import AuthorizationGate, AuthResult
from igris.core.identity_resolver import InterlocutorProfile, IdentityResolver
from igris.core.intent_resolver import IntentResolver, IntentResolution
from igris.core.interlocutor_audit import InterlocutorAudit
from igris.core.judgment_layer import Advisory, JudgmentLayer, OperationalContext
from igris.core.proactive_engine import ProactiveEngine, ProactiveEvent
from igris.core.state_calibration import StateCalibration, StateSignal, ResponseMode


@dataclass
class InteractionResult:
    """Full result of processing an interlocutor interaction."""
    profile: InterlocutorProfile
    state: StateSignal
    response_mode: ResponseMode
    auth: AuthResult
    intent: Optional[IntentResolution] = None
    advisory: Optional[Advisory] = None
    proactive_events: List[ProactiveEvent] = field(default_factory=list)
    audit_event_id: str = ""

    # ---- convenience properties ----

    @property
    def allowed(self) -> bool:
        return self.auth.allowed

    @property
    def requires_confirmation(self) -> bool:
        return self.advisory.requires_confirmation if self.advisory else False

    @property
    def blocked(self) -> bool:
        return not self.auth.allowed

    @property
    def needs_clarification(self) -> bool:
        return self.intent is not None and self.intent.ambiguous

    def to_dict(self) -> Dict[str, Any]:
        def _safe(v: Any) -> Any:
            if hasattr(v, "__dict__"):
                return {k: _safe(val) for k, val in v.__dict__.items()}
            if isinstance(v, list):
                return [_safe(i) for i in v]
            return v

        return {
            "profile_id": self.profile.profile_id,
            "display_name": self.profile.display_name,
            "trust_level": self.profile.trust_level,
            "state": _safe(self.state),
            "response_mode": _safe(self.response_mode),
            "allowed": self.allowed,
            "blocked": self.blocked,
            "needs_clarification": self.needs_clarification,
            "requires_confirmation": self.requires_confirmation,
            "auth_reason": self.auth.reason,
            "auth_message": self.auth.message,
            "intent": _safe(self.intent) if self.intent else None,
            "advisory": _safe(self.advisory) if self.advisory else None,
            "proactive_events": [_safe(e) for e in self.proactive_events],
            "audit_event_id": self.audit_event_id,
        }


class AdaptiveResponse:
    """Layer 1-7 integration: process a user message end-to-end."""

    def __init__(self, project_root: str, audit_path: str | None = None) -> None:
        self.project_root = project_root
        self._identity = IdentityResolver(project_root)
        self._auth_gate = AuthorizationGate(project_root)
        self._state_cal = StateCalibration()
        self._judgment = JudgmentLayer()
        self._proactive = ProactiveEngine(project_root)
        self._intent_resolver = IntentResolver()
        self._audit = InterlocutorAudit(audit_path)

    def process(
        self,
        interlocutor_name: str,
        message: str,
        action_type: str = "",
        target_resource: str = "",
        operational_context: Optional[OperationalContext] = None,
        state_snapshot: Optional[Dict[str, Any]] = None,
        delegation_key_id: Optional[str] = None,
        delegation_key_passphrase: Optional[str] = None,
    ) -> InteractionResult:
        # 1. Identity
        profile = self._identity.resolve(interlocutor_name)
        self._identity.update(profile)

        # 2. State
        state = self._state_cal.detect(message)
        response_mode = self._state_cal.select_response_mode(
            state,
            communication_style=profile.communication_style,
            expertise_level=profile.expertise_level,
        )

        # 3. Intent (resolve from message when action_type not given)
        intent: Optional[IntentResolution] = None
        resolved_action = action_type
        resolved_target = target_resource
        if not action_type:
            intent = self._intent_resolver.resolve(
                message, state_urgency=None
            )
            resolved_action = intent.action_type
            resolved_target = intent.target_resource if intent.target_resource != "unknown" else target_resource

        # 4. Ambiguous → clarification, no action
        if intent and intent.ambiguous:
            auth = AuthResult(
                allowed=False,
                reason="needs_clarification",
                message=intent.clarification_question or "Please clarify your request.",
            )
            audit_id = self._audit.record(
                "needs_clarification",
                interlocutor_id=profile.profile_id,
                display_name=profile.display_name,
                trust_level=profile.trust_level,
                action_type=resolved_action,
                target_resource=resolved_target,
                decision="deferred",
                reason="ambiguous_intent",
            )
            return InteractionResult(
                profile=profile,
                state=state,
                response_mode=response_mode,
                auth=auth,
                intent=intent,
                audit_event_id=audit_id,
            )

        # 5. Authorization
        auth = self._auth_gate.check(
            profile=profile,
            action_type=resolved_action,
            target_resource=resolved_target,
            delegation_key_id=delegation_key_id,
            delegation_key_passphrase=delegation_key_passphrase,
        )

        # 6. Denied → audit + return
        if not auth.allowed:
            audit_id = self._audit.record(
                "auth_denied",
                interlocutor_id=profile.profile_id,
                display_name=profile.display_name,
                trust_level=profile.trust_level,
                action_type=resolved_action,
                target_resource=resolved_target,
                decision="denied",
                reason=auth.reason,
            )
            return InteractionResult(
                profile=profile,
                state=state,
                response_mode=response_mode,
                auth=auth,
                intent=intent,
                audit_event_id=audit_id,
            )

        # 7. Judgment advisory
        advisory: Optional[Advisory] = None
        ctx = operational_context or OperationalContext()
        advisory = self._judgment.advise(
            action_type=resolved_action,
            target_resource=resolved_target,
            context=ctx,
            trust_level=profile.trust_level,
        )

        # 8. Proactive scan
        proactive: List[ProactiveEvent] = []
        if state_snapshot:
            try:
                proactive = self._proactive.scan(
                    state_snapshot=state_snapshot,
                    authorized_scopes=profile.authorized_scopes or None,
                    trust_level=profile.trust_level,
                )
            except Exception:
                pass

        # 9. Persist profile in memory graph (best-effort)
        try:
            self._identity.persist_to_memory_graph(profile)
        except Exception:
            pass

        # 10. Full audit
        audit_id = self._audit.record(
            "auth_allowed",
            interlocutor_id=profile.profile_id,
            display_name=profile.display_name,
            trust_level=profile.trust_level,
            action_type=resolved_action,
            target_resource=resolved_target,
            decision="allowed",
            reason=auth.reason,
            extra={
                "advisory_proceed": advisory.should_proceed if advisory else True,
                "proactive_count": len(proactive),
                "requires_confirmation": advisory.requires_confirmation if advisory else False,
            },
        )

        return InteractionResult(
            profile=profile,
            state=state,
            response_mode=response_mode,
            auth=auth,
            intent=intent,
            advisory=advisory,
            proactive_events=proactive,
            audit_event_id=audit_id,
        )
