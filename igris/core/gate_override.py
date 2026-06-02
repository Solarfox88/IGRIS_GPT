"""OTP-based gate override with audit trail and physical approval.

Moved from long_term_memory.py as part of #1129 cleanup — OTPRecord
and GateOverride are gate/security concerns, not memory concerns.
"""

from __future__ import annotations

import random
import string
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class OTPRecord:
    """A one-time password record for gate override."""
    code: str = ""
    user: str = ""
    scope: str = "global"
    mission_id: str = ""
    reason: str = ""
    created_at: float = field(default_factory=time.time)
    ttl: float = 300.0
    used: bool = False
    physically_approved: bool = False
    approved_by: str = ""
    revoked_at: float = 0.0
    revoked_reason: str = ""

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl


class GateOverride:
    """OTP-based gate override with audit trail and physical approval support."""

    MAX_TTL_SECONDS = 15 * 60

    def __init__(self) -> None:
        self._records: Dict[str, OTPRecord] = {}
        self._audit: List[Dict[str, Any]] = []

    def _audit_event(self, action: str, **fields: Any) -> None:
        event = {"action": action, "ts": time.time()}
        event.update(fields)
        self._audit.append(event)

    def reset(self) -> None:
        """Clear all override state. Primarily used by tests and maintenance."""
        self._records.clear()
        self._audit.clear()

    def _revoke_record(self, code: str, reason: str) -> bool:
        record = self._records.get(code)
        if record is None or record.revoked_at:
            return False
        record.revoked_at = time.time()
        record.revoked_reason = reason
        self._audit_event("revoked", code=code, scope=record.scope, reason=reason)
        return True

    def revoke_expired(self) -> List[str]:
        """Revoke all expired, still-active records and return their codes."""
        revoked: List[str] = []
        for code, record in list(self._records.items()):
            if record.revoked_at or record.used:
                continue
            if record.is_expired():
                if self._revoke_record(code, "expired"):
                    revoked.append(code)
        return revoked

    def generate_otp(
        self,
        user: str,
        ttl: float = 300.0,
        scope: str = "global",
        mission_id: str = "",
        reason: str = "",
    ) -> str:
        """Generate a 6-digit OTP for *user* with a given TTL in seconds."""
        ttl = max(0.0, min(float(ttl), self.MAX_TTL_SECONDS))
        code = "".join(random.choices(string.digits, k=6))
        record = OTPRecord(
            code=code,
            user=user,
            scope=scope or "global",
            mission_id=mission_id,
            reason=reason,
            ttl=ttl,
        )
        self._records[code] = record
        self._audit_event(
            "generate",
            user=user,
            code=code,
            scope=record.scope,
            mission_id=mission_id,
            reason=reason,
            ttl=ttl,
        )
        return code

    def validate_otp(self, code: str, scope: Optional[str] = None) -> bool:
        """Return True if *code* exists, matches scope and has not expired."""
        self.revoke_expired()
        record = self._records.get(code)
        if record is None:
            return False
        if record.revoked_at or record.used or record.is_expired():
            return False
        if scope is not None and record.scope != scope:
            return False
        return True

    def get_audit_logs(self) -> List[Dict[str, Any]]:
        """Return the full audit trail."""
        return list(self._audit)

    def request_override(
        self,
        user: str,
        scope: str = "global",
        ttl: float = 300.0,
        reason: str = "",
        mission_id: str = "",
    ) -> str:
        """Create a scoped override token request."""
        return self.generate_otp(
            user=user,
            ttl=ttl,
            scope=scope,
            mission_id=mission_id,
            reason=reason,
        )

    def request_physical_approval(self, code: str) -> Optional[OTPRecord]:
        """Mark a code as pending physical approval and return its record."""
        self.revoke_expired()
        record = self._records.get(code)
        if record is None:
            return None
        self._audit_event(
            "physical_approval_requested",
            code=code,
            scope=record.scope,
            mission_id=record.mission_id,
        )
        return record

    def approve_physically(self, code: str, approved_by: str = "operator") -> None:
        """Mark a code as physically approved."""
        self.revoke_expired()
        record = self._records.get(code)
        if record is not None:
            record.physically_approved = True
            record.approved_by = approved_by
            self._audit_event(
                "physically_approved",
                code=code,
                scope=record.scope,
                approved_by=approved_by,
                mission_id=record.mission_id,
            )

    def confirm_override(
        self,
        code: str,
        approved_by: str = "operator",
        scope: str = "",
        mission_id: str = "",
    ) -> bool:
        """Confirm and consume an override token.

        The token must be live, scope-matched and physically approved.
        """
        self.revoke_expired()
        record = self._records.get(code)
        if record is None:
            return False
        if scope and record.scope != scope:
            return False
        if mission_id and record.mission_id and record.mission_id != mission_id:
            return False
        if not record.physically_approved:
            return False
        if record.used or record.revoked_at or record.is_expired():
            return False
        record.used = True
        record.approved_by = approved_by
        self._revoke_record(code, "consumed")
        self._audit_event(
            "confirmed",
            code=code,
            scope=record.scope,
            approved_by=approved_by,
            mission_id=record.mission_id,
        )
        return True

    def revoke_override(self, code: str, reason: str = "revoked") -> bool:
        """Explicitly revoke an override token."""
        self.revoke_expired()
        return self._revoke_record(code, reason)

    def is_physically_approved(self, code: str) -> bool:
        """Return True if *code* has been physically approved."""
        self.revoke_expired()
        record = self._records.get(code)
        return record is not None and record.physically_approved and not record.revoked_at and not record.used

    def active_overrides(self) -> List[Dict[str, Any]]:
        """Return a safe view of currently active overrides."""
        self.revoke_expired()
        active = []
        for record in self._records.values():
            if record.revoked_at or record.used or record.is_expired():
                continue
            active.append({
                "code": record.code,
                "user": record.user,
                "scope": record.scope,
                "mission_id": record.mission_id,
                "reason": record.reason,
                "created_at": record.created_at,
                "ttl": record.ttl,
                "physically_approved": record.physically_approved,
                "approved_by": record.approved_by,
            })
        return active


_SHARED_GATE_OVERRIDE = GateOverride()
