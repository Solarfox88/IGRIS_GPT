"""
Long-term persistent memory with domain index and rolling summary.

Stores memory entries keyed by domain, supports rolling summary generation
for maintaining a concise compressed view of past events.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_log = logging.getLogger("igris.memory.long_term")

from igris.core.safety import redact_secrets
from igris.core.redaction import redact_nested as _redact_nested  # noqa: F401
from igris.models.config import CONFIG


# ---------------------------------------------------------------------------
# Ranking helper (#1129)
# ---------------------------------------------------------------------------

def _rank_score(
    entry: "MemoryEntry",
    query_tags: Optional[List[str]] = None,
    now: Optional[float] = None,
) -> float:
    """Compute composite rank score for a memory entry.

    Factors: recency (decay), importance, source confidence,
    tag match bonus, stale penalty, contradiction penalty.
    """
    _now = now or time.time()
    age_hours = max(0, (_now - entry.timestamp) / 3600)
    recency = max(0.0, 1.0 - (age_hours / (24 * 30)))  # decay over 30 days

    tag_bonus = 0.0
    if query_tags:
        overlap = len(set(entry.tags) & set(query_tags))
        tag_bonus = min(0.3, overlap * 0.1)

    stale_penalty = -0.4 if entry.stale else 0.0
    contradiction_penalty = -0.3 if entry.contradiction else 0.0

    score = (
        recency * 0.3
        + entry.importance * 0.3
        + entry.source_confidence * 0.2
        + tag_bonus
        + stale_penalty
        + contradiction_penalty
    )
    return round(score, 4)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class MemoryEntry:
    """A single memory entry with metadata."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    domain: str = ""
    content: Any = field(default_factory=dict)  # supports str or dict
    timestamp: float = field(default_factory=time.time)
    source: str = ""
    tags: List[str] = field(default_factory=list)
    importance: float = 1.0  # 0.0 (low) to 1.0 (high)
    source_confidence: float = 1.0  # 0.0 (untrusted) to 1.0 (verified)
    stale: bool = False  # marked stale by staleness check
    contradiction: bool = False  # marked as contradicting another entry


@dataclass
class DomainIndex:
    """Index of memory entries for a given domain."""
    domain: str = ""
    entries: List[str] = field(default_factory=list)  # list of entry ids
    latest_timestamp: float = 0.0
    entry_count: int = 0


