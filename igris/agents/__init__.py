"""
Internal agent definitions and registry.

The agents module provides a simple contract for describing agent roles,
capabilities and messaging.  It also includes a registry that can be used
to discover available agents and their capabilities.  This is the first
step toward making IGRIS_GPT A2A‑ready without committing to a fully
distributed protocol.

Agents in this module do not implement any complex logic – they serve as
lightweight wrappers around existing functionality (task engine, teacher,
execution runner, etc.) so that other parts of the system can reason
about capabilities in a uniform way.
"""

from __future__ import annotations

from .base import (
    AgentRole,
    AgentCapability,
    AgentMessage,
    AgentTask,
    AgentResult,
    AgentArtifact,
    BaseAgent,
)
from .registry import (
    register_agent,
    list_agents,
    list_capabilities,
    find_agents_for_capability,
    get_capability,
    build_default_registry,
)

__all__ = [
    "AgentRole",
    "AgentCapability",
    "AgentMessage",
    "AgentTask",
    "AgentResult",
    "AgentArtifact",
    "BaseAgent",
    "register_agent",
    "list_agents",
    "list_capabilities",
    "find_agents_for_capability",
    "get_capability",
    "build_default_registry",
]