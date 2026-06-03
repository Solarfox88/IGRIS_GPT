"""Chat interlocutor preflight — runs before every chat_llm() call.

Implements the full interlocutor-aware pipeline for conversational entry points
as part of issue #526.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PreflightResult:
    interlocutor_id: str
    trust_level: str
    response_mode: dict
    intent_action: str
    intent_risk: str
    blocked: bool
    block_reason: str | None
    requires_clarification: bool
    clarification_question: str | None
    advisory: str | None
    system_prompt_enrichment: str
    audit_event_id: str | None = None

    @property
    def allowed(self) -> bool:
        return not self.blocked and not self.requires_clarification


SENSITIVE_CHAT_ACTIONS = {
    "deploy", "delete", "rollback", "merge_pr", "close_issue",
    "run_command", "network_diagnostic", "github_write", "github_admin",
    "browser_operation", "override", "restart_server",
}


def run_preflight(
    message: str,
    interlocutor_id: str | None = None,
    project_root: str | None = None,
) -> PreflightResult:
    """Full interlocutor-aware preflight for a chat message."""
    from pathlib import Path

    # 1. Resolve identity
    _id = interlocutor_id or "unknown"
    profile = None
    trust_level = "untrusted"
    try:
        from igris.core.identity_resolver import IdentityResolver
        root = project_root or str(Path.home())
        ir = IdentityResolver(root)
        profile = ir.resolve(_id)
        trust_level = str(getattr(profile, "trust_level", "untrusted")).lower()
        if hasattr(profile, "touch"):
            profile.touch()
    except Exception:
        pass

    # 2. Detect state
    response_mode: dict = {
        "verbosity": "normal",
        "tone": "professional",
        "lead_with_action": False,
        "use_bullet_points": False,
        "simplify_language": False,
    }
    try:
        from igris.core.state_calibration import StateCalibration
        sc = StateCalibration()
        state = sc.detect(message)
        expertise = getattr(profile, "expertise_level", "intermediate") if profile else "intermediate"
        style = getattr(profile, "communication_style", "technical") if profile else "technical"
        mode = sc.select_response_mode(state, communication_style=style, expertise_level=expertise)
        response_mode = {
            "verbosity": mode.verbosity,
            "tone": mode.tone,
            "lead_with_action": mode.lead_with_action,
            "use_bullet_points": mode.use_bullet_points,
            "simplify_language": mode.simplify_language,
        }
    except Exception:
        pass

    # 3. Resolve intent
    intent_action = "unknown"
    intent_risk = "low"
    ambiguous = False
    clarification_question = None
    try:
        from igris.core.intent_resolver import IntentResolver
        ir2 = IntentResolver()
        intent = ir2.resolve(message)
        intent_action = intent.action_type
        intent_risk = intent.risk_hint
        ambiguous = intent.ambiguous
        clarification_question = intent.clarification_question
    except Exception:
        pass

    # 4. Authorization for action-like intents
    blocked = False
    block_reason = None
    advisory = None

    is_sensitive = intent_action in SENSITIVE_CHAT_ACTIONS or intent_risk in ("high", "destructive")
    is_untrusted = trust_level in ("untrusted", "unknown", "")

    if is_sensitive and is_untrusted:
        blocked = True
        block_reason = (
            f"Action '{intent_action}' (risk: {intent_risk}) denied for unrecognized interlocutor. "
            "Please identify yourself or provide a delegation key."
        )
    elif is_sensitive and not is_untrusted:
        advisory = (
            f"Action '{intent_action}' is sensitive (risk: {intent_risk}). "
            "Proceeding with authorization."
        )

    # 5. Build system prompt enrichment (no secrets)
    profile_summary = ""
    if profile:
        expertise = getattr(profile, "expertise_level", "unknown")
        style = getattr(profile, "communication_style", "neutral")
        profile_summary = (
            f"\n[INTERLOCUTOR CONTEXT]\n"
            f"Identity: {_id} | Trust: {trust_level} | Expertise: {expertise} | Style: {style}\n"
            f"Response mode: verbosity={response_mode.get('verbosity', 'normal')}, "
            f"tone={response_mode.get('tone', 'professional')}, "
            f"simplify={response_mode.get('simplify_language', False)}\n"
        )

    # 6. Audit
    audit_event_id = None
    try:
        from igris.core.interlocutor_audit import InterlocutorAudit
        audit = InterlocutorAudit()
        event_type = (
            "auth_denied" if blocked
            else ("auth_allowed" if is_sensitive else "identity_resolved")
        )
        audit_event_id = audit.record(
            event_type=event_type,
            interlocutor_id=_id,
            display_name=str(getattr(profile, "display_name", _id)),
            trust_level=trust_level,
            action_type=intent_action,
            target_resource="chat",
            decision="denied" if blocked else "allowed",
            reason=block_reason or advisory or "chat message",
        )
    except Exception:
        pass

    return PreflightResult(
        interlocutor_id=_id,
        trust_level=trust_level,
        response_mode=response_mode,
        intent_action=intent_action,
        intent_risk=intent_risk,
        blocked=blocked,
        block_reason=block_reason,
        requires_clarification=ambiguous and is_sensitive,
        clarification_question=clarification_question if (ambiguous and is_sensitive) else None,
        advisory=advisory,
        system_prompt_enrichment=profile_summary,
        audit_event_id=audit_event_id,
    )


def extract_interlocutor_id(
    payload: dict | None = None,
    headers: dict | None = None,
) -> str | None:
    """Extract interlocutor_id from request payload or headers."""
    if payload:
        v = payload.get("interlocutor_id") or payload.get("user_id")
        if v:
            return str(v)
    if headers:
        # Headers are case-insensitive in HTTP but dict lookup is case-sensitive
        for key in ("x-igris-interlocutor", "X-IGRIS-Interlocutor", "X-Igris-Interlocutor"):
            v = headers.get(key)
            if v:
                return str(v)
    return None
