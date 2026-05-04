"""
A2A protocol primitives for IGRIS_GPT.

This package defines lightweight data structures and helpers to expose
IGRIS_GPT as an A2A‑compatible agent.  It is not a full implementation
of the A2A protocol; instead it provides enough structure to publish
capabilities via an agent card and accept simple task submissions
through an A2A‑style API.  Future versions could extend these
definitions to fully comply with the specification at
https://google-a2a.github.io/A2A/specification/.
"""

from .schemas import (
    A2AAgentCard,
    A2AAgentCapabilities,
    A2AAgentSkill,
    A2AAgentProvider,
    A2ATask,
    A2ATaskStatus,
    A2AMessage,
    A2APart,
    A2AArtifact,
)
from .agent_card import build_agent_card

__all__ = [
    "A2AAgentCard",
    "A2AAgentCapabilities",
    "A2AAgentSkill",
    "A2AAgentProvider",
    "A2ATask",
    "A2ATaskStatus",
    "A2AMessage",
    "A2APart",
    "A2AArtifact",
    "build_agent_card",
]