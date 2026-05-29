"""MemoryScorer: computes relevance scores for memory chunks.

Part of GitHub issue #536: Memory Tree hierarchy — chunk→score→topic→global pipeline.

Signals:
  - recency:      exponential decay based on age (half-life configurable)
  - unique_words: vocabulary richness (penalises repetitive content)
  - token_count:  penalises too-short (<50 tokens) or too-long (>2500 tokens) chunks
  - source_weight: lesson > world_state > other node types

Final score = weighted sum of normalised signals, stored in SQLite column `score`.
"""
from __future__ import annotations

import math
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Source-type weights (higher = more important)
SOURCE_WEIGHTS: Dict[str, float] = {
    "lesson": 1.0,
    "world_state_snapshot": 0.9,
    "capability": 0.85,
    "decision": 0.8,
    "run_event": 0.6,
    "command_recipe": 0.75,
    "project_fact": 0.7,
    "identity_fact": 0.65,
    "environment_fact": 0.5,
    # Memory-tree chunk types
    "chunk": 0.8,
    "topic_summary": 0.85,
    "global_digest": 0.9,
}

# Score signal weights (must sum to 1.0)
_W_RECENCY = 0.35
_W_UNIQUE = 0.25
_W_TOKENS = 0.20
_W_SOURCE = 0.20


class MemoryScorer:
    """Computes and persists relevance scores for memory chunks.

    Scores are stored in a lightweight SQLite table so the MemoryGraph
    can ORDER BY score without loading all nodes.
    """

    HALF_LIFE_DAYS: float = 14.0  # recency half-life

    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
CREATE TABLE IF NOT EXISTS chunk_scores (
    chunk_id    TEXT PRIMARY KEY,
    node_type   TEXT NOT NULL DEFAULT '',
    score       REAL NOT NULL DEFAULT 0.0,
    recency_sig REAL NOT NULL DEFAULT 0.0,
    unique_sig  REAL NOT NULL DEFAULT 0.0,
    token_sig   REAL NOT NULL DEFAULT 0.0,
    source_sig  REAL NOT NULL DEFAULT 0.0,
    scored_at   REAL NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_scores_score ON chunk_scores(score DESC);
CREATE INDEX IF NOT EXISTS idx_scores_type  ON chunk_scores(node_type);
""")
        self._conn.commit()

    # ------------------------------------------------------------------
    # Signal computation
    # ------------------------------------------------------------------

    def _recency_signal(self, created_at: float) -> float:
        """Exponential decay: 1.0 at creation, 0.5 after HALF_LIFE_DAYS."""
        age_days = max(0.0, (time.time() - created_at) / 86400.0)
        return math.exp(-math.log(2) * age_days / self.HALF_LIFE_DAYS)

    def _unique_words_signal(self, text: str) -> float:
        """Ratio of unique words to total words, capped at 1.0."""
        words = re.findall(r"\w+", text.lower())
        if not words:
            return 0.0
        return min(1.0, len(set(words)) / len(words))

    def _token_count_signal(self, text: str) -> float:
        """Penalises very short (<50) or very long (>2500) chunks.

        Returns 1.0 in the ideal range [100, 1500] tokens.
        """
        tokens = max(1, len(text) // 4)  # rough: 4 chars per token
        if tokens < 50:
            return tokens / 50.0
        if tokens > 2500:
            return max(0.1, 2500.0 / tokens)
        return 1.0

    def _source_weight_signal(self, node_type: str) -> float:
        return SOURCE_WEIGHTS.get(node_type, 0.6)

    def compute(
        self,
        chunk_id: str,
        node_type: str,
        content: str,
        created_at: Optional[float] = None,
    ) -> float:
        """Compute a score for a chunk without persisting it."""
        if created_at is None:
            created_at = time.time()
        r = self._recency_signal(created_at)
        u = self._unique_words_signal(content)
        t = self._token_count_signal(content)
        s = self._source_weight_signal(node_type)
        return round(
            _W_RECENCY * r + _W_UNIQUE * u + _W_TOKENS * t + _W_SOURCE * s, 6
        )

    def score_and_store(
        self,
        chunk_id: str,
        node_type: str,
        content: str,
        created_at: Optional[float] = None,
    ) -> float:
        """Compute score and persist in SQLite. Returns the score."""
        if created_at is None:
            created_at = time.time()
        r = self._recency_signal(created_at)
        u = self._unique_words_signal(content)
        t = self._token_count_signal(content)
        s = self._source_weight_signal(node_type)
        score = round(_W_RECENCY * r + _W_UNIQUE * u + _W_TOKENS * t + _W_SOURCE * s, 6)
        now = time.time()
        with self._lock:
            self._conn.execute("""
INSERT INTO chunk_scores (chunk_id, node_type, score, recency_sig, unique_sig, token_sig, source_sig, scored_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(chunk_id) DO UPDATE SET
    score=excluded.score,
    recency_sig=excluded.recency_sig,
    unique_sig=excluded.unique_sig,
    token_sig=excluded.token_sig,
    source_sig=excluded.source_sig,
    scored_at=excluded.scored_at
""", (chunk_id, node_type, score, round(r, 6), round(u, 6), round(t, 6), round(s, 6), now))
            self._conn.commit()
        return score

    def get_score(self, chunk_id: str) -> Optional[float]:
        """Return persisted score for a chunk, or None."""
        row = self._conn.execute(
            "SELECT score FROM chunk_scores WHERE chunk_id=?", (chunk_id,)
        ).fetchone()
        return float(row[0]) if row else None

    def top_k(
        self,
        k: int = 20,
        node_type: Optional[str] = None,
    ) -> List[Tuple[str, float]]:
        """Return top-k (chunk_id, score) pairs, optionally filtered by node_type."""
        if node_type:
            rows = self._conn.execute(
                "SELECT chunk_id, score FROM chunk_scores WHERE node_type=? ORDER BY score DESC LIMIT ?",
                (node_type, k),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT chunk_id, score FROM chunk_scores ORDER BY score DESC LIMIT ?",
                (k,),
            ).fetchall()
        return [(r[0], float(r[1])) for r in rows]

    def recompute_all(self, chunks: List[Dict]) -> int:
        """Recompute scores for a batch of chunks (e.g. after decay).

        Each dict must have: chunk_id, node_type, content, created_at (optional).
        Returns number of scores updated.
        """
        updated = 0
        for c in chunks:
            self.score_and_store(
                chunk_id=c["chunk_id"],
                node_type=c.get("node_type", "chunk"),
                content=c.get("content", ""),
                created_at=c.get("created_at"),
            )
            updated += 1
        return updated

    def signals_for(self, chunk_id: str) -> Optional[Dict[str, float]]:
        """Return the stored signal breakdown for a chunk."""
        row = self._conn.execute(
            "SELECT score, recency_sig, unique_sig, token_sig, source_sig FROM chunk_scores WHERE chunk_id=?",
            (chunk_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "score": float(row[0]),
            "recency": float(row[1]),
            "unique_words": float(row[2]),
            "token_count": float(row[3]),
            "source_weight": float(row[4]),
        }
