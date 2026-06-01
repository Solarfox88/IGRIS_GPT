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
    created_at: float = field(default_factory=time.time)
    ttl: float = 300.0
    used: bool = False
    physically_approved: bool = False

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl


class GateOverride:
    """OTP-based gate override with audit trail and physical approval support."""

    def __init__(self) -> None:
        self._records: Dict[str, OTPRecord] = {}
        self._audit: List[Dict[str, Any]] = []

    def generate_otp(self, user: str, ttl: float = 300.0) -> str:
        """Generate a 6-digit OTP for *user* with a given TTL in seconds."""
        code = "".join(random.choices(string.digits, k=6))
        record = OTPRecord(code=code, user=user, ttl=ttl)
        self._records[code] = record
        self._audit.append({
            "action": "generate",
            "user": user,
            "code": code,
            "ts": time.time(),
        })
        return code

    def validate_otp(self, code: str) -> bool:
        """Return True if *code* exists and has not expired."""
        record = self._records.get(code)
        if record is None:
            return False
        return not record.is_expired()

    def get_audit_logs(self) -> List[Dict[str, Any]]:
        """Return the full audit trail."""
        return list(self._audit)

    def request_physical_approval(self, code: str) -> Optional[OTPRecord]:
        """Mark a code as pending physical approval and return its record."""
        record = self._records.get(code)
        if record is None:
            return None
        self._audit.append({"action": "physical_approval_requested", "code": code, "ts": time.time()})
        return record

    def approve_physically(self, code: str) -> None:
        """Mark a code as physically approved."""
        record = self._records.get(code)
        if record is not None:
            record.physically_approved = True
            self._audit.append({"action": "physically_approved", "code": code, "ts": time.time()})

    def is_physically_approved(self, code: str) -> bool:
        """Return True if *code* has been physically approved."""
        record = self._records.get(code)
        return record is not None and record.physically_approved
