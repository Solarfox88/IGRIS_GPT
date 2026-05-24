"""ToolTracker: per-tool effectiveness stats post-turn.

Tracks total calls, successes, failures, average duration,
and common error patterns for each tool. Persists to .igris/tool_stats.json.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


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


class ToolTracker:
    """Records and retrieves tool execution statistics.

    Persistence is handled via atomic write to .igris/tool_stats.json.
    """

    MAX_ERROR_PATTERNS = 5

    def __init__(self, project_root: str) -> None:
        self.project_root = Path(project_root)
        self.stats_dir = self.project_root / ".igris"
        self.stats_file = self.stats_dir / "tool_stats.json"
        self._stats: Dict[str, ToolStats] = {}
        self._load()

    def _load(self) -> None:
        """Load existing stats from the JSON file, if any."""
        if self.stats_file.exists():
            try:
                raw = json.loads(self.stats_file.read_text(encoding="utf-8"))
                for name, data in raw.items():
                    self._stats[name] = ToolStats(
                        tool_name=name,
                        total_calls=data.get("total_calls", 0),
                        successes=data.get("successes", 0),
                        failures=data.get("failures", 0),
                        avg_duration_ms=data.get("avg_duration_ms", 0.0),
                        common_error_patterns=data.get(
                            "common_error_patterns", []
                        ),
                        last_updated=data.get("last_updated", time.time()),
                    )
            except (json.JSONDecodeError, OSError):
                # If corrupted, start fresh.
                self._stats = {}

    def _save(self) -> None:
        """Atomically persist the current stats."""
        self.stats_dir.mkdir(parents=True, exist_ok=True)
        data = {
            name: {
                "tool_name": s.tool_name,
                "total_calls": s.total_calls,
                "successes": s.successes,
                "failures": s.failures,
                "avg_duration_ms": s.avg_duration_ms,
                "common_error_patterns": s.common_error_patterns,
                "last_updated": s.last_updated,
            }
            for name, s in self._stats.items()
        }
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=self.stats_dir,
            prefix="tool_stats_",
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as tmpf:
            json.dump(data, tmpf, indent=2, ensure_ascii=False)
            tmpf.flush()
            os.replace(tmpf.name, self.stats_file)

    def record(
        self,
        tool_name: str,
        success: bool,
        duration_ms: float,
        error_snippet: Optional[str] = None,
    ) -> None:
        """Record an execution of *tool_name*.

        Args:
            tool_name: Name of the tool.
            success: Whether the execution succeeded.
            duration_ms: Duration in milliseconds.
            error_snippet: A short, unique error snippet for tracking patterns.
        """
        stats = self._stats.get(tool_name)
        if stats is None:
            stats = ToolStats(tool_name=tool_name)
            self._stats[tool_name] = stats

        # Update running average: new_avg = old_avg + (value - old_avg) / n
        n = stats.total_calls + 1
        stats.avg_duration_ms = (
            stats.avg_duration_ms * (n - 1) + duration_ms
        ) / n

        stats.total_calls = n
        if success:
            stats.successes += 1
        else:
            stats.failures += 1

        if error_snippet:
            snippet = error_snippet.strip()[:500]  # reasonable cap
            if snippet not in stats.common_error_patterns:
                stats.common_error_patterns.append(snippet)
                if len(stats.common_error_patterns) > self.MAX_ERROR_PATTERNS:
                    stats.common_error_patterns.pop(0)

        stats.last_updated = time.time()
        self._save()

    def get_stats(self, tool_name: str) -> Optional[ToolStats]:
        """Return stats for a tool, or None."""
        return self._stats.get(tool_name)

    def get_all_stats(self) -> Dict[str, ToolStats]:
        """Return all tool stats."""
        return dict(self._stats)

    def get_unreliable_tools(
        self,
        min_calls: int = 5,
        max_success_rate: float = 0.6,
    ) -> List[str]:
        """Return tool names with success rate below *max_success_rate*
        among tools with at least *min_calls*.
        """
        unreliable = []
        for name, s in self._stats.items():
            if s.total_calls >= min_calls:
                rate = s.successes / s.total_calls if s.total_calls else 0.0
                if rate < max_success_rate:
                    unreliable.append(name)
        return sorted(unreliable)
