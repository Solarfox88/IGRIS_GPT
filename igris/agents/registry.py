"""
Agent registry for IGRIS_GPT.

This module provides a simple registry for agents and their capabilities.
It allows registration of agents, introspection of available agents and
capabilities and helpers to find agents that can handle a specific
capability.  The registry is intentionally simple and does not enforce
any persistence or ordering beyond the list of registered agents.

In future revisions this registry could be extended to load agent
implementations dynamically or integrate with a discovery mechanism for
external agents via the A2A protocol.  For the MVP it suffices to
provide introspection for the local agents baked into the process.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .base import AgentCapability, BaseAgent

_agents: List[BaseAgent] = []


def register_agent(agent: BaseAgent) -> None:
    """Register an agent in the global registry.

    Agents should be registered during application startup.  Duplicate
    registrations of the same instance are ignored.  The registry does
    not currently enforce unique agent identifiers, so care should be
    taken to only register distinct agents once.

    :param agent: The agent to register.
    """
    if agent not in _agents:
        _agents.append(agent)


def list_agents() -> List[BaseAgent]:
    """Return a list of all registered agents."""
    return list(_agents)


def list_capabilities() -> List[AgentCapability]:
    """Return a flat list of all capabilities exposed by all agents."""
    caps: List[AgentCapability] = []
    for agent in _agents:
        caps.extend(agent.capabilities)
    return caps


def find_agents_for_capability(capability_id: str) -> List[BaseAgent]:
    """Return all agents that expose a given capability ID."""
    agents: List[BaseAgent] = []
    for agent in _agents:
        for cap in agent.capabilities:
            if cap.id == capability_id:
                agents.append(agent)
                break
    return agents


def get_capability(capability_id: str) -> Optional[AgentCapability]:
    """Return the first capability with the given ID, or None if not found."""
    for agent in _agents:
        for cap in agent.capabilities:
            if cap.id == capability_id:
                return cap
    return None


def build_default_registry() -> None:
    """Populate the registry with default agents used by IGRIS_GPT.

    This helper is called by the FastAPI server during startup to
    ensure that the registry contains at least one agent for each
    subsystem implemented in the MVP.  It registers lightweight
    wrapper agents exposing the capabilities already present in the
    existing modules (e.g. git status, file tree, test run).  These
    agents do not implement autonomous behaviour; they simply expose
    existing functions under the agent contract.
    """
    # Avoid duplicate registration if this function is called more than once.
    if _agents:
        return
    from .base import AgentRole
    from igris.layers.git_layer.git_status import get_git_info
    from igris.layers.execution.runner import run_tests, run_safe_command
    from igris.layers.execution.safe_commands import ALLOWED_COMMANDS
    from igris.web.server import create_app  # type: ignore

    class GitAgent(BaseAgent):
        def __init__(self) -> None:
            super().__init__(
                agent_id="git-agent",
                name="Git Agent",
                role=AgentRole.git,
                capabilities=[
                    AgentCapability(
                        id="git.status",
                        name="Git status",
                        description="Return information about the current git repository.",
                        output_schema={"branch": "string", "remote": "string", "dirty": "bool", "changed": "list"},
                        safe=True,
                        risk="low",
                    )
                ],
            )

        def run(self, task: AgentTask) -> AgentResult:  # type: ignore
            info = get_git_info()
            return AgentResult(
                task_id=task.id,
                success=True,
                output={
                    "branch": info.branch,
                    "remote": info.remote,
                    "dirty": info.dirty,
                    "changed": info.changed,
                    "head": info.head,
                },
                artifacts=None,
            )

    class TestAgent(BaseAgent):
        def __init__(self) -> None:
            super().__init__(
                agent_id="test-agent",
                name="Test Runner Agent",
                role=AgentRole.validation,
                capabilities=[
                    AgentCapability(
                        id="validation.run_tests",
                        name="Run Tests",
                        description="Execute the test suite using pytest.",
                        safe=True,
                        risk="medium",
                        output_schema={"success": "bool", "stdout": "string", "stderr": "string"},
                    )
                ],
            )

        def run(self, task: AgentTask) -> AgentResult:  # type: ignore
            res = run_tests()
            success = res.get("returncode", 1) == 0
            return AgentResult(
                task_id=task.id,
                success=success,
                output={"stdout": res.get("stdout", ""), "stderr": res.get("stderr", "")},
                artifacts=None,
            )

    class TerminalAgent(BaseAgent):
        def __init__(self) -> None:
            super().__init__(
                agent_id="terminal-agent",
                name="Terminal Agent",
                role=AgentRole.execution,
                capabilities=[
                    AgentCapability(
                        id="execution.run_safe_command",
                        name="Run Safe Command",
                        description="Execute a pre-defined safe shell command.",
                        input_schema={"command_id": "string"},
                        output_schema={"stdout": "string", "stderr": "string", "returncode": "int"},
                        safe=True,
                        risk="medium",
                    )
                ],
            )

        def run(self, task: AgentTask) -> AgentResult:  # type: ignore
            cmd_id = task.safe_command_ids[0] if task.safe_command_ids else ""
            if cmd_id not in ALLOWED_COMMANDS:
                return AgentResult(task_id=task.id, success=False, output=None, error="Unknown command", artifacts=None)
            res = run_safe_command(cmd_id)
            return AgentResult(
                task_id=task.id,
                success=res.get("returncode", 1) == 0,
                output={"stdout": res.get("stdout", ""), "stderr": res.get("stderr", ""), "returncode": res.get("returncode")},
                artifacts=None,
            )

    # Instantiate and register our minimal agents
    register_agent(GitAgent())
    register_agent(TestAgent())
    register_agent(TerminalAgent())