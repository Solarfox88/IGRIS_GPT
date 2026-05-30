"""Long-term persistent memory with domain index and rolling summary.

Provides LongTermMemory for storing/retrieving persistent facts across sessions,
and MemoryRetriever for context-aware retrieval with decay and relevance scoring.
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class MemoryFact:
    """A single stored fact with metadata."""
    key: str
    value: str
    domain: str = "general"
    tags: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    ttl: Optional[float] = None  # seconds relative to updated_at; None = no expiry
    importance: float = 1.0  # 0.0 to 1.0 for decay weighting

    def is_expired(self, now: float | None = None) -> bool:
        if self.ttl is None:
            return False
        now = now or time.time()
        return now - self.updated_at > self.ttl

    def touch(self) -> None:
        self.access_count += 1
        self.last_accessed = time.time()


@dataclass
class RollingSummary:
    """Compact summary of recent/high-value memories for a domain."""
    domain: str
    summary_text: str = ""
    last_updated: float = field(default_factory=time.time)
    fact_keys: Set[str] = field(default_factory=set)

    def update(self, facts: List[MemoryFact], max_summary_length: int = 500) -> None:
        """Regenerate summary from a list of facts (most recent first)."""
        sorted_facts = sorted(facts, key=lambda f: f.updated_at, reverse=True)[:10]
        lines = []
        for f in sorted_facts:
            line = f"{f.key}: {f.value[:80]}"
            lines.append(line)
        self.summary_text = "\n".join(lines)[:max_summary_length]
        self.fact_keys = {f.key for f in sorted_facts}
        self.last_updated = time.time()


# ---------------------------------------------------------------------------
# Memory store
# ---------------------------------------------------------------------------


class LongTermMemory:
    """Persistent, domain-indexed memory with rolling summaries and TTL-based expiry.

    Supports JSON serialisation to disk, domain-based queries, importance-weighted
    retrieval, and automatic decaying of rarely accessed facts.
    """

    def __init__(self, storage_path: str | Path | None = None):
        self._storage_path: Path
        if storage_path:
            self._storage_path = Path(storage_path)
        else:
            base = os.environ.get("IGRIS_DATA_DIR", "/tmp/igris_data")
            self._storage_path = Path(base) / "long_term_memory.json"
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)

        self._facts: Dict[str, MemoryFact] = {}  # key -> fact
        self._domain_index: Dict[str, Set[str]] = defaultdict(set)  # domain -> set of keys
        self._tag_index: Dict[str, Set[str]] = defaultdict(set)  # tag -> set of keys
        self._rollups: Dict[str, RollingSummary] = {}  # domain -> summary

        self._load()

    # ---- persistence ----

    def _load(self) -> None:
        if not self._storage_path.exists():
            return
        try:
            raw = json.loads(self._storage_path.read_text())
            for fact_dict in raw.get("facts", []):
                f = MemoryFact(**fact_dict)
                self._facts[f.key] = f
                self._domain_index[f.domain].add(f.key)
                for tag in f.tags:
                    self._tag_index[tag].add(f.key)
            for rollup_dict in raw.get("rollups", []):
                rs = RollingSummary(**rollup_dict)
                self._rollups[rs.domain] = rs
        except Exception:
            # Corrupted file -> start fresh
            self._facts.clear()
            self._domain_index.clear()
            self._tag_index.clear()
            self._rollups.clear()

    def _save(self) -> None:
        data = {
            "facts": [asdict(f) for f in self._facts.values()],
            "rollups": [asdict(rs) for rs in self._rollups.values()],
        }
        self._storage_path.write_text(json.dumps(data, indent=2))

    # ---- CRUD ----

    def store(self, key: str, value: str, domain: str = "general",
              tags: List[str] | None = None, ttl: float | None = None,
              importance: float = 1.0) -> None:
        """Store a new fact, or update an existing one."""
        now = time.time()
        if key in self._facts:
            fact = self._facts[key]
            fact.value = value
            fact.domain = domain
            fact.tags = tags or []
            fact.updated_at = now
            fact.ttl = ttl
            fact.importance = importance
            fact.touch()
        else:
            fact = MemoryFact(
                key=key,
                value=value,
                domain=domain,
                tags=tags or [],
                created_at=now,
                updated_at=now,
                ttl=ttl,
                importance=importance,
            )
            self._facts[key] = fact
            self._domain_index[domain].add(key)
            for tag in (tags or []):
                self._tag_index[tag].add(key)
        # Update rolling summary for the domain
        domain_facts = self.get_by_domain(domain, include_expired=False)
        if domain not in self._rollups:
            self._rollups[domain] = RollingSummary(domain=domain)
        self._rollups[domain].update(domain_facts)
        self._save()

    def get(self, key: str) -> Optional[MemoryFact]:
        fact = self._facts.get(key)
        if fact is None:
            return None
        if fact.is_expired():
            self._delete_fact(key)
            self._save()
            return None
        fact.touch()
        self._save()
        return fact

    def delete(self, key: str) -> bool:
        if key not in self._facts:
            return False
        self._delete_fact(key)
        self._save()
        return True

    def _delete_fact(self, key: str) -> None:
        fact = self._facts.pop(key, None)
        if fact is None:
            return
        self._domain_index[fact.domain].discard(key)
        if not self._domain_index[fact.domain]:
            del self._domain_index[fact.domain]
        for tag in fact.tags:
            self._tag_index[tag].discard(key)
            if not self._tag_index[tag]:
                del self._tag_index[tag]

    # ---- queries ----

    def get_by_domain(self, domain: str, include_expired: bool = False) -> List[MemoryFact]:
        keys = self._domain_index.get(domain, set())
        facts = []
        now = time.time()
        for k in keys:
            f = self._facts.get(k)
            if f is None:
                continue
            if not include_expired and f.is_expired(now):
                continue
            facts.append(f)
        return facts

    def get_by_tag(self, tag: str, include_expired: bool = False) -> List[MemoryFact]:
        keys = self._tag_index.get(tag, set())
        facts = []
        now = time.time()
        for k in keys:
            f = self._facts.get(k)
            if f is None:
                continue
            if not include_expired and f.is_expired(now):
                continue
            facts.append(f)
        return facts

    def get_all(self, include_expired: bool = False) -> List[MemoryFact]:
        now = time.time()
        if include_expired:
            return list(self._facts.values())
        return [f for f in self._facts.values() if not f.is_expired(now)]

    def get_domain_summary(self, domain: str) -> Optional[str]:
        rs = self._rollups.get(domain)
        if rs is None:
            return None
        # Check if summary is stale relative to latest fact updates
        domain_facts = self.get_by_domain(domain, include_expired=False)
        if domain_facts:
            latest = max(f.updated_at for f in domain_facts)
            if latest > rs.last_updated:
                rs.update(domain_facts)
                self._save()
        return rs.summary_text

    def search(self, query: str, max_results: int = 10) -> List[Tuple[MemoryFact, float]]:
        """Simple substring search over keys and values, scored by importance and recency."""
        now = time.time()
        results = []
        q = query.lower()
        for fact in self._facts.values():
            if fact.is_expired(now):
                continue
            score = 0.0
            if q in fact.key.lower():
                score += 0.5
            if q in fact.value.lower():
                score += 0.3
            if q in fact.domain.lower():
                score += 0.2
            # Add decay: higher importance, more recent = higher score
            recency_factor = 1.0 - min(1.0, (now - fact.updated_at) / (86400 * 30))  # 30 day half-life
            score += fact.importance * recency_factor * 0.5
            if score > 0.0:
                results.append((fact, score))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:max_results]

    def clear_expired(self) -> int:
        """Remove all expired facts and return count removed."""
        now = time.time()
        to_remove = [k for k, f in self._facts.items() if f.is_expired(now)]
        for k in to_remove:
            self._delete_fact(k)
        if to_remove:
            self._save()
        return len(to_remove)

    def fact_count(self) -> int:
        return len(self._facts)


# ---------------------------------------------------------------------------
# MemoryRetriever: context-aware retrieval with decay and relevance
# ---------------------------------------------------------------------------


class MemoryRetriever:
    """High-level retriever that combines multiple memory sources with scoring."""

    def __init__(self, long_term_memory: LongTermMemory, decay_rate: float = 0.9):
        self._ltm = long_term_memory
        self._decay_rate = decay_rate

    def retrieve(self, query: str, domains: List[str] | None = None,
                 tags: List[str] | None = None,
                 max_results: int = 5) -> List[MemoryFact]:
        """Retrieve facts matching query, optionally filtered by domains and tags.

        Returns facts sorted by relevance score (descending).
        """
        candidates: Dict[str, MemoryFact] = {}

        if domains:
            for d in domains:
                for f in self._ltm.get_by_domain(d):
                    candidates[f.key] = f
        if tags:
            for t in tags:
                for f in self._ltm.get_by_tag(t):
                    candidates[f.key] = f

        if not domains and not tags:
            # Use search directly
            scored = self._ltm.search(query, max_results=max_results)
            return [f for f, _ in scored]

        # Score candidates
        now = time.time()
        scored: List[Tuple[MemoryFact, float]] = []
        q = query.lower()
        for fact in candidates.values():
            if fact.is_expired(now):
                continue
            score = 0.0
            if q in fact.key.lower():
                score += 0.4
            if q in fact.value.lower():
                score += 0.3
            if q in fact.domain.lower():
                score += 0.2
            # Recency bonus
            hours_since_access = (now - fact.last_accessed) / 3600
            decay = self._decay_rate ** hours_since_access
            score += fact.importance * decay * 0.5
            scored.append((fact, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [f for f, _ in scored[:max_results]]

    def get_relevant_summaries(self, domains: List[str] | None = None) -> Dict[str, str]:
        """Get rolling summaries for given domains (or all if None)."""
        if domains:
            return {d: s for d in domains if (s := self._ltm.get_domain_summary(d))}
        # All domains
        all_domains = set(self._ltm._domain_index.keys())  # access internal for completeness
        return {d: s for d in all_domains if (s := self._ltm.get_domain_summary(d))}

    def store_and_retrieve(self, key: str, value: str, domain: str = "general",
                           tags: List[str] | None = None,
                           ttl: float | None = None,
                           importance: float = 1.0,
                           query: str | None = None,
                           max_results: int = 5) -> List[MemoryFact]:
        """Store a fact and return related facts based on optional query."""
        self._ltm.store(key, value, domain, tags, ttl, importance)
        q = query or value
        return self.retrieve(q, domains=[domain] if domain else None, max_results=max_results)
