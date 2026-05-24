"""
ToolTracker: per-tool effectiveness stats.

Stores stats in .igris/tool_stats.json (atomic writes).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolStats:
    """Statistics for a single tool."""

    tool_name: str
    total_calls: int = 0
    successes: int = 0
    failures: int = 0
    avg_duration_ms: float = 0.0
    common_error_patterns: List[str] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)

    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 1.0
        return self.successes / self.total_calls

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "total_calls": self.total_calls,
            "successes": self.successes,
            "failures": self.failures,
            "avg_duration_ms": self.avg_duration_ms,
            "common_error_patterns": self.common_error_patterns,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ToolStats":
        return cls(
            tool_name=d["tool_name"],
            total_calls=d.get("total_calls", 0),
            successes=d.get("successes", 0),
            failures=d.get("failures", 0),
            avg_duration_ms=d.get("avg_duration_ms", 0.0),
            common_error_patterns=d.get("common_error_patterns", []),
            last_updated=d.get("last_updated", time.time()),
        )


class ToolTracker:
    """
    Collects and persists tool execution statistics.

    Stats are stored as JSON in .igris/tool_stats.json inside the project.
    """

    def __init__(self, project_root: str) -> None:
        self._stats: Dict[str, ToolStats] = {}
        self._file_path = Path(project_root) / ".igris" / "tool_stats.json"
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        tool_name: str,
        success: bool,
        duration_ms: float,
        error_snippet: Optional[str] = None,
    ) -> None:
        """Record a tool execution result."""
        stats = self._stats.get(tool_name)
        if stats is None:
            stats = ToolStats(tool_name=tool_name)
            self._stats[tool_name] = stats

        stats.total_calls += 1
        if success:
            stats.successes += 1
        else:
            stats.failures += 1
            if error_snippet and error_snippet.strip():
                self._add_error_pattern(stats, error_snippet.strip())

        # Update running average duration
        if stats.total_calls > 0:
            old_avg = stats.avg_duration_ms
            n = stats.total_calls - 1  # previous total
            if n == 0:
                stats.avg_duration_ms = duration_ms
            else:
                stats.avg_duration_ms = (old_avg * n + duration_ms) / (n + 1)

        stats.last_updated = time.time()
        self._save()

    def get_stats(self, tool_name: str) -> Optional[ToolStats]:
        """Return stats for a tool, or None."""
        return self._stats.get(tool_name)

    def get_all_stats(self) -> Dict[str, ToolStats]:
        """Return a copy of all stats."""
        return dict(self._stats)

    def get_unreliable_tools(
        self,
        min_calls: int = 5,
        max_success_rate: float = 0.6,
    ) -> List[str]:
        """Return names of tools with low success rate."""
        unreliable: List[str] = []
        for name, stats in self._stats.items():
            if stats.total_calls >= min_calls:
                if stats.success_rate() <= max_success_rate:
                    unreliable.append(name)
        return sorted(unreliable)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _file_data(self) -> Dict[str, Any]:
        return {
            "tools": {name: s.to_dict() for name, s in self._stats.items()},
        }

    def _load(self) -> None:
        if not self._file_path.exists():
            return
        try:
            text = self._file_path.read_text(encoding="utf-8")
            data = json.loads(text)
            for tool_data in data.get("tools", {}).values():
                stats = ToolStats.from_dict(tool_data)
                self._stats[stats.tool_name] = stats
        except Exception as exc:
            logger.warning("Failed to load tool stats from %s: %s", self._file_path, exc)

    def _save(self) -> None:
        """Atomic write: write to temp file, then rename."""
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._file_path.with_suffix(".tmp")
            payload = json.dumps(self._file_data(), indent=2)
            tmp_path.write_text(payload, encoding="utf-8")
            tmp_path.rename(self._file_path)
        except Exception as exc:
            logger.error("Failed to save tool stats to %s: %s", self._file_path, exc)

    def _add_error_pattern(self, stats: ToolStats, snippet: str) -> None:
        """Add an error snippet, deduplicating and capping at 5."""
        if snippet not in stats.common_error_patterns:
            if len(stats.common_error_patterns) >= 5:
                # Remove oldest
                stats.common_error_patterns.pop(0)
            stats.common_error_patterns.append(snippet)
