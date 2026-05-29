"""
Proactive Context Engine — Layer 7 of the Interlocutor-Aware system (issue #526).

Anti-flood: cooldown per event type, urgency threshold, deny-by-default for untrusted.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_COOLDOWN_FILE = ".igris/proactive_cooldowns.json"
_DEFAULT_MIN_INTERVAL_SEC = 300


@dataclass
class ProactiveEvent:
    event_type: str
    title: str
    message: str
    urgency: float
    relevant_resource: str
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProactiveConfig:
    min_urgency: float = 0.3
    min_interval_sec: float = _DEFAULT_MIN_INTERVAL_SEC
    enabled: bool = True


class ProactiveEngine:
    """Layer 7: event scanner with anti-flood protection."""

    def __init__(
        self,
        project_root: str,
        config: Optional[ProactiveConfig] = None,
    ) -> None:
        self.project_root = project_root
        self.config = config or ProactiveConfig()
        self._cooldowns: Optional[Dict[str, float]] = None

    def _cooldown_path(self) -> Path:
        return Path(self.project_root) / _COOLDOWN_FILE

    def _load_cooldowns(self) -> Dict[str, float]:
        if self._cooldowns is not None:
            return self._cooldowns
        path = self._cooldown_path()
        if not path.exists():
            self._cooldowns = {}
            return self._cooldowns
        try:
            self._cooldowns = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self._cooldowns = {}
        return self._cooldowns

    def _save_cooldowns(self) -> None:
        path = self._cooldown_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(
                json.dumps(self._cooldowns or {}, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def _is_on_cooldown(self, event_type: str) -> bool:
        cooldowns = self._load_cooldowns()
        last = cooldowns.get(event_type, 0.0)
        return (time.time() - last) < self.config.min_interval_sec

    def _record_cooldown(self, event_type: str) -> None:
        cooldowns = self._load_cooldowns()
        cooldowns[event_type] = time.time()
        self._cooldowns = cooldowns
        self._save_cooldowns()

    def scan(
        self,
        state_snapshot: Dict[str, Any],
        authorized_scopes: Optional[List[str]] = None,
        trust_level: str = "untrusted",
    ) -> List[ProactiveEvent]:
        if not self.config.enabled:
            return []
        if trust_level == "untrusted":
            return []

        events: List[ProactiveEvent] = []

        if state_snapshot.get("run_failed"):
            run_info = state_snapshot["run_failed"]
            resource = str(run_info.get("issue", run_info.get("run_id", "unknown")))
            if self._is_relevant(resource, authorized_scopes):
                events.append(ProactiveEvent(
                    event_type="run_failed",
                    title="Run failed",
                    message=f"Run on {resource} failed: {run_info.get('reason', 'unknown')}",
                    urgency=0.7,
                    relevant_resource=resource,
                ))

        if state_snapshot.get("ci_broken"):
            branch = str(state_snapshot.get("branch", "unknown"))
            if self._is_relevant(branch, authorized_scopes):
                events.append(ProactiveEvent(
                    event_type="ci_broken",
                    title="CI broken",
                    message=f"CI is broken on branch '{branch}'.",
                    urgency=0.8,
                    relevant_resource=branch,
                ))

        for res in state_snapshot.get("degraded_resources", []):
            resource_name = str(res.get("name", "unknown"))
            if self._is_relevant(resource_name, authorized_scopes):
                events.append(ProactiveEvent(
                    event_type="resource_degraded",
                    title=f"Resource degraded: {resource_name}",
                    message=f"Healthcheck failed for '{resource_name}': {res.get('reason', '')}",
                    urgency=0.9,
                    relevant_resource=resource_name,
                ))

        session_start = float(state_snapshot.get("session_start_ts", 0.0) or 0.0)
        if session_start > 0:
            elapsed_h = (time.time() - session_start) / 3600
            if elapsed_h >= 4:
                events.append(ProactiveEvent(
                    event_type="session_long",
                    title="Long session",
                    message=f"You have been working for {elapsed_h:.1f} hours. Want a status summary?",
                    urgency=0.3,
                    relevant_resource="session",
                ))

        result: List[ProactiveEvent] = []
        for ev in events:
            if ev.urgency < self.config.min_urgency:
                continue
            if self._is_on_cooldown(ev.event_type):
                continue
            self._record_cooldown(ev.event_type)
            result.append(ev)

        return result

    def _is_relevant(
        self, resource: str, authorized_scopes: Optional[List[str]]
    ) -> bool:
        if authorized_scopes is None:
            return True
        if "*" in authorized_scopes:
            return True
        return resource in authorized_scopes
