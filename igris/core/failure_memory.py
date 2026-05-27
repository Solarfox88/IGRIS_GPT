"""Failure memory for IGRIS SelfRepairSupervisor.

Records structured failure patterns from blocked/failed runs and provides
similarity-based risk scoring for new missions.  All data is persisted in
.igris/failure_patterns.json.  The module is intentionally simple: keyword
overlap is enough to surface relevant history without requiring embeddings.

Public API
----------
FailureMemory.record(goal, failure_class, capability_signals, repair_cycles)
    Persist a new failure entry (call after any blocked/failed run).

FailureMemory.check(goal) -> FailureRisk
    Return a FailureRisk summary for a new mission goal.

FailureRisk
    .risk_level: "low" | "medium" | "high"
    .similar_count: int
    .dominant_failure: str
    .notes: list[str]
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_DEFAULT_STORE = Path(".igris/failure_patterns.json")

# Minimum keyword overlap (intersection / union) to call two goals "similar".
_SIMILARITY_THRESHOLD = 0.20

# Words filtered from keyword extraction (too common to be meaningful).
_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "to", "in", "for", "with",
    "add", "new", "fix", "get", "set", "run", "use", "on", "at",
    "is", "it", "be", "as", "by", "from", "that", "this", "so",
    "we", "do", "no", "if", "not", "but",
})

_MAX_PATTERNS = 200   # hard cap — oldest entries evicted above this limit
_TTL_DAYS = 30        # entries older than this many days are pruned on every write


def _keywords(text: str) -> frozenset:
    tokens = re.findall(r"[a-z][a-z0-9_]{2,}", text.lower())
    return frozenset(t for t in tokens if t not in _STOP_WORDS)


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


@dataclass
class FailureRisk:
    risk_level: str = "low"        # "low" | "medium" | "high"
    similar_count: int = 0
    dominant_failure: str = ""
    notes: List[str] = field(default_factory=list)
    file_risks: Dict[str, str] = field(default_factory=dict)


class FailureMemory:
    """Persistent failure pattern store."""

    def __init__(self, store_path: Path = _DEFAULT_STORE) -> None:
        self._path = store_path
        self._patterns: List[Dict[str, Any]] = []
        self._file_patterns: Dict[str, Dict[str, Any]] = {}
        self._goal_patterns: Dict[str, Dict[str, Any]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        goal: str,
        failure_class: str,
        capability_signals: Optional[Dict[str, int]] = None,
        repair_cycles: int = 0,
        files_touched: Optional[List[str]] = None,
    ) -> None:
        """Persist a failure pattern from a blocked/failed run."""
        now_ts = time.time()
        now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts))

        # Issue #721 — deduplication: if same failure_class + normalized goal already
        # exists, update the existing entry (increment hit count + last_seen) instead
        # of appending a new one.  Uses first 150 chars of lowercased goal so that
        # "implement X" retried multiple times collapses, while genuinely different
        # goals stay separate.
        _norm_goal = goal.strip().lower()[:150]
        dedup_key = f"{failure_class}::{_norm_goal}"
        for existing in self._patterns:
            existing_norm = existing.get("_norm_goal", existing.get("goal", "").strip().lower()[:150])
            existing_key = f"{existing.get('failure_class', '')}::{existing_norm}"
            if existing_key == dedup_key:
                existing["hit_count"] = int(existing.get("hit_count", 1)) + 1
                existing["last_seen"] = now_str
                break
        else:
            entry: Dict[str, Any] = {
                "id": uuid.uuid4().hex[:12],
                "timestamp": now_ts,
                "last_seen": now_str,
                "hit_count": 1,
                "_norm_goal": _norm_goal,  # internal dedup key, not displayed
                "goal": goal[:500],
                "keywords": sorted(_keywords(goal)),
                "failure_class": failure_class,
                "capability_signals": dict(capability_signals or {}),
                "repair_cycles": repair_cycles,
            }
            self._patterns.append(entry)

        for fp in list(files_touched or []):
            if not fp:
                continue
            agg = self._file_patterns.setdefault(fp, {"failure_classes": {}, "total_failures": 0, "last_failure": now_str})
            agg["failure_classes"][failure_class] = int(agg["failure_classes"].get(failure_class, 0)) + 1
            agg["total_failures"] = int(agg.get("total_failures", 0)) + 1
            agg["last_failure"] = now_str
        gk = " ".join(sorted(_keywords(goal)))[:120] or goal[:120]
        gp = self._goal_patterns.setdefault(gk, {"attempts": 0, "outcomes": [], "last_seen": now_str})
        gp["attempts"] = int(gp.get("attempts", 0)) + 1
        gp["outcomes"] = list(gp.get("outcomes", []))[-9:] + [failure_class]
        gp["last_seen"] = now_str
        # Prune on every write: TTL eviction then hard cap
        self._prune()
        self._save()

    def _prune(self) -> None:
        """Issue #721 — TTL eviction + max-entries cap.

        1. Remove entries older than _TTL_DAYS days (using timestamp).
        2. If still over _MAX_PATTERNS, keep the most recent entries by timestamp.
        """
        cutoff = time.time() - _TTL_DAYS * 86400
        self._patterns = [
            p for p in self._patterns
            if float(p.get("timestamp", 0)) >= cutoff
        ]
        if len(self._patterns) > _MAX_PATTERNS:
            # Sort by timestamp descending, keep newest
            self._patterns = sorted(
                self._patterns,
                key=lambda p: float(p.get("timestamp", 0)),
                reverse=True,
            )[:_MAX_PATTERNS]

    def check(self, goal: str) -> FailureRisk:
        """Return a risk assessment based on past failures similar to goal."""
        goal_kw = _keywords(goal)
        matches: List[Dict[str, Any]] = []
        for p in self._patterns:
            past_kw = frozenset(p.get("keywords") or [])
            if _jaccard(goal_kw, past_kw) >= _SIMILARITY_THRESHOLD:
                matches.append(p)

        if not matches:
            return FailureRisk(risk_level="low")

        # Count failure classes among matches, weighted by hit_count (issue #721
        # dedup merges identical entries but preserves hit_count so risk scoring
        # still reflects how many times each pattern was actually seen).
        class_counts: Dict[str, int] = {}
        for m in matches:
            fc = m.get("failure_class", "unknown")
            weight = int(m.get("hit_count", 1))
            class_counts[fc] = class_counts.get(fc, 0) + weight
        dominant = max(class_counts, key=class_counts.__getitem__)
        # Effective count = sum of hit_counts (how many real failures were seen)
        count = sum(int(m.get("hit_count", 1)) for m in matches)

        if count >= 3:
            risk_level = "high"
        elif count >= 2:
            risk_level = "medium"
        else:
            risk_level = "low"

        notes: List[str] = [
            f"Found {count} similar past failure(s) (dominant: {dominant}).",
        ]
        # Surface capability signals if present
        all_signals: Dict[str, int] = {}
        for m in matches:
            for sig, cnt in (m.get("capability_signals") or {}).items():
                all_signals[sig] = all_signals.get(sig, 0) + cnt
        if all_signals:
            notes.append(f"Accumulated capability signals from history: {all_signals}")

        file_risks: Dict[str, str] = {}
        for fp, agg in self._file_patterns.items():
            tf = int(agg.get("total_failures", 0))
            file_risks[fp] = "high" if tf >= 3 else ("medium" if tf >= 2 else "low")
        return FailureRisk(
            risk_level=risk_level,
            similar_count=count,
            dominant_failure=dominant,
            notes=notes,
            file_risks=file_risks,
        )

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            self._patterns = list(data.get("patterns", data.get("entries", [])))
            self._file_patterns = dict(data.get("file_patterns", {}))
            self._goal_patterns = dict(data.get("goal_patterns", {}))
        except (FileNotFoundError, json.JSONDecodeError, AttributeError):
            self._patterns = []
            self._file_patterns = {}
            self._goal_patterns = {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "patterns": self._patterns,
                        "file_patterns": self._file_patterns,
                        "goal_patterns": self._goal_patterns,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        except OSError:
            pass  # non-fatal: memory is advisory, never blocks a run
