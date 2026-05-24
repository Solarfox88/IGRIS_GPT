"""ToolTracker — per-tool effectiveness stats post-turn."""
import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ToolStats:
    """Statistics for a single tool."""

    tool_name: str
    total_calls: int = 0
    successes: int = 0
    failures: int = 0
    avg_duration_ms: float = 0.0
    common_error_patterns: list[str] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)


class ToolTracker:
    """Persistent per-tool effectiveness tracker.

    Stores stats in `.igris/tool_stats.json` and provides methods
    to record tool executions, retrieve stats, and identify
    unreliable tools.
    """

    def __init__(self, project_root: str) -> None:
        self._stats_file = os.path.join(project_root, ".igris", "tool_stats.json")
        self._stats: dict[str, ToolStats] = {}
        self._load()

    def _load(self) -> None:
        """Load stats from disk."""
        try:
            with open(self._stats_file, "r") as f:
                data = json.load(f)
            for name, entry in data.items():
                stats = ToolStats(
                    tool_name=name,
                    total_calls=entry.get("total_calls", 0),
                    successes=entry.get("successes", 0),
                    failures=entry.get("failures", 0),
                    avg_duration_ms=entry.get("avg_duration_ms", 0.0),
                    common_error_patterns=entry.get("common_error_patterns", []),
                    last_updated=entry.get("last_updated", time.time()),
                )
                self._stats[name] = stats
        except FileNotFoundError:
            pass

    def _save(self) -> None:
        """Atomically save stats to disk."""
        os.makedirs(os.path.dirname(self._stats_file), exist_ok=True)
        tmp = self._stats_file + ".tmp"
        data = {
            name: {
                "tool_name": stats.tool_name,
                "total_calls": stats.total_calls,
                "successes": stats.successes,
                "failures": stats.failures,
                "avg_duration_ms": stats.avg_duration_ms,
                "common_error_patterns": stats.common_error_patterns,
                "last_updated": stats.last_updated,
            }
            for name, stats in self._stats.items()
        }
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self._stats_file)

    def record(
        self,
        tool_name: str,
        success: bool,
        duration_ms: float,
        error_snippet: Optional[str] = None,
    ) -> None:
        """Record a tool execution.

        Updates running average of duration and maintains up to 5
        unique error snippets.
        """
        if tool_name not in self._stats:
            self._stats[tool_name] = ToolStats(tool_name=tool_name)
        stats = self._stats[tool_name]

        # Update counts
        stats.total_calls += 1
        if success:
            stats.successes += 1
        else:
            stats.failures += 1
            if error_snippet and error_snippet not in stats.common_error_patterns:
                if len(stats.common_error_patterns) >= 5:
                    stats.common_error_patterns.pop(0)
                stats.common_error_patterns.append(error_snippet)

        # Running average
        stats.avg_duration_ms = (
            (stats.avg_duration_ms * (stats.total_calls - 1) + duration_ms)
            / stats.total_calls
        )
        stats.last_updated = time.time()
        self._save()

    def get_stats(self, tool_name: str) -> Optional[ToolStats]:
        """Return stats for a given tool, or None if not tracked."""
        return self._stats.get(tool_name)

    def get_all_stats(self) -> dict[str, ToolStats]:
        """Return a copy of all tool stats."""
        return dict(self._stats)

    def get_unreliable_tools(
        self, min_calls: int = 5, max_success_rate: float = 0.6
    ) -> list[str]:
        """Return list of tool names with success rate <= max_success_rate
        and at least min_calls recorded.
        """
        unreliable = []
        for name, stats in self._stats.items():
            if stats.total_calls >= min_calls:
                success_rate = stats.successes / stats.total_calls
                if success_rate <= max_success_rate:
                    unreliable.append(name)
        return sorted(unreliable)
