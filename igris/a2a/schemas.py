"""
Simplified A2A schema definitions.

These dataclasses model a subset of the A2A specification.  They are
intended to be serialisable to JSON via `asdict()` or `.dict()` when
using dataclasses or Pydantic.  The goal is not to implement the full
protocol but to provide structures that can be returned by the FastAPI
endpoints and used by clients to understand the agent's capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class A2AAgentProvider(str, Enum):
    """Enumeration of possible providers for the agent.

    For the MVP we expose only 'local'.  Future implementations could
    include 'openai', 'ollama', 'vastai', etc.
    """

    local = "local"
    openai = "openai"
    vastai = "vastai"


@dataclass
class A2AAgentSkill:
    """Describe a skill that an agent offers.

    In the A2A specification a skill groups capabilities and indicates
    input/output modalities.  We keep this minimal for now.
    """

    id: str
    name: str
    description: str
    input_modality: List[str] = field(default_factory=lambda: ["text"])
    output_modality: List[str] = field(default_factory=lambda: ["text"])


@dataclass
class A2AAgentCapabilities:
    """List of capabilities offered by the agent as used in the A2A card."""

    skills: List[A2AAgentSkill]


@dataclass
class A2AAgentCard:
    """Representation of an A2A agent card.

    This mirrors parts of the specification: name, description, version,
    provider, URL and capabilities.  Additional fields can be added
    later as needed.
    """

    name: str
    description: str
    version: str
    provider: A2AAgentProvider
    url: str
    capabilities: A2AAgentCapabilities
    authentication: str = "none"


class A2ATaskStatus(str, Enum):
    """Task statuses for A2A tasks (extended for long-running support)."""

    submitted = "submitted"
    working = "working"
    input_required = "input_required"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"


@dataclass
class A2AArtifact:
    """Artifact produced as part of a task."""

    id: str
    name: str
    url: Optional[str] = None
    content: Optional[Any] = None
    mime_type: Optional[str] = None


@dataclass
class A2APart:
    """A part of an A2A message."""

    role: str
    content: str


@dataclass
class A2AMessage:
    """Message in the context of an A2A task conversation."""

    sender: str
    parts: List[A2APart]
    timestamp: Optional[float] = None


@dataclass
class A2ATask:
    """Simplified representation of an A2A task."""

    id: str
    status: A2ATaskStatus
    created_at: Optional[float] = None
    updated_at: Optional[float] = None
    title: Optional[str] = None
    description: Optional[str] = None
    messages: List[A2AMessage] = field(default_factory=list)
    artifacts: List[A2AArtifact] = field(default_factory=list)
