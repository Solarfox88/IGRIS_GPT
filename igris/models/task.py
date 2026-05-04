"""
Data models for tasks executed by the agent.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    blocked = "blocked"


@dataclass
class Task:
    """Representation of a task scheduled or performed by the agent."""

    id: int
    description: str
    status: TaskStatus = TaskStatus.pending
    result: Optional[str] = None
    title: Optional[str] = None
    family: str = "other"
    priority: int = 0
    risk: str = "low"
    source: str = "user"
    success_criteria: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    updated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    blocked_reason: Optional[str] = None
    semantic_fingerprint: Optional[str] = None
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "uuid": self.uuid,
            "title": self.title or self.description[:80],
            "description": self.description,
            "family": self.family,
            "status": self.status.value if isinstance(self.status, TaskStatus) else self.status,
            "priority": self.priority,
            "risk": self.risk,
            "source": self.source,
            "success_criteria": self.success_criteria,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "blocked_reason": self.blocked_reason,
            "semantic_fingerprint": self.semantic_fingerprint,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        status_val = data.get("status", "pending")
        if isinstance(status_val, str):
            status_val = TaskStatus(status_val)
        return cls(
            id=data["id"],
            description=data.get("description", ""),
            status=status_val,
            result=data.get("result"),
            title=data.get("title"),
            family=data.get("family", "other"),
            priority=data.get("priority", 0),
            risk=data.get("risk", "low"),
            source=data.get("source", "user"),
            success_criteria=data.get("success_criteria", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            blocked_reason=data.get("blocked_reason"),
            semantic_fingerprint=data.get("semantic_fingerprint"),
            uuid=data.get("uuid", str(uuid.uuid4())),
        )
