from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


class LongTermMemory:
    """
    Long-term persistent memory with domain indexing and rolling summary.
    Stores memories in a SQLite database in the .igris directory.
    """

    def __init__(self, project_root: str) -> None:
        self.project_root = Path(project_root)
        mem_dir = self.project_root / ".igris"
        mem_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = mem_dir / "long_term_memory.db"
        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.db_path))
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                timestamp REAL NOT NULL,
                content TEXT NOT NULL,
                embedding_id TEXT,
                importance REAL DEFAULT 0.5
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                domain TEXT PRIMARY KEY,
                summary TEXT NOT NULL,
                last_updated REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_domain
            ON memories(domain)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_timestamp
            ON memories(timestamp)
        """)
        conn.commit()

    def add_memory(
        self,
        domain: str,
        content: str,
        importance: float = 0.5,
        embedding_id: Optional[str] = None,
    ) -> str:
        """Add a memory entry and update the domain summary."""
        memory_id = str(uuid.uuid4())
        timestamp = time.time()
        conn = self._get_connection()
        conn.execute(
            "INSERT INTO memories (id, domain, timestamp, content, embedding_id, importance) VALUES (?, ?, ?, ?, ?, ?)",
            (memory_id, domain, timestamp, content, embedding_id, importance),
        )
        conn.commit()
        self._update_summary(domain)
        return memory_id

    def get_memories_by_domain(
        self,
        domain: str,
        limit: int = 50,
        offset: int = 0,
        min_importance: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """Retrieve memories for a given domain, sorted by timestamp descending."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT id, domain, timestamp, content, embedding_id, importance "
            "FROM memories WHERE domain = ? AND importance >= ? "
            "ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (domain, min_importance, limit, offset),
        )
        results = []
        for row in cursor.fetchall():
            results.append({
                "id": row["id"],
                "domain": row["domain"],
                "timestamp": row["timestamp"],
                "content": row["content"],
                "embedding_id": row["embedding_id"],
                "importance": row["importance"],
            })
        return results

    def get_all_domains(self) -> List[str]:
        """Return all distinct domains."""
        conn = self._get_connection()
        cursor = conn.execute("SELECT DISTINCT domain FROM memories")
        return [row["domain"] for row in cursor.fetchall()]

    def get_summary(self, domain: str) -> Optional[str]:
        """Get the rolling summary for a domain."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT summary FROM summaries WHERE domain = ?", (domain,)
        )
        row = cursor.fetchone()
        return row["summary"] if row else None

    def _update_summary(self, domain: str) -> None:
        """Update the rolling summary for a domain by combining recent memories."""
        conn = self._get_connection()
        # Fetch the most recent 10 memories for summary generation
        cursor = conn.execute(
            "SELECT content FROM memories WHERE domain = ? ORDER BY timestamp DESC LIMIT 10",
            (domain,),
        )
        recent = [row["content"] for row in cursor.fetchall()]
        new_summary = " | ".join(recent)
        if len(new_summary) > 1000:
            new_summary = new_summary[:1000] + "..."
        timestamp = time.time()
        conn.execute(
            "INSERT OR REPLACE INTO summaries (domain, summary, last_updated) VALUES (?, ?, ?)",
            (domain, new_summary, timestamp),
        )
        conn.commit()

    def clear_domain(self, domain: str) -> int:
        """Delete all memories for a domain. Returns number of deleted rows."""
        conn = self._get_connection()
        cursor = conn.execute("DELETE FROM memories WHERE domain = ?", (domain,))
        deleted = cursor.rowcount
        conn.execute("DELETE FROM summaries WHERE domain = ?", (domain,))
        conn.commit()
        return deleted

    def close(self) -> None:
        """Close the database connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
