"""
Helpers to build an A2A agent card for IGRIS_GPT.

The agent card exposes the high level description of the agent along
with its skills and capabilities.  This module builds a minimal card
using the internal agent registry so that external systems can
discover what IGRIS_GPT can do.  It is not a full implementation
of the A2A agent card spec, but provides enough information for
clients adhering to the A2A protocol to interact with IGRIS_GPT.
"""

from __future__ import annotations

from typing import List

from igris.a2a.schemas import (
    A2AAgentCard,
    A2AAgentCapabilities,
    A2AAgentProvider,
    A2AAgentSkill,
)
from igris.agents import list_capabilities


def build_agent_card(base_url: str = "http://localhost:7778") -> A2AAgentCard:
    """Construct an A2A agent card from the internal agent registry.

    :param base_url: Base URL where the agent API is hosted.
    :returns: An A2AAgentCard instance serialisable to JSON via dataclasses.asdict().
    """
    caps = list_capabilities()
    # Convert capabilities into skills; a skill groups capabilities by name
    skills: List[A2AAgentSkill] = []
    for cap in caps:
        skills.append(
            A2AAgentSkill(
                id=cap.id,
                name=cap.name,
                description=cap.description,
                input_modality=["text"],
                output_modality=["text"],
            )
        )
    capabilities = A2AAgentCapabilities(skills=skills)
    card = A2AAgentCard(
        name="IGRIS_GPT",
        description="IGRIS_GPT local AI engineering agent",
        version="0.1.0",
        provider=A2AAgentProvider.local,
        url=f"{base_url}",
        capabilities=capabilities,
        authentication="none",
    )
    return card