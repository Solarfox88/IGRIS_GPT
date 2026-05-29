"""
Adaptive Response — Layer integration for the Interlocutor-Aware system (issue #526).

Single interface combining all 7 layers. Never raises.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from igris.core.authorization_gate import AuthorizationGate, AuthResult
from igris.core.identity_resolver import InterlocutorProfile, IdentityResolver
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
    advisory: Optional[Advisory] = None
    proactive_events: List[ProactiveEvent] = field(default_factory=list)


class AdaptiveResponse:
    """Layer 1-7 integration: process a user message end-to-end."""

    def __init__(self, project_root: str) -> None:
        self.project_root = project_root
        self._identity = IdentityResolver(project_root)
        self._auth_gate = AuthorizationGate(project_root)
        self._state_cal = StateCalibration()
        self._judgment = JudgmentLayer()
        self._proactive = ProactiveEngine(project_root)

    def process(
        self,
        interlocutor_name: str,
        message: str,
        action_type: str,
        target_resource: str,
        operational_context: Optional[OperationalContext] = None,
        state_snapshot: Optional[Dict[str, Any]] = None,
        delegation_key_id: Optional[str] = None,
        delegation_key_passphrase: Optional[str] = None,
    ) -> InteractionResult:
        profile = self._identity.resolve(interlocutor_name)
        self._identity.update(profile)

        state = self._state_cal.detect(message)
        response_mode = self._state_cal.select_response_mode(
            state,
            communication_style=profile.communication_style,
            expertise_level=profile.expertise_level,
        )

        auth = self._auth_gate.check(
            profile=profile,
            action_type=action_type,
            target_resource=target_resource,
            delegation_key_id=delegation_key_id,
            delegation_key_passphrase=delegation_key_passphrase,
        )

        advisory: Optional[Advisory] = None
        if auth.allowed:
            ctx = operational_context or OperationalContext()
            advisory = self._judgment.advise(
                action_type=action_type,
                target_resource=target_resource,
                context=ctx,
                trust_level=profile.trust_level,
            )

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

        return InteractionResult(
            profile=profile,
            state=state,
            response_mode=response_mode,
            auth=auth,
            advisory=advisory,
            proactive_events=proactive,
        )
