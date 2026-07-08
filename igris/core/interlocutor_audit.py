"""
Interlocutor Audit — append-only JSONL audit log with redaction (issue #526).

Security hardening (#1239):
- Path uses CONFIG.project_root when available (consistent across restarts)
- Write failures produce a visible warning log entry (degraded state)
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_audit_logger = logging.getLogger(__name__)

REDACT_PATTERNS = [
    re.compile(
        r'(passphrase|password|secret|token|key)["\s:=]+[^\s,"}{]+',
        re.IGNORECASE,
    ),
]


def _redact(text: str) -> str:
    for p in REDACT_PATTERNS:
        text = p.sub(r'\1=<REDACTED>', text)
    return text


def _safe_str(v: Any) -> str:
    try:
        s = json.dumps(v) if not isinstance(v, str) else v
        return _redact(s)
    except Exception:
        return "<unserializable>"


class InterlocutorAudit:
    def __init__(self, path: Path | str | None = None):
        if path is None:
            try:
                from igris.models.config import CONFIG
                path = CONFIG.igris_dir / "interlocutor_audit.jsonl"
            except Exception:
                path = Path(".igris") / "interlocutor_audit.jsonl"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        event_type: str,
        interlocutor_id: str = "unknown",
        display_name: str = "unknown",
        trust_level: str = "untrusted",
        action_type: str = "",
        target_resource: str = "",
        decision: str = "",
        reason: str = "",
        mission_id: str = "",
        run_id: str = "",
        request_id: str = "",
        extra: dict | None = None,
    ) -> str:
        event_id = str(uuid.uuid4())
        entry = {
            "event_id": event_id,
            "event_type": event_type,
            "ts": datetime.now(timezone.utc).isoformat(),
            "interlocutor_id": interlocutor_id,
            "display_name": display_name,
            "trust_level": trust_level,
            "action_type": action_type,
            "target_resource": target_resource,
            "decision": decision,
            "reason": _redact(reason),
            "mission_id": mission_id,
            "run_id": run_id,
            "request_id": request_id,
            "redacted_details": _safe_str(extra or {}),
        }
        try:
            with self.path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as _write_exc:
            _audit_logger.warning("Audit write failed (degraded): %s", _write_exc)
            return ""  # not None — callers can check truthiness
        return event_id

    def recent(self, n: int = 50) -> list[dict]:
        try:
            lines = (
                self.path.read_text().strip().split("\n")
                if self.path.exists()
                else []
            )
            return [json.loads(ln) for ln in lines[-n:] if ln.strip()]
        except Exception:
            return []