@dataclass
class RollingSummary:
    """Rolling summary of memory entries for a domain."""
    domain: str = ""
    summary: str = ""
    last_updated: float = 0.0
    version: int = 0
    entry_count_since_summary: int = 0


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class LongTermMemory:
    """Persistent, domain-indexed memory with rolling summary."""

    def __init__(
        self,
        base_path: Optional[Path] = None,
        storage_dir: Optional[str] = None,
    ) -> None:
        if storage_dir is not None:
            self._base_path = Path(storage_dir)
        else:
            self._base_path = base_path or Path(CONFIG.igris_dir) / "memory" / "long_term"
        self._base_path.mkdir(parents=True, exist_ok=True)
        self._entries_file = self._base_path / "entries.json"
        self._index_file = self._base_path / "index.json"
        self._summary_file = self._base_path / "summary.json"
        self._entries: Dict[str, MemoryEntry] = {}
        self._index: Dict[str, DomainIndex] = {}
        self._summaries: Dict[str, RollingSummary] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load state from disk.

        Epic #1073: non-silent failure — logs warnings on corrupt/missing files
        and returns empty state rather than crashing the caller.
        """
        if self._entries_file.exists():
            try:
                with open(self._entries_file, "r") as f:
                    raw = json.load(f)
                    for k, v in raw.items():
                        self._entries[k] = MemoryEntry(**v)
            except Exception as exc:
                _log.warning("LongTermMemory: failed to load entries from %s: %s", self._entries_file, exc)
                self._entries = {}  # return empty rather than crash
        if self._index_file.exists():
            try:
                with open(self._index_file, "r") as f:
                    raw = json.load(f)
                    for k, v in raw.items():
                        self._index[k] = DomainIndex(**v)
            except Exception as exc:
                _log.warning("LongTermMemory: failed to load index from %s: %s", self._index_file, exc)
                self._index = {}
        if self._summary_file.exists():
            try:
                with open(self._summary_file, "r") as f:
                    raw = json.load(f)
                    for k, v in raw.items():
                        self._summaries[k] = RollingSummary(**v)
            except Exception as exc:
                _log.warning("LongTermMemory: failed to load summaries from %s: %s", self._summary_file, exc)
                self._summaries = {}

    def _save(self) -> None:
        """Save state to disk."""
        # Convert dataclasses to dicts, redact content (nested)
        entries_dict = {
            eid: asdict(entry)
            for eid, entry in self._entries.items()
        }
        for e in entries_dict.values():
            e["content"] = _redact_nested(e["content"])

        index_dict = {k: asdict(v) for k, v in self._index.items()}
        summary_dict = {k: asdict(v) for k, v in self._summaries.items()}

        with open(self._entries_file, "w") as f:
            json.dump(entries_dict, f, indent=2, default=str)
        with open(self._index_file, "w") as f:
            json.dump(index_dict, f, indent=2, default=str)
        with open(self._summary_file, "w") as f:
            json.dump(summary_dict, f, indent=2, default=str)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_entry(self, domain: str, content: Any, source: str = "",
                  tags: Optional[List[str]] = None,
                  importance: float = 1.0) -> MemoryEntry:
        """Add a memory entry for a given domain."""
        entry = MemoryEntry(
            domain=domain,
            content=content,
            source=source,
            tags=tags or [],
            importance=importance
        )
        self._entries[entry.id] = entry

        # Update domain index
        if domain not in self._index:
            self._index[domain] = DomainIndex(domain=domain)
        idx = self._index[domain]
        idx.entries.append(entry.id)
        idx.latest_timestamp = max(idx.latest_timestamp, entry.timestamp)
        idx.entry_count += 1

        # Invalidate summary so it will be regenerated
        if domain in self._summaries:
            self._summaries[domain].entry_count_since_summary += 1

        self._save()
        return entry

    def get_entries(self, domain: str,
                    limit: int = 100,
                    offset: int = 0) -> List[MemoryEntry]:
        """Retrieve entries for a domain, ordered by timestamp descending."""
        if domain not in self._index:
            return []
        entry_ids = self._index[domain].entries
        # Sort by timestamp descending
        sorted_ids = sorted(
            entry_ids,
            key=lambda eid: self._entries[eid].timestamp,
            reverse=True
        )
        selected = sorted_ids[offset:offset+limit]
        return [self._entries[eid] for eid in selected]

    def store(
        self,
        domain: str,
        content: Any,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        importance: float = 1.0,
    ) -> MemoryEntry:
        """Store a memory entry (convenience alias for add_entry)."""
        meta = metadata or {}
        return self.add_entry(
            domain=domain,
            content=content,
            source=str(meta.get("source", "")),
            tags=tags or [],
            importance=importance,
        )

    def get(self, entry_id: str) -> Optional[MemoryEntry]:
        """Return a single entry by its ID."""
        return self._entries.get(entry_id)

    def get_domain_index(self) -> Dict[str, List[str]]:
        """Return mapping of domain → list of entry IDs."""
        return {domain: list(idx.entries) for domain, idx in self._index.items()}

    def get_rolling_summary(self, domain: str, max_entries: int = 10) -> List[MemoryEntry]:
        """Return the most recent *max_entries* entries for *domain*."""
        return self.get_entries(domain, limit=max_entries)

    def search(self, query: str,
               domains: Optional[List[str]] = None,
               limit: int = 50) -> List[MemoryEntry]:
        """Search entries by keyword in content (case-insensitive substring)."""
        query_lower = query.lower()
        results: List[MemoryEntry] = []
        for entry in self._entries.values():
            if domains and entry.domain not in domains:
                continue
            if query_lower in str(entry.content).lower():
                results.append(entry)
        results.sort(key=lambda e: _rank_score(e), reverse=True)
        return results[:limit]

    def search_entries(self, query: str,
                       domains: Optional[List[str]] = None,
                       limit: int = 50) -> List[MemoryEntry]:
        """Alias for search() for backwards compatibility."""
        return self.search(query, domains=domains, limit=limit)

    def mark_stale(self, entry_id: str) -> bool:
        """Mark an entry as stale (outdated)."""
        entry = self._entries.get(entry_id)
        if entry is None:
            return False
        entry.stale = True
        self._save()
        return True

    def mark_contradiction(self, entry_id: str) -> bool:
        """Mark an entry as contradicting another entry."""
        entry = self._entries.get(entry_id)
        if entry is None:
            return False
        entry.contradiction = True
        self._save()
        return True

    def get_ranked(self, domain: str, limit: int = 20,
                   query_tags: Optional[List[str]] = None) -> List[MemoryEntry]:
        """Return entries ranked by composite score (#1129).

        Ranking factors: recency, importance, source confidence,
        tag/domain match, stale penalty, contradiction penalty.
        """
        if domain not in self._index:
            return []
        entry_ids = self._index[domain].entries
        candidates = [self._entries[eid] for eid in entry_ids if eid in self._entries]
        candidates.sort(key=lambda e: _rank_score(e, query_tags=query_tags), reverse=True)
        return candidates[:limit]

    def memory_influence_report(
        self, used_ids: List[str], reason_map: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Generate a structured influence report for used memories (#1129)."""
        reason_map = reason_map or {}
        report: List[Dict[str, Any]] = []
        for eid in used_ids:
            entry = self._entries.get(eid)
            if entry is None:
                continue
            report.append({
                "id": entry.id,
                "domain": entry.domain,
                "importance": entry.importance,
                "source_confidence": entry.source_confidence,
                "stale": entry.stale,
                "contradiction": entry.contradiction,
                "rank_score": round(_rank_score(entry), 3),
                "why_selected": reason_map.get(eid, "relevance"),
                "tags": entry.tags[:5],
            })
        return report

    def generate_summary(self, domain: str, force: bool = False) -> str:
        """Generate or retrieve a rolling summary for a domain.

        #1129: improved summary includes source distribution, importance
        stats, stale/contradiction counts, and top sources alongside tags.
        """
        if domain not in self._index:
            return ""

        curr = self._summaries.get(domain)
        if curr and not force and curr.entry_count_since_summary < 10:
            return curr.summary

        entries = self.get_entries(domain, limit=100)
        if not entries:
            return ""

        # Tag distribution
        tag_counts: Dict[str, int] = {}
        for e in entries:
            for t in e.tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1
        top_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:5]
        tag_str = ", ".join(f"{tag}({cnt})" for tag, cnt in top_tags)

        # Source distribution
        source_counts: Dict[str, int] = {}
        for e in entries:
            src = e.source or "unknown"
            source_counts[src] = source_counts.get(src, 0) + 1
        top_sources = sorted(source_counts.items(), key=lambda x: -x[1])[:3]
        source_str = ", ".join(f"{s}({c})" for s, c in top_sources)

        # Importance and quality stats
        avg_importance = sum(e.importance for e in entries) / len(entries)
        stale_count = sum(1 for e in entries if e.stale)
        contradiction_count = sum(1 for e in entries if e.contradiction)

        start_ts = min(e.timestamp for e in entries)
        end_ts = max(e.timestamp for e in entries)
        summary_text = (
            f"Domain: {domain} | Entries: {len(entries)} | "
            f"From: {start_ts:.2f} To: {end_ts:.2f} | "
            f"Top tags: {tag_str} | Sources: {source_str} | "
            f"Avg importance: {avg_importance:.2f} | "
            f"Stale: {stale_count} | Contradictions: {contradiction_count}"
        )

        new_summary = RollingSummary(
            domain=domain,
            summary=summary_text,
            last_updated=time.time(),
            version=(curr.version + 1) if curr else 1,
            entry_count_since_summary=0
        )
        self._summaries[domain] = new_summary
        self._save()
        return summary_text

    def get_summary(self, domain: str) -> Optional[str]:
        """Get current summary for a domain if it exists."""
        if domain in self._summaries:
            return self._summaries[domain].summary
        return None

    def delete_entry(self, entry_id: str) -> bool:
        """Delete a specific entry by its ID."""
        if entry_id not in self._entries:
            return False
        entry = self._entries[entry_id]
        domain = entry.domain
        # Remove from index
        if domain in self._index:
            idx = self._index[domain]
            if entry_id in idx.entries:
                idx.entries.remove(entry_id)
                idx.entry_count -= 1
                if idx.entry_count == 0:
                    del self._index[domain]
        # Remove entry
        del self._entries[entry_id]
        self._save()
        return True

    def clear_domain(self, domain: str) -> bool:
        """Remove all entries for a given domain."""
        if domain not in self._index:
            return False
        for eid in self._index[domain].entries:
            del self._entries[eid]
        del self._index[domain]
        if domain in self._summaries:
            del self._summaries[domain]
        self._save()
        return True

    # ------------------------------------------------------------------
    # Epic #1073 — TTL / staleness helpers
    # ------------------------------------------------------------------

    def is_entry_stale(self, entry_id: str, ttl_seconds: float) -> bool:
        """Return True if the entry is older than *ttl_seconds*.

        Useful for callers that want to skip outdated memory facts without
        reading the full entry list.
        """
        entry = self._entries.get(entry_id)
        if entry is None:
            return True
        return (time.time() - entry.timestamp) > ttl_seconds

    def get_fresh_entries(
        self,
        domain: str,
        ttl_seconds: float,
        limit: int = 100,
    ) -> List[MemoryEntry]:
        """Return only entries younger than *ttl_seconds* for *domain*.

        Epic #1073: callers no longer silently receive stale data — entries
        outside the TTL window are excluded. A warning is logged when stale
        entries are present so operators can tune TTL values.
        """
        all_entries = self.get_entries(domain, limit=limit * 2)
        now = time.time()
        fresh = [e for e in all_entries if (now - e.timestamp) <= ttl_seconds]
        stale_count = len(all_entries) - len(fresh)
        if stale_count > 0:
            _log.info(
                "LongTermMemory.get_fresh_entries: domain=%r, %d stale entries skipped (ttl=%.0fs)",
                domain, stale_count, ttl_seconds,
            )
        return fresh[:limit]

    def healthcheck(self) -> Dict[str, Any]:
        """Return a structured health report for the memory store.

        Epic #1073: non-silent — each check logs a warning on failure and
        returns a 'degraded' status so callers can surface the problem.
        """
        report: Dict[str, Any] = {
            "entry_count": 0,
            "domain_count": 0,
            "summary_count": 0,
            "files_ok": True,
            "status": "healthy",
        }
        try:
            report["entry_count"] = len(self._entries)
            report["domain_count"] = len(self._index)
            report["summary_count"] = len(self._summaries)
        except Exception as exc:
            _log.warning("LongTermMemory.healthcheck: failed to count entries: %s", exc)
            report["status"] = "degraded"
            report["error"] = str(exc)
            return report

        # Verify files are readable and not corrupt
        for file_path, label in [
            (self._entries_file, "entries"),
            (self._index_file, "index"),
            (self._summary_file, "summary"),
        ]:
            if file_path.exists():
                try:
                    with open(file_path, "r") as f:
                        json.load(f)
                except Exception as exc:
                    _log.warning("LongTermMemory.healthcheck: %s file corrupt: %s", label, exc)
                    report["files_ok"] = False
                    report["status"] = "degraded"
                    report[f"{label}_error"] = str(exc)[:200]

        return report


# ---------------------------------------------------------------------------
# MemoryRetriever — contextual and recency-based retrieval
# ---------------------------------------------------------------------------

class MemoryRetriever:
    """High-level retriever that wraps a LongTermMemory instance."""

    def __init__(self, memory: LongTermMemory) -> None:
        self._memory = memory

    def retrieve_contextual(
        self,
        domain: str,
        query: str = "",
        limit: int = 10,
    ) -> List[MemoryEntry]:
        """Return entries for *domain* that contain *query* (substring search)."""
        if query:
            return self._memory.search(query, domains=[domain], limit=limit)
        return self._memory.get_entries(domain, limit=limit)

    def retrieve_recent(self, domain: str, limit: int = 10) -> List[MemoryEntry]:
        """Return the *limit* most recent entries for *domain*."""
        return self._memory.get_entries(domain, limit=limit)


# ---------------------------------------------------------------------------
# Backward-compat imports — OTPRecord/GateOverride moved to gate_override.py (#1129)
# ---------------------------------------------------------------------------

from igris.core.gate_override import GateOverride, OTPRecord  # noqa: F401,E402
