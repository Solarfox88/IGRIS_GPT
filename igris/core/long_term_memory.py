"""
Long-term persistent memory with domain indexing and rolling summary.

Provides LongTermMemory for storing structured memory entries with domain tags,
auto-generated rolling summaries, and MemoryRetriever for contextual lookup.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from igris.core.safety import redact_secrets
from igris.models.config import CONFIG


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class MemoryEntry:
    """A single memory entry with domain tag and metadata."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)
    domain: str = "general"
    content: str = ""
    importance: float = 0.5  # 0.0 (trivial) to 1.0 (critical)
    tags: List[str] = field(default_factory=list)
    source: str = ""  # e.g. "teacher", "gate_override", "user"
    expiry: Optional[float] = None  # None = never expires

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> MemoryEntry:
        return cls(**d)


@dataclass
class RollingSummary:
    """Summarised view of a domain's memory over a rolling window."""
    domain: str
    window_start: float
    window_end: float
    entry_count: int
    summary_text: str
    last_updated: float = field(default_factory=time.time)


@dataclass
class DomainIndex:
    """Index of domains with metadata for fast retrieval."""
    domains: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # domain -> { "last_updated": float, "entry_count": int, "latest_summary": str }


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

_MEMORY_DIR = CONFIG.igris_path / "memory" / "long_term"
_DOMAIN_INDEX_FILE = _MEMORY_DIR / "domain_index.json"
_ENTRIES_DIR = _MEMORY_DIR / "entries"
_SUMMARIES_DIR = _MEMORY_DIR / "summaries"


def _ensure_dirs() -> None:
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    _ENTRIES_DIR.mkdir(parents=True, exist_ok=True)
    _SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)


def _load_domain_index() -> DomainIndex:
    _ensure_dirs()
    if _DOMAIN_INDEX_FILE.exists():
        raw = json.loads(_DOMAIN_INDEX_FILE.read_text())
        return DomainIndex(**raw)
    return DomainIndex()


def _save_domain_index(index: DomainIndex) -> None:
    _DOMAIN_INDEX_FILE.write_text(json.dumps(asdict(index), indent=2))


def _entry_path(entry_id: str) -> Path:
    return _ENTRIES_DIR / f"{entry_id}.json"


def _domain_summary_path(domain: str) -> Path:
    safe_name = domain.replace(" ", "_").replace("/", "_").replace("\\", "_")
    return _SUMMARIES_DIR / f"{safe_name}.json"


# ---------------------------------------------------------------------------
# LongTermMemory
# ---------------------------------------------------------------------------

class LongTermMemory:
    """Persistent memory store with domain indexing and rolling summaries.

    Entries are stored as individual JSON files under .igris/memory/long_term/entries/
    indexed by domain in domain_index.json.  Rolling summaries are regenerated
    periodically when the entry count crosses a threshold.
    """

    def __init__(self, max_entries_per_domain: int = 1000,
                 summary_entry_threshold: int = 50) -> None:
        self._max_entries = max_entries_per_domain
        self._summary_threshold = summary_entry_threshold
        self._domain_index = _load_domain_index()

    # ---- Public API ----

    def store(self, entry: MemoryEntry) -> str:
        """Persist a memory entry, update domain index, and trigger summary if needed."""
        redacted_content = redact_secrets(entry.content)
        entry.content = redacted_content

        # Enforce max entries per domain (evict oldest if necessary)
        self._evict_if_needed(entry.domain)

        # Write entry file
        path = _entry_path(entry.id)
        path.write_text(json.dumps(entry.to_dict(), indent=2))

        # Update domain index
        domain_data = self._domain_index.domains.setdefault(entry.domain, {
            "last_updated": 0.0,
            "entry_count": 0,
            "latest_summary": ""
        })
        domain_data["last_updated"] = time.time()
        domain_data["entry_count"] = domain_data.get("entry_count", 0) + 1

        _save_domain_index(self._domain_index)

        # Check if summary regeneration is needed
        if domain_data["entry_count"] % self._summary_threshold == 0:
            self._regenerate_summary(entry.domain)

        return entry.id

    def retrieve(self, domain: Optional[str] = None,
                 tags: Optional[List[str]] = None,
                 limit: int = 10,
                 min_importance: float = 0.0) -> List[MemoryEntry]:
        """Retrieve memory entries, optionally filtered by domain and tags."""
        entries: List[MemoryEntry] = []
        for entry_file in _ENTRIES_DIR.iterdir():
            if entry_file.suffix != ".json":
                continue
            try:
                entry = MemoryEntry.from_dict(json.loads(entry_file.read_text()))
            except (json.JSONDecodeError, KeyError):
                continue

            if domain and entry.domain != domain:
                continue
            if tags and not set(tags).issubset(set(entry.tags)):
                continue
            if entry.importance < min_importance:
                continue

            entries.append(entry)

        # Sort by timestamp descending, limit
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        return entries[:limit]

    def get_domain_summary(self, domain: str) -> Optional[RollingSummary]:
        """Return the latest rolling summary for a domain, if exists."""
        path = _domain_summary_path(domain)
        if path.exists():
            raw = json.loads(path.read_text())
            return RollingSummary(**raw)
        return None

    def list_domains(self) -> List[str]:
        """Return all known domains."""
        return list(self._domain_index.domains.keys())

    def forget_old_entries(self, max_age_seconds: float = 3600 * 24 * 30) -> int:
        """Remove entries older than max_age_seconds. Returns count removed."""
        now = time.time()
        count = 0
        for entry_file in _ENTRIES_DIR.iterdir():
            if entry_file.suffix != ".json":
                continue
            try:
                entry = MemoryEntry.from_dict(json.loads(entry_file.read_text()))
            except (json.JSONDecodeError, KeyError):
                entry_file.unlink(missing_ok=True)
                count += 1
                continue

            age = now - entry.timestamp
            if entry.expiry is not None and now > entry.expiry:
                entry_file.unlink(missing_ok=True)
                count += 1
                self._decrement_domain_count(entry.domain)
            elif age > max_age_seconds:
                entry_file.unlink(missing_ok=True)
                count += 1
                self._decrement_domain_count(entry.domain)

        return count

    # ---- Internal helpers ----

    def _evict_if_needed(self, domain: str) -> None:
        entries = self.retrieve(domain=domain, limit=self._max_entries + 1)
        if len(entries) > self._max_entries:
            # Remove oldest entries beyond the limit
            to_remove = entries[self._max_entries:]
            for entry in to_remove:
                path = _entry_path(entry.id)
                path.unlink(missing_ok=True)
                self._decrement_domain_count(domain)

    def _decrement_domain_count(self, domain: str) -> None:
        if domain in self._domain_index.domains:
            self._domain_index.domains[domain]["entry_count"] = max(
                0, self._domain_index.domains[domain]["entry_count"] - 1
            )
            _save_domain_index(self._domain_index)

    def _regenerate_summary(self, domain: str) -> None:
        entries = self.retrieve(domain=domain, limit=self._summary_threshold)
        if not entries:
            return

        # Simple concatenation summary (can be replaced with LLM call later)
        summary_text = "; ".join(
            f"{e.timestamp}: {e.content[:200]}" for e in entries[::-1]
        )
        if len(summary_text) > 2000:
            summary_text = summary_text[:2000] + "..."

        summary = RollingSummary(
            domain=domain,
            window_start=entries[-1].timestamp,
            window_end=entries[0].timestamp,
            entry_count=len(entries),
            summary_text=summary_text
        )
        path = _domain_summary_path(domain)
        path.write_text(json.dumps(asdict(summary), indent=2))

        # Update domain index with summary
        if domain in self._domain_index.domains:
            self._domain_index.domains[domain]["latest_summary"] = summary_text
            _save_domain_index(self._domain_index)


