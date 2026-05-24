"""ToolTracker – per-tool effectiveness statistics with JSON persistence."""

import json
import shutil
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class ToolStats:
    tool_name: str
    total_calls: int = 0
    successes: int = 0
    failures: int = 0
    avg_duration_ms: float = 0.0
    common_error_patterns: list[str] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)


class ToolTracker:
    """Tracks execution stats per tool and persists them atomically to disk."""

    def __init__(self, project_root: str) -> None:
        self.project_root = Path(project_root)
        self.stats_dir = self.project_root / ".igris"
        self.stats_file = self.stats_dir / "tool_stats.json"
        self.stats_dir.mkdir(parents=True, exist_ok=True)
        self._stats: dict[str, ToolStats] = {}
        self._load()

    # ------------------------------------------------------------------ private

    def _load(self) -> None:
        if self.stats_file.exists():
            try:
                raw = json.loads(self.stats_file.read_text(encoding="utf-8"))
                self._stats = {name: ToolStats(**d) for name, d in raw.items()}
            except Exception:
                self._stats = {}

    def _save(self) -> None:
        temp = self.stats_file.with_suffix(".tmp")
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(
                {name: asdict(s) for name, s in self._stats.items()},
                f,
                indent=2,
                default=str,
            )
        shutil.move(str(temp), str(self.stats_file))

    # ------------------------------------------------------------------ public

    def record(
        self,
        tool_name: str,
        success: bool,
        duration_ms: float,
        error_snippet: str | None = None,
    ) -> None:
        """Record a tool invocation, updating running stats."""
        if tool_name not in self._stats:
            self._stats[tool_name] = ToolStats(tool_name=tool_name)

        s = self._stats[tool_name]
        s.total_calls += 1

        if success:
            s.successes += 1
        else:
            s.failures += 1
            if error_snippet:
                snippet = error_snippet.strip()
                if snippet and snippet not in s.common_error_patterns:
                    s.common_error_patterns.append(snippet)
                # keep only the last 5 unique patterns
                if len(s.common_error_patterns) > 5:
                    s.common_error_patterns = s.common_error_patterns[-5:]

        # running average
        if s.total_calls == 1:
            s.avg_duration_ms = duration_ms
        else:
            s.avg_duration_ms = (
                (s.avg_duration_ms * (s.total_calls - 1)) + duration_ms
            ) / s.total_calls

        s.last_updated = time.time()
        self._save()

    def get_stats(self, tool_name: str) -> ToolStats | None:
        """Return stats for *tool_name* or None if never recorded."""
        return self._stats.get(tool_name)

    def get_all_stats(self) -> dict[str, ToolStats]:
        """Return a copy of all recorded stats."""
        return dict(self._stats)

    def get_unreliable_tools(
        self,
        min_calls: int = 5,
        max_success_rate: float = 0.6,
    ) -> list[str]:
        """Return tool names whose success rate is below *max_success_rate*
        given at least *min_calls* recorded invocations."""
        unreliable: list[str] = []
        for name, s in self._stats.items():
            if s.total_calls >= min_calls:
                rate = s.successes / s.total_calls
                if rate < max_success_rate:
                    unreliable.append(name)
        return unreliable
