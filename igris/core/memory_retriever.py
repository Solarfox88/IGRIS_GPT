"""
Memory retriever for contextual retrieval from LongTermMemory.

Provides query-based retrieval with domain filtering and keyword similarity.
Also supports retrieving rolling summaries for a given domain.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from igris.core.long_term_memory import LongTermMemory, MemoryEntry


class MemoryRetriever:
    """Retrieves memory entries based on contextual queries.

    Uses keyword overlap scoring to rank entries by relevance.
    Supports domain-scoped retrieval and rolling summary access.
    """

    def __init__(self, long_term_memory: LongTermMemory) -> None:
        self._ltm = long_term_memory

    def search(
        self,
        query: str,
        domain: Optional[str] = None,
        top_k: int = 10,
    ) -> List[MemoryEntry]:
        """Retrieve memory entries relevant to the query, optionally filtered by domain.

        Args:
            query: Natural language query string.
            domain: Optional domain to restrict search scope.
            top_k: Maximum number of entries to return.

        Returns:
            List of MemoryEntry objects sorted by relevance score.
        """
        entries = self._ltm.get_entries(domain=domain)
        if not entries:
            return []

        query_tokens = self._tokenize(query)
        scored: List[tuple[MemoryEntry, float]] = []
        for entry in entries:
            score = self._compute_relevance(entry, query_tokens)
            if score > 0:
                scored.append((entry, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [entry for entry, _ in scored[:top_k]]

    def get_rolling_summary(self, domain: str) -> str:
        """Retrieve the rolling summary for a given domain.

        Args:
            domain: Domain to fetch summary for.

        Returns:
            Summary string, or empty string if not found.
        """
        return self._ltm.get_rolling_summary(domain)

    def search_summaries(
        self,
        query: str,
        domain: Optional[str] = None,
        top_k: int = 5,
    ) -> List[MemoryEntry]:
        """Retrieve memory entries with summaries matching the query.

        Delegates to search() after expanding with summary text.
        """
        return self.search(query, domain, top_k)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Split text into lowercase word tokens."""
        import re
        return set(re.findall(r'\w+', text.lower()))

    @staticmethod
    def _compute_relevance(entry: MemoryEntry, query_tokens: set[str]) -> float:
        """Compute keyword overlap score between entry content and query tokens."""
        content_tokens = MemoryRetriever._tokenize(entry.content)
        if not content_tokens:
            return 0.0
        overlap = len(query_tokens & content_tokens)
        return overlap / max(len(content_tokens), 1)
