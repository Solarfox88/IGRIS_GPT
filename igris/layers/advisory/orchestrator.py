"""
Advisory orchestrator — thin coordinator for task sequencing.

Delegates to ModelOrchestrator for all LLM routing. Exists for backward
compatibility with callers that import Orchestrator by name from this module.
"""
from __future__ import annotations

from igris.core.model_orchestrator import ModelOrchestrator


class Orchestrator:
    """Thin wrapper around ModelOrchestrator used by legacy advisory endpoints."""

    def __init__(self) -> None:
        self._inner = ModelOrchestrator()

    def start(self) -> None:
        """No-op: ModelOrchestrator initialises lazily on first .complete() call."""
