"""
ReflectionHook — post-step structured LLM extraction of lessons into memory graph.

Issue #532: triggered by complexity signals (not every step), with per-session
throttling, silent on LLM failure, persists observations/patterns as lesson nodes.

Based on openhuman reflection.rs pattern: complexity triggers, not blanket reflection.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


_DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "max_reflections_per_session": 10,
    "min_tool_calls": 3,
    "min_response_chars": 500,
    "model_profile": "local_light",
}

_REFLECTION_PROMPT = """\
You are an AI assistant that extracts structured learning signals from a reasoning step.

Given a step result, extract:
- observations: concrete facts observed in this step (e.g. "test X failed with error Y")
- patterns: reusable patterns or anti-patterns (e.g. "running pytest without --tb=short produces verbose output")
- user_preferences: any user preferences or constraints that were explicit in this step

Return ONLY valid JSON with this exact schema:
{
  "observations": ["..."],
  "patterns": ["..."],
  "user_preferences": ["..."]
}

If nothing notable, return empty lists. Keep items concise (max 120 chars each).
"""


@dataclass
class ReflectionOutput:
    observations: List[str] = field(default_factory=list)
    patterns: List[str] = field(default_factory=list)
    user_preferences: List[str] = field(default_factory=list)


@dataclass
class ReflectionConfig:
    enabled: bool = True
    max_reflections_per_session: int = 10
    min_tool_calls: int = 3
    min_response_chars: int = 500
    model_profile: str = "local_light"

    @classmethod
    def from_file(cls, path: str) -> "ReflectionConfig":
        try:
            with open(path, "r") as f:
                data = json.load(f)
            return cls(
                enabled=bool(data.get("enabled", True)),
                max_reflections_per_session=int(data.get("max_reflections_per_session", 10)),
                min_tool_calls=int(data.get("min_tool_calls", 3)),
                min_response_chars=int(data.get("min_response_chars", 500)),
                model_profile=str(data.get("model_profile", "local_light")),
            )
        except Exception:
            return cls()


class ReflectionHook:
    """Post-step hook that fires only on complex turns and extracts structured lessons.

    Design:
    - should_reflect() checks complexity: tool_count >= min_tool_calls OR response_len > min_response_chars
    - Per-session throttle: max_reflections_per_session counter
    - LLM call via ModelOrchestrator (best-effort, never raises)
    - Persists observations + patterns as 'lesson' nodes in MemoryGraph
    """

    def __init__(self, project_root: str, config: Optional[Dict[str, Any]] = None) -> None:
        self.project_root = project_root
        self._reflections_this_session: int = 0

        # Load config from file or use provided/defaults
        config_path = os.path.join(project_root, ".igris", "reflection_config.json")
        if config is not None:
            self._cfg = ReflectionConfig(
                enabled=bool(config.get("enabled", True)),
                max_reflections_per_session=int(config.get("max_reflections_per_session", 10)),
                min_tool_calls=int(config.get("min_tool_calls", 3)),
                min_response_chars=int(config.get("min_response_chars", 500)),
                model_profile=str(config.get("model_profile", "local_light")),
            )
        elif os.path.exists(config_path):
            self._cfg = ReflectionConfig.from_file(config_path)
        else:
            self._cfg = ReflectionConfig()

    def should_reflect(self, step_result: Dict[str, Any]) -> bool:
        """Complexity check: trigger reflection only on complex steps.

        Returns True if:
        - hook is enabled
        - per-session budget not exhausted
        - tool_count >= min_tool_calls OR response_len > min_response_chars
        """
        if not self._cfg.enabled:
            return False
        if self._reflections_this_session >= self._cfg.max_reflections_per_session:
            return False

        tool_count = int(step_result.get("tool_count", 0))
        response_text = str(step_result.get("response", step_result.get("summary", "")))
        response_len = len(response_text)

        return (
            tool_count >= self._cfg.min_tool_calls
            or response_len >= self._cfg.min_response_chars
        )

    def on_step_complete(
        self,
        step_result: Dict[str, Any],
        goal: str,
        project_root: Optional[str] = None,
    ) -> Optional[ReflectionOutput]:
        """Extract lessons from this step and persist to memory graph.

        Best-effort: never raises. Returns ReflectionOutput or None on any failure.
        """
        try:
            if not self.should_reflect(step_result):
                return None

            output = self._call_llm(step_result, goal)
            if output is None:
                return None

            # Rollback counter if LLM failed to produce content
            if not (output.observations or output.patterns or output.user_preferences):
                return output  # no counter increment for empty results

            self._reflections_this_session += 1
            self._persist(output, goal, project_root or self.project_root)
            return output
        except Exception:
            return None

    def _call_llm(
        self, step_result: Dict[str, Any], goal: str
    ) -> Optional[ReflectionOutput]:
        """Call ModelOrchestrator for structured extraction. Silent on failure."""
        try:
            from igris.core.model_orchestrator import ModelOrchestrator

            step_summary = self._build_step_summary(step_result, goal)
            orchestrator = ModelOrchestrator()
            result = orchestrator.complete(
                task_type="reflection",
                messages=[{"role": "user", "content": step_summary}],
                system_prompt=_REFLECTION_PROMPT,
                preferred_profile=self._cfg.model_profile,
                max_tokens=512,
                temperature=0.2,
                json_mode=True,
                timeout=20.0,
            )
            if not result.success or not result.text:
                return None

            return self._parse_llm_output(result.text)
        except Exception:
            return None

    def _build_step_summary(self, step_result: Dict[str, Any], goal: str) -> str:
        """Build a concise step summary for the LLM."""
        lines = [f"Goal: {goal[:200]}"]
        action = step_result.get("action_type", step_result.get("action", "unknown"))
        lines.append(f"Action: {action}")
        outcome = step_result.get("outcome", step_result.get("success", "unknown"))
        lines.append(f"Outcome: {outcome}")

        summary = str(step_result.get("summary", step_result.get("response", "")))
        if summary:
            lines.append(f"Summary (first 400 chars): {summary[:400]}")

        error = str(step_result.get("error", ""))
        if error:
            lines.append(f"Error: {error[:200]}")

        return "\n".join(lines)

    def _parse_llm_output(self, text: str) -> Optional[ReflectionOutput]:
        """Parse structured JSON from LLM. Silent on malformed JSON."""
        try:
            # Strip markdown code fences if present
            stripped = text.strip()
            if stripped.startswith("```"):
                lines = stripped.splitlines()
                stripped = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

            data = json.loads(stripped)
            return ReflectionOutput(
                observations=[str(x)[:120] for x in data.get("observations", []) if x],
                patterns=[str(x)[:120] for x in data.get("patterns", []) if x],
                user_preferences=[str(x)[:120] for x in data.get("user_preferences", []) if x],
            )
        except Exception:
            return None

    def _persist(self, output: ReflectionOutput, goal: str, project_root: str) -> None:
        """Persist observations and patterns as lesson nodes in MemoryGraph."""
        try:
            from igris.core.memory_graph import MemoryGraph
            mg = MemoryGraph(project_root)

            for obs in output.observations:
                mg.add_node(
                    "lesson",
                    {
                        "content": obs,
                        "goal": goal[:100],
                        "source": "reflection_hook",
                        "kind": "observation",
                        "ts": time.time(),
                    },
                    confidence=0.6,
                )

            for pat in output.patterns:
                mg.add_node(
                    "lesson",
                    {
                        "content": pat,
                        "goal": goal[:100],
                        "source": "reflection_hook",
                        "kind": "pattern",
                        "ts": time.time(),
                    },
                    confidence=0.65,
                )
        except Exception:
            pass
