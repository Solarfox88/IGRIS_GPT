"""
Action Guard — lightweight runtime enforcement of identity/authorization
before sensitive operations (issue #526).
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

SENSITIVE_ACTION_TYPES = frozenset({
    "write_file", "edit_file", "run_command", "github_write", "github_admin",
    "deploy", "rollback", "delete", "network_scan", "browser_operation", "override",
})

_PROJECT_ROOT = os.environ.get("IGRIS_PROJECT_ROOT", ".")


def _get_gate():
    from igris.core.authorization_gate import AuthorizationGate
    return AuthorizationGate(_PROJECT_ROOT)


def _get_resolver():
    from igris.core.identity_resolver import IdentityResolver
    return IdentityResolver(_PROJECT_ROOT)


def _get_audit():
    from igris.core.interlocutor_audit import InterlocutorAudit
    return InterlocutorAudit()


def check_action(
    action_type: str,
    profile_id: str = "unknown",
    scope: Optional[str] = None,
) -> Tuple[bool, str]:
    """Returns (allowed, reason). Deny-by-default for sensitive actions."""
    if action_type not in SENSITIVE_ACTION_TYPES:
        return True, "non-sensitive"

    try:
        resolver = _get_resolver()
        profile = resolver.resolve(profile_id)
    except Exception:
        profile = None

    audit = _get_audit()

    if profile is None or profile.trust_level == "untrusted":
        audit.record(
            "unknown_interlocutor_denied",
            interlocutor_id=profile_id,
            action_type=action_type,
            decision="denied",
            reason="unknown or untrusted profile",
        )
        return False, "unknown or untrusted interlocutor — access denied by default"

    required_scope = scope or action_type
    try:
        gate = _get_gate()
        result = gate.check(profile, action_type=action_type, target_resource=required_scope)
    except Exception as e:
        audit.record(
            "auth_error",
            interlocutor_id=profile_id,
            action_type=action_type,
            decision="denied",
            reason=str(e),
        )
        return False, f"authorization error: {e}"

    audit.record(
        "auth_allowed" if result.allowed else "auth_denied",
        interlocutor_id=profile_id,
        display_name=getattr(profile, "display_name", ""),
        trust_level=str(getattr(profile, "trust_level", "")),
        action_type=action_type,
        target_resource=required_scope,
        decision="allowed" if result.allowed else "denied",
        reason=getattr(result, "reason", ""),
    )

    return result.allowed, getattr(result, "reason", "")
