"""TopicTree: groups memory chunks by topic and produces per-topic summaries.

Part of GitHub issue #536: Memory Tree hierarchy — chunk→score→topic→global pipeline.

For each topic (extracted from chunk tags), TopicTree keeps the top-K highest-scored
chunks and produces a plain-text summary. The tree is rebuilt in the background every
N new chunks so the main hot path is never blocked.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class TopicTree:
    """Groups chunks by topic and maintains per-topic summaries.

    Topics are derived from tags on ContentStore chunks (or MemoryGraph nodes).
    The tree is stored in SQLite for fast lookup.

    Usage::

        tree = TopicTree(db_path)
        tree.update(chunks)          # add/refresh chunks
        result = tree.get_topic("python")   # top chunks + summary
        topics = tree.list_topics()
    """

    def __init__(
        self,
        db_path: str,
        top_k: int = 10,
        rebuild_every_n: int = 20,
    ) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._top_k = top_k
        self._rebuild_every_n = rebuild_every_n
        self._new_since_rebuild = 0
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
CREATE TABLE IF NOT EXISTS topic_chunks (
    topic       TEXT NOT NULL,
    chunk_id    TEXT NOT NULL,
    score       REAL NOT NULL DEFAULT 0.0,
    content     TEXT NOT NULL DEFAULT '',
    added_at    REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (topic, chunk_id)
);
CREATE TABLE IF NOT EXISTS topic_summaries (
    topic       TEXT PRIMARY KEY,
    summary     TEXT NOT NULL DEFAULT '',
    chunk_count INTEGER NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_tc_topic_score ON topic_chunks(topic, score DESC);
""")
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, chunks: List[Dict]) -> int:
        """Add or refresh chunks in the topic index.

        Each dict must have: chunk_id, content, score (float), tags (list[str]).
        Returns number of (topic, chunk) pairs inserted/updated.
        """
        pairs = 0
        now = time.time()
        with self._lock:
            for chunk in chunks:
                chunk_id = chunk.get("chunk_id", "")
                content = chunk.get("content", "")
                score = float(chunk.get("score", 0.0))
                tags = chunk.get("tags") or []
                if isinstance(tags, str):
                    tags = [t.strip() for t in tags.split(",") if t.strip()]

                for topic in tags:
                    topic = topic.strip().lower()
                    if not topic:
                        continue
                    self._conn.execute("""
INSERT INTO topic_chunks (topic, chunk_id, score, content, added_at)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(topic, chunk_id) DO UPDATE SET
    score=excluded.score,
    content=excluded.content,
    added_at=excluded.added_at
""", (topic, chunk_id, score, content, now))
                    pairs += 1
            self._conn.commit()

        self._new_since_rebuild += len(chunks)
        if self._new_since_rebuild >= self._rebuild_every_n:
            self._rebuild_summaries()
            self._new_since_rebuild = 0

        return pairs

    def get_topic(self, topic: str) -> Optional[Dict]:
        """Return top-K chunks and summary for a topic."""
        topic = topic.strip().lower()
        rows = self._conn.execute(
            "SELECT chunk_id, content, score FROM topic_chunks WHERE topic=? ORDER BY score DESC LIMIT ?",
            (topic, self._top_k),
        ).fetchall()
        if not rows:
            return None
        summary_row = self._conn.execute(
            "SELECT summary, chunk_count, updated_at FROM topic_summaries WHERE topic=?",
            (topic,),
        ).fetchone()
        return {
            "topic": topic,
            "top_chunks": [{"chunk_id": r[0], "content": r[1], "score": r[2]} for r in rows],
            "summary": summary_row[0] if summary_row else "",
            "chunk_count": summary_row[1] if summary_row else len(rows),
            "updated_at": summary_row[2] if summary_row else time.time(),
        }

    def list_topics(self) -> List[Dict]:
        """Return all known topics with their chunk count and top score."""
        rows = self._conn.execute("""
SELECT tc.topic, COUNT(*) as cnt, MAX(tc.score) as top_score, ts.summary
FROM topic_chunks tc
LEFT JOIN topic_summaries ts ON ts.topic = tc.topic
GROUP BY tc.topic
ORDER BY top_score DESC
""").fetchall()
        return [
            {"topic": r[0], "chunk_count": r[1], "top_score": r[2], "summary": r[3] or ""}
            for r in rows
        ]

    def search_topics(self, query: str, limit: int = 5) -> List[Dict]:
        """Find topics whose name or summary contains query keywords."""
        tokens = [t.lower() for t in query.split() if t]
        all_topics = self.list_topics()
        scored: List[Tuple[int, Dict]] = []
        for t in all_topics:
            hits = sum(
                1 for tok in tokens
                if tok in t["topic"] or tok in (t["summary"] or "").lower()
            )
            if hits > 0:
                scored.append((hits, t))
        scored.sort(key=lambda x: (-x[0], -x[1]["top_score"]))
        return [d for _, d in scored[:limit]]

    def topic_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(DISTINCT topic) FROM topic_chunks").fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rebuild_summaries(self) -> None:
        """Rebuild per-topic plain-text summaries from top-K chunks."""
        topics = self._conn.execute(
            "SELECT DISTINCT topic FROM topic_chunks"
        ).fetchall()
        now = time.time()
        with self._lock:
            for (topic,) in topics:
                rows = self._conn.execute(
                    "SELECT content FROM topic_chunks WHERE topic=? ORDER BY score DESC LIMIT ?",
                    (topic, self._top_k),
                ).fetchall()
                count = self._conn.execute(
                    "SELECT COUNT(*) FROM topic_chunks WHERE topic=?", (topic,)
                ).fetchone()[0]
                summary = self._build_summary(topic, [r[0] for r in rows])
                self._conn.execute("""
INSERT INTO topic_summaries (topic, summary, chunk_count, updated_at)
VALUES (?, ?, ?, ?)
ON CONFLICT(topic) DO UPDATE SET
    summary=excluded.summary,
    chunk_count=excluded.chunk_count,
    updated_at=excluded.updated_at
""", (topic, summary, count, now))
            self._conn.commit()

    @staticmethod
    def _build_summary(topic: str, contents: List[str]) -> str:
        """Build a concise summary from the top chunks of a topic.

        This is a deterministic extractive summary (no LLM needed):
        takes the first sentence from each of the top-3 chunks.
        """
        if not contents:
            return f"Topic: {topic} (no content)"
        sentences = []
        for c in contents[:3]:
            # Take first non-empty line as representative sentence
            for line in c.splitlines():
                line = line.strip()
                if len(line) > 20:
                    sentences.append(line[:200])
                    break
        if not sentences:
            return f"Topic: {topic}"
        return f"[{topic}] " + " | ".join(sentences)