# ---------------------------------------------------------------------------
# MemoryRetriever
# ---------------------------------------------------------------------------

class MemoryRetriever:
    """Contextual memory retriever that wraps LongTermMemory with scoring and ranking.

    Provides relevance scoring based on domain match, tag overlap, recency, and importance.
    """

    def __init__(self, memory: LongTermMemory) -> None:
        self._memory = memory

    def query(self, domain: Optional[str] = None,
              tags: Optional[List[str]] = None,
              keywords: Optional[List[str]] = None,
              max_results: int = 10,
              recency_weight: float = 1.0,
              importance_weight: float = 1.0) -> List[MemoryEntry]:
        """Retrieve and score entries based on context."""
        candidates = self._memory.retrieve(domain=domain, tags=tags,
                                            limit=max_results * 3)

        scored: List[tuple[float, MemoryEntry]] = []
        for entry in candidates:
            score = 0.0

            # Domain match bonus
            if domain and entry.domain == domain:
                score += 2.0

            # Tag overlap
            if tags:
                overlap = len(set(tags) & set(entry.tags))
                score += overlap * 1.5

            # Keyword match in content
            if keywords:
                content_lower = entry.content.lower()
                keyword_matches = sum(1 for kw in keywords if kw.lower() in content_lower)
                score += keyword_matches * 1.0

            # Recency (normalised to hours)
            age_hours = (time.time() - entry.timestamp) / 3600
            recency_score = max(0, 1 - (age_hours / 720))  # 30 days = 0
            score += recency_weight * recency_score

            # Importance
            score += importance_weight * entry.importance

            scored.append((score, entry))

        # Sort descending by score, return top max_results
        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:max_results]]

    def query_by_domain(self, domain: str, max_results: int = 10) -> List[MemoryEntry]:
        """Quick retrieval of top entries for a domain, weighted by importance."""
        return self.query(domain=domain, max_results=max_results)

    def query_by_tags(self, tags: List[str], domain: Optional[str] = None,
                      max_results: int = 10) -> List[MemoryEntry]:
        """Retrieve entries matching tags, optionally filtered by domain."""
        return self.query(domain=domain, tags=tags, max_results=max_results)


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def create_long_term_memory() -> LongTermMemory:
    """Create a LongTermMemory instance with default config."""
    return LongTermMemory()


def create_memory_retriever(memory: Optional[LongTermMemory] = None) -> MemoryRetriever:
    """Create a MemoryRetriever wrapping the given or default memory."""
    if memory is None:
        memory = create_long_term_memory()
    return MemoryRetriever(memory)
