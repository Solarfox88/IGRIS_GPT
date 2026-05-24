"""ToolTracker — per-tool effectiveness stats post-turn (Issue #534).

Tracks tool call outcomes (success/failure, duration, error patterns) and persists
to `.igris/tool_stats.json` using atomic writes. Provides query methods for
unreliable tools to inform context-sensitive warnings.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ToolStats:
    """Per-tool effectiveness statistics."""
    tool_name: str
    total_calls: int = 0
    successes: int = 0
    failures: int = 0
    avg_duration_ms: float = 0.0
    common_error_patterns: List[str] = field(default_factory=list)
    last_updated: float = 0.0


class ToolTracker:
    """Collects and persists per-tool effectiveness stats.

    Usage::

        tracker = ToolTracker(project_root="/path/to/project")
        tracker.record("bash", success=True, duration_ms=123.4)
        tracker.record("bash", success=False, duration_ms=500.0, error_snippet="Permission denied")
        stats = tracker.get_stats("bash")
        unreliable = tracker.get_unreliable_tools()
    """

    DEFAULT_STATS_FILE = ".igris/tool_stats.json"
    MAX_ERROR_PATTERNS = 5

    def __init__(self, project_root: str) -> None:
        self._project_root = Path(project_root)
        self._stats_file = self._project_root / self.DEFAULT_STATS_FILE
        self._stats: Dict[str, ToolStats] = {}
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
        """Record the outcome of a single tool call.

        Updates the running average duration and maintains a bounded list of
        unique error snippets (last 5).
        """
        stats = self._get_or_create(tool_name)
        stats.total_calls += 1
        if success:
            stats.successes += 1
        else:
            stats.failures += 1
            if error_snippet:
                self._add_error_pattern(stats, error_snippet.strip())

        # Update running average duration using Welford's online algorithm
        prev_avg = stats.avg_duration_ms
        n = stats.total_calls
        if n == 1:
            stats.avg_duration_ms = duration_ms
        else:
            stats.avg_duration_ms = prev_avg + (duration_ms - prev_avg) / n

        stats.last_updated = time.time()
        self._save()

    def get_stats(self, tool_name: str) -> Optional[ToolStats]:
        """Return stats for *tool_name*, or ``None`` if never recorded."""
        return self._stats.get(tool_name)

    def get_all_stats(self) -> Dict[str, ToolStats]:
        """Return a copy of all current stats."""
        return dict(self._stats)

    def get_unreliable_tools(
        self,
        min_calls: int = 5,
        max_success_rate: float = 0.6,
    ) -> List[str]:
        """Return tool names that have at least *min_calls* total calls
        and a success rate ≤ *max_success_rate*.
        """
        unreliable = []
        for name, stats in self._stats.items():
            if stats.total_calls < min_calls:
                continue
            if stats.total_calls == 0:
                continue
            success_rate = stats.successes / stats.total_calls
            if success_rate <= max_success_rate:
                unreliable.append(name)
        return unreliable

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_or_create(self, tool_name: str) -> ToolStats:
        if tool_name not in self._stats:
            self._stats[tool_name] = ToolStats(tool_name=tool_name)
        return self._stats[tool_name]

    def _add_error_pattern(self, stats: ToolStats, snippet: str) -> None:
        # Omit if already present (dedup)
        if snippet in stats.common_error_patterns:
            return
        stats.common_error_patterns.append(snippet)
        # Keep only the last MAX_ERROR_PATTERNS items
        if len(stats.common_error_patterns) > self.MAX_ERROR_PATTERNS:
            stats.common_error_patterns = stats.common_error_patterns[-self.MAX_ERROR_PATTERNS:]

    def _load(self) -> None:
        """Load stats from the JSON file, if it exists and is valid."""
        if not self._stats_file.exists():
            return
        try:
            data = json.loads(self._stats_file.read_text(encoding="utf-8"))
            for name, raw in data.items():
                stats = ToolStats(
                    tool_name=name,
                    total_calls=raw.get("total_calls", 0),
                    successes=raw.get("successes", 0),
                    failures=raw.get("failures", 0),
                    avg_duration_ms=raw.get("avg_duration_ms", 0.0),
                    common_error_patterns=raw.get("common_error_patterns", []),
                    last_updated=raw.get("last_updated", 0.0),
                )
                self._stats[name] = stats
        except Exception:
            logger.exception("Failed to load tool stats; starting fresh")
            self._stats = {}

    def _save(self) -> None:
        """Persist stats atomically to avoid corruption."""
        out = {}
        for name, stats in self._stats.items():
            out[name] = {
                "tool_name": stats.tool_name,
                "total_calls": stats.total_calls,
                "successes": stats.successes,
                "failures": stats.failures,
                "avg_duration_ms": stats.avg_duration_ms,
                "common_error_patterns": stats.common_error_patterns,
                "last_updated": stats.last_updated,
            }
        tmp_path = self._stats_file.with_suffix(".tmp")
        try:
            tmp_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
            os.replace(tmp_path, self._stats_file)
        except Exception:
            logger.exception("Failed to save tool stats")
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
