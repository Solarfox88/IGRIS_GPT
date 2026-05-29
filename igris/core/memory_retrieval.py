"""MemoryRetrieval: hierarchical retrieval over the memory tree.

Part of GitHub issue #536: Memory Tree hierarchy — chunk→score→topic→global pipeline.

Query path:
  1. Search TopicTree for matching topics (fast, no LLM)
  2. Drill down to top-K chunks from matching topics via MemoryScorer
  3. Fallback: keyword search on MemoryGraph SQLite if no topic match

Returns chunks ordered by relevance score.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class MemoryRetrieval:
    """Hierarchical retrieval over ContentStore + TopicTree + MemoryGraph.

    Usage::

        retrieval = MemoryRetrieval(content_store, topic_tree, scorer, memory_graph)
        results = retrieval.search("python async error handling", top_k=5)
    """

    def __init__(
        self,
        content_store: Any,       # ContentStore
        topic_tree: Any,          # TopicTree
        scorer: Any,              # MemoryScorer
        memory_graph: Any,        # MemoryGraph
        min_score: float = 0.0,
    ) -> None:
        self._store = content_store
        self._topics = topic_tree
        self._scorer = scorer
        self._graph = memory_graph
        self._min_score = min_score

    def search(
        self,
        query: str,
        top_k: int = 10,
        node_type: Optional[str] = None,
    ) -> List[Dict]:
        """Return top-k chunks relevant to query, ordered by score.

        Strategy:
        1. Extract keywords from query
        2. Search TopicTree for matching topics
        3. Collect top-scored chunks from matching topics
        4. Fallback to keyword search on MemoryGraph if results < top_k
        5. Deduplicate and sort by score
        """
        keywords = self._extract_keywords(query)
        results: Dict[str, Dict] = {}  # chunk_id -> result dict

        # Step 1: topic-based retrieval
        if keywords:
            matching_topics = self._topics.search_topics(query, limit=5)
            for topic_info in matching_topics:
                topic_data = self._topics.get_topic(topic_info["topic"])
                if not topic_data:
                    continue
                for chunk in topic_data.get("top_chunks", [])[:top_k]:
                    cid = chunk["chunk_id"]
                    score = chunk.get("score", 0.0)
                    if score >= self._min_score and cid not in results:
                        results[cid] = {
                            "chunk_id": cid,
                            "content": chunk.get("content", ""),
                            "score": score,
                            "source": "topic_tree",
                            "topic": topic_info["topic"],
                        }

        # Step 2: top-k from scorer (by stored score, optionally filtered)
        scorer_top = self._scorer.top_k(k=top_k * 2, node_type=node_type)
        for cid, score in scorer_top:
            if cid in results:
                continue
            if score < self._min_score:
                continue
            # Try to get content from ContentStore
            chunk_data = self._get_chunk_content(cid, node_type)
            if chunk_data and self._matches_query(chunk_data.get("content", ""), keywords):
                results[cid] = {
                    "chunk_id": cid,
                    "content": chunk_data.get("content", ""),
                    "score": score,
                    "source": "scorer",
                    "node_type": chunk_data.get("node_type", node_type or ""),
                }

        # Step 3: keyword fallback on MemoryGraph
        if len(results) < top_k and keywords:
            graph_nodes = self._graph.query_by_intent(query, node_type=node_type, limit=top_k)
            for node in graph_nodes:
                nid = node.get("node_id", "")
                if nid in results:
                    continue
                content = self._node_to_text(node)
                score = self._scorer.get_score(nid) or 0.0
                if score < self._min_score:
                    score = 0.1  # give small base score for keyword matches
                results[nid] = {
                    "chunk_id": nid,
                    "content": content,
                    "score": score,
                    "source": "memory_graph",
                    "node_type": node.get("node_type", ""),
                }

        # Sort by score descending, return top_k
        sorted_results = sorted(results.values(), key=lambda x: x["score"], reverse=True)
        return sorted_results[:top_k]

    def drill_down(self, topic: str, top_k: int = 5) -> List[Dict]:
        """Retrieve top chunks for a specific topic."""
        topic_data = self._topics.get_topic(topic)
        if not topic_data:
            return []
        chunks = topic_data.get("top_chunks", [])[:top_k]
        return [
            {
                "chunk_id": c["chunk_id"],
                "content": c.get("content", ""),
                "score": c.get("score", 0.0),
                "topic": topic,
                "source": "topic_drill_down",
            }
            for c in chunks
        ]

    def get_global_digest(self, day_key: Optional[str] = None) -> Optional[Dict]:
        """Retrieve the global digest for today (or a specific day)."""
        import time
        if day_key is None:
            day_key = time.strftime("%Y-%m-%d", time.gmtime())
        # Try ContentStore first
        all_digests = self._store.read_all(node_type="global_digest")
        for d in all_digests:
            if d.get("day") == day_key or day_key in d.get("chunk_id", ""):
                return d
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_keywords(self, query: str) -> List[str]:
        """Extract meaningful keywords from a query string."""
        stopwords = {
            "the", "a", "an", "is", "in", "on", "at", "to", "for",
            "of", "and", "or", "with", "by", "from", "that", "this",
            "are", "was", "be", "been", "have", "has", "it", "its",
            "do", "does", "not", "but", "if", "as", "can",
        }
        words = re.findall(r"\w+", query.lower())
        return [w for w in words if w not in stopwords and len(w) >= 3]

    def _matches_query(self, content: str, keywords: List[str]) -> bool:
        """True if content contains at least one query keyword."""
        if not keywords:
            return True
        text = content.lower()
        return any(kw in text for kw in keywords)

    def _get_chunk_content(self, chunk_id: str, node_type: Optional[str] = None) -> Optional[Dict]:
        """Try to get chunk content from ContentStore (search all types if node_type unknown)."""
        if node_type:
            result = self._store.read(node_type, chunk_id)
            if result:
                return result
        # Search across all node types
        all_chunks = self._store.read_all()
        for c in all_chunks:
            if c.get("chunk_id") == chunk_id:
                return c
        return None

    @staticmethod
    def _node_to_text(node: Dict) -> str:
        """Convert a MemoryGraph node dict to searchable text."""
        import json
        content = node.get("content", {})
        if isinstance(content, dict):
            return json.dumps(content, ensure_ascii=False)
        return str(content)
