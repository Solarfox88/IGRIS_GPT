"""ToolTracker: per-tool effectiveness statistics with persistence."""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock


@dataclass
class ToolStats:
    """Aggregated stats for a single tool."""
    tool_name: str
    total_calls: int = 0
    successes: int = 0
    failures: int = 0
    avg_duration_ms: float = 0.0
    common_error_patterns: list[str] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)


class ToolTracker:
    """Tracks per-tool effectiveness: calls, successes, failures, avg duration, error patterns.

    Stats are persisted to .igris/tool_stats.json atomically.
    """

    def __init__(self, project_root: str) -> None:
        self._project_root = Path(project_root)
        self._stats_file = self._project_root / ".igris" / "tool_stats.json"
        self._lock = Lock()
        self._stats: dict[str, ToolStats] = {}
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self,
               tool_name: str,
               success: bool,
               duration_ms: float,
               error_snippet: str | None = None) -> None:
        """Record a tool invocation.

        Updates running average for duration and deduplicated error patterns.
        """
        if not tool_name:
            return

        with self._lock:
            stats = self._stats.get(tool_name)
            if stats is None:
                stats = ToolStats(tool_name=tool_name)
                self._stats[tool_name] = stats

            # Update counts
            stats.total_calls += 1
            if success:
                stats.successes += 1
            else:
                stats.failures += 1

            # Running average for duration
            if stats.total_calls == 1:
                stats.avg_duration_ms = duration_ms
            else:
                stats.avg_duration_ms = (
                    (stats.avg_duration_ms * (stats.total_calls - 1) + duration_ms)
                    / stats.total_calls
                )

            # Error patterns (dedup, max 5)
            if not success and error_snippet:
                snippet = error_snippet.strip()
                if snippet and snippet not in stats.common_error_patterns:
                    stats.common_error_patterns.append(snippet)
                    if len(stats.common_error_patterns) > 5:
                        stats.common_error_patterns = stats.common_error_patterns[-5:]

            stats.last_updated = time.time()
            self._persist()

    def get_stats(self, tool_name: str) -> ToolStats | None:
        """Return stats for a specific tool, or None if never recorded."""
        with self._lock:
            return self._stats.get(tool_name)

    def get_all_stats(self) -> dict[str, ToolStats]:
        """Return a shallow copy of all stats, keyed by tool name."""
        with self._lock:
            return dict(self._stats)

    def get_unreliable_tools(self,
                             min_calls: int = 5,
                             max_success_rate: float = 0.6) -> list[str]:
        """Return tool names with success rate <= max_success_rate over at least min_calls."""
        unreliable: list[str] = []
        with self._lock:
            for name, stats in self._stats.items():
                if stats.total_calls >= min_calls:
                    rate = stats.successes / stats.total_calls if stats.total_calls > 0 else 0.0
                    if rate <= max_success_rate:
                        unreliable.append(name)
        return unreliable

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load existing stats from JSON file, if present."""
        if not self._stats_file.exists():
            return

        try:
            data = json.loads(self._stats_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        for name, raw in data.items():
            stats = ToolStats(
                tool_name=name,
                total_calls=raw.get("total_calls", 0),
                successes=raw.get("successes", 0),
                failures=raw.get("failures", 0),
                avg_duration_ms=raw.get("avg_duration_ms", 0.0),
                common_error_patterns=raw.get("common_error_patterns", []),
                last_updated=raw.get("last_updated", time.time()),
            )
            self._stats[name] = stats

    def _persist(self) -> None:
        """Atomically write stats to JSON file."""
        # Ensure directory exists
        self._stats_file.parent.mkdir(parents=True, exist_ok=True)

        # Build serializable dict
        serializable: dict = {}
        for name, stats in self._stats.items():
            serializable[name] = {
                "tool_name": stats.tool_name,
                "total_calls": stats.total_calls,
                "successes": stats.successes,
                "failures": stats.failures,
                "avg_duration_ms": stats.avg_duration_ms,
                "common_error_patterns": stats.common_error_patterns,
                "last_updated": stats.last_updated,
            }

        # Write to temp file then rename for atomicity
        tmp = self._stats_file.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._stats_file)
        except OSError:
            # If rename fails, attempt direct write as fallback
            self._stats_file.write_text(
                json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8"
            )
