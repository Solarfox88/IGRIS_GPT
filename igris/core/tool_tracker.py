"""ToolTracker — Per-tool effectiveness stats post-turn.

Tracks per-tool: total_calls, successes, failures, avg_duration_ms,
and common_error_patterns. Persists to .igris/tool_stats.json atomically.
"""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
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

    def success_rate(self) -> float:
        """Return success rate (0.0-1.0) or 1.0 if no calls."""
        if self.total_calls == 0:
            return 1.0
        return self.successes / self.total_calls

    def record_call(self, success: bool, duration_ms: float, error_snippet: Optional[str] = None) -> None:
        """Update running stats with a new call."""
        self.total_calls += 1
        if success:
            self.successes += 1
        else:
            self.failures += 1

        # Update running average duration
        if self.total_calls == 1:
            self.avg_duration_ms = duration_ms
        else:
            # Welford's online algorithm for mean
            delta = duration_ms - self.avg_duration_ms
            self.avg_duration_ms += delta / self.total_calls

        # Track unique error patterns (max 5)
        if not success and error_snippet:
            snippet = error_snippet.strip()
            if snippet and snippet not in self.common_error_patterns:
                self.common_error_patterns.append(snippet)
                if len(self.common_error_patterns) > 5:
                    self.common_error_patterns.pop(0)

        self.last_updated = time.time()


class ToolTracker:
    """Manages per-tool statistics with persistent storage."""

    DATA_DIR = ".igris"
    STATS_FILE = "tool_stats.json"

    def __init__(self, project_root: str) -> None:
        """Initialize tracker with project root directory.

        Args:
            project_root: Root directory of the project (where .igris folder lives).
        """
        self.project_root = Path(project_root)
        self.data_dir = self.project_root / self.DATA_DIR
        self.stats_file = self.data_dir / self.STATS_FILE
        self._stats: dict[str, ToolStats] = {}
        self._load()

    def _load(self) -> None:
        """Load existing stats from JSON file."""
        if self.stats_file.exists():
            try:
                with open(self.stats_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for name, data in raw.items():
                    stats = ToolStats(
                        tool_name=name,
                        total_calls=data.get("total_calls", 0),
                        successes=data.get("successes", 0),
                        failures=data.get("failures", 0),
                        avg_duration_ms=data.get("avg_duration_ms", 0.0),
                        common_error_patterns=data.get("common_error_patterns", []),
                        last_updated=data.get("last_updated", 0.0),
                    )
                    self._stats[name] = stats
            except (json.JSONDecodeError, KeyError, OSError):
                # If file is corrupt or missing, start fresh
                self._stats = {}

    def _save(self) -> None:
        """Atomically persist current stats to JSON file."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # Write to temporary file then rename for atomicity
        tmp_file = self.stats_file.with_suffix(".tmp")
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
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_file, self.stats_file)

    def record(
        self,
        tool_name: str,
        success: bool,
        duration_ms: float,
        error_snippet: Optional[str] = None,
    ) -> None:
        """Record a tool call outcome.

        Args:
            tool_name: Name of the tool (e.g., 'gh', 'pytest', 'ruff').
            success: Whether the call succeeded.
            duration_ms: Duration in milliseconds.
            error_snippet: Optional error message fragment (for failure).
        """
        if tool_name not in self._stats:
            self._stats[tool_name] = ToolStats(tool_name=tool_name)
        self._stats[tool_name].record_call(success, duration_ms, error_snippet)
        self._save()

    def get_stats(self, tool_name: str) -> Optional[ToolStats]:
        """Retrieve stats for a specific tool."""
        return self._stats.get(tool_name)

    def get_all_stats(self) -> dict[str, ToolStats]:
        """Return all tool stats."""
        return dict(self._stats)

    def get_unreliable_tools(
        self, min_calls: int = 5, max_success_rate: float = 0.6
    ) -> list[str]:
        """Return list of tool names that are unreliable.

        Args:
            min_calls: Minimum number of calls to consider.
            max_success_rate: Tools with success rate below this are unreliable.

        Returns:
            List of tool names sorted alphabetically.
        """
        unreliable = []
        for name, stats in self._stats.items():
            if stats.total_calls >= min_calls and stats.success_rate() < max_success_rate:
                unreliable.append(name)
        unreliable.sort()
        return unreliable
