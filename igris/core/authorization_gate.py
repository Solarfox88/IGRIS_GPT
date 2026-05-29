"""
Authorization Gate — Layer 4 of the Interlocutor-Aware system (issue #526).

Deny-by-default engine. Never raises — returns a structured AuthResult.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from igris.core.identity_resolver import InterlocutorProfile


@dataclass
class AuthResult:
    """Result of an authorization check."""
    allowed: bool
    reason: str
    message: str = ""
    warn_destructive: bool = False
    requires_delegation_key: bool = False
    authorized_scopes: List[str] = field(default_factory=list)


_DESTRUCTIVE_ACTIONS = frozenset([
    "delete_branch", "force_push", "drop_database", "wipe_storage",
    "terminate_process", "remove_file", "reset_hard", "revert_migration",
])


class AuthorizationGate:
    """Deny-by-default authorization engine."""

    def __init__(self, project_root: str) -> None:
        self.project_root = project_root

    def check(
        self,
        profile: InterlocutorProfile,
        action_type: str,
        target_resource: str,
        delegation_key_id: Optional[str] = None,
        delegation_key_passphrase: Optional[str] = None,
    ) -> AuthResult:
        is_destructive = action_type in _DESTRUCTIVE_ACTIONS

        if profile.trust_level == "admin":
            return AuthResult(
                allowed=True,
                reason="admin_bypass",
                message=f"Admin '{profile.display_name}' authorized for {action_type} on {target_resource}.",
                warn_destructive=is_destructive,
                authorized_scopes=profile.authorized_scopes,
            )

        scope_ok = (
            target_resource in profile.authorized_scopes
            or action_type in profile.authorized_scopes
            or "*" in profile.authorized_scopes
        )
        if scope_ok:
            return AuthResult(
                allowed=True,
                reason="scope_match",
                message=f"'{profile.display_name}' has scope for {target_resource}.",
                warn_destructive=is_destructive,
                authorized_scopes=profile.authorized_scopes,
            )

        if delegation_key_id and delegation_key_passphrase:
            return self._check_delegation_key(
                profile=profile,
                action_type=action_type,
                target_resource=target_resource,
                key_id=delegation_key_id,
                passphrase=delegation_key_passphrase,
                is_destructive=is_destructive,
            )

        return AuthResult(
            allowed=False,
            reason="scope_denied",
            message=(
                f"'{profile.display_name}' is not authorized for '{target_resource}'. "
                "If you have been granted a delegation key, provide it to proceed."
            ),
            requires_delegation_key=True,
        )

    def _check_delegation_key(
        self,
        profile: InterlocutorProfile,
        action_type: str,
        target_resource: str,
        key_id: str,
        passphrase: str,
        is_destructive: bool,
    ) -> AuthResult:
        try:
            from igris.core.delegation_keys import verify_key
            ok, reason = verify_key(
                project_root=self.project_root,
                key_id=key_id,
                raw_passphrase=passphrase,
                requested_scopes=[target_resource],
                bearer=profile.profile_id,
            )
            if ok:
                return AuthResult(
                    allowed=True,
                    reason="delegation_key_accepted",
                    message=f"Delegation key verified for '{target_resource}'.",
                    warn_destructive=is_destructive,
                    authorized_scopes=[target_resource],
                )
            return AuthResult(
                allowed=False,
                reason=f"delegation_key_rejected:{reason}",
                message=f"Delegation key rejected: {reason}.",
            )
        except Exception as e:
            return AuthResult(
                allowed=False,
                reason="delegation_key_error",
                message=f"Delegation key verification error: {e}",
            )

    def check_multiple_scopes(
        self,
        profile: InterlocutorProfile,
        scopes: List[str],
    ) -> Dict[str, bool]:
        result = {}
        for scope in scopes:
            ar = self.check(profile, action_type="access", target_resource=scope)
            result[scope] = ar.allowed
        return result
