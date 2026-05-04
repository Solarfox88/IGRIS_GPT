"""
Base definitions for agents and capabilities.

This module defines data structures that describe the capabilities of an
agent, messages exchanged between agents and tasks/results.  These
definitions are intentionally simple and serialisable using standard
Python types so they can be embedded into JSON responses easily.

The goal of the agent contract is to provide enough information for other
components or external systems to understand what an agent can do and
how to interact with it.  In the future these models could be
converted to pydantic models or marshalled into an A2A schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentRole(str, Enum):
    """Enumeration of coarse agent roles.

    These roles are not enforced; they are used for documentation and
    discovery purposes.  An agent may implement multiple roles.
    """

    orchestrator = "orchestrator"
    project_context = "project_context"
    task_intelligence = "task_intelligence"
    teacher = "teacher"
    execution = "execution"
    validation = "validation"
    git = "git"
    cost_router = "cost_router"
    safety = "safety"
    a2a = "a2a"


@dataclass
class AgentCapability:
    """Describe a single capability exposed by an agent.

    Attributes:
        id: A short identifier for the capability (unique within the agent).
        name: Human friendly name.
        description: Brief description of what the capability does.
        input_schema: Optional schema description for inputs (dict or None).
        output_schema: Optional schema description for outputs (dict or None).
        safe: Indicates whether the capability is considered safe to run
            without human approval.
        risk: Coarse risk classification (low/medium/high).
    """

    id: str
    name: str
    description: str
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    safe: bool = True
    risk: str = "low"


@dataclass
class AgentMessage:
    """Representation of a message sent between agents or from a user to an agent."""

    role: str
    content: str
    timestamp: Optional[float] = None


@dataclass
class AgentTask:
    """Representation of a task assigned to an agent."""

    id: str
    title: str
    description: str
    family: str = "other"
    status: str = "pending"
    priority: int = 0
    risk: str = "low"
    source: str = "system"
    success_criteria: List[str] = field(default_factory=list)
    created_at: Optional[float] = None
    updated_at: Optional[float] = None
    semantic_fingerprint: Optional[str] = None
    blocked_reason: Optional[str] = None
    differentiator: Optional[str] = None
    expected_output: Optional[str] = None
    safe_command_ids: Optional[List[str]] = None


@dataclass
class AgentResult:
    """Result produced by an agent after running a task."""

    task_id: str
    success: bool
    output: Any
    error: Optional[str] = None
    artifacts: Optional[List[AgentArtifact]] = None
    next_recommendation: Optional[str] = None
    created_at: Optional[float] = None
    failure_type: Optional[str] = None


@dataclass
class AgentArtifact:
    """Generic artifact produced by an agent (e.g. file, report)."""

    id: str
    name: str
    content: Any
    mime_type: Optional[str] = None


class BaseAgent:
    """Base class for all agents.

    An agent must provide a unique identifier, a set of capabilities
    and implement `run` to handle tasks.  Subclasses can override
    `can_handle` to indicate whether they can process a given task.
    """

    def __init__(self, agent_id: str, name: str, role: AgentRole, capabilities: List[AgentCapability]) -> None:
        self.agent_id = agent_id
        self.name = name
        self.role = role
        self.capabilities = capabilities

    def describe(self) -> Dict[str, Any]:
        """Return a description of the agent and its capabilities."""
        return {
            "id": self.agent_id,
            "name": self.name,
            "role": self.role,
            "capabilities": [cap.__dict__ for cap in self.capabilities],
        }

    def can_handle(self, task: AgentTask) -> bool:
        """Return True if this agent can handle the given task.

        The default implementation simply returns True for all tasks.
        Subclasses may override this to provide selective handling.
        """
        return True

    def run(self, task: AgentTask) -> AgentResult:
        """Run the given task and return an AgentResult.

        Subclasses must implement this method.  The base implementation
        raises NotImplementedError.
        """
        raise NotImplementedError("BaseAgent does not implement run")