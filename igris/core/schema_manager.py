"""SQLite schema versioning and migration system (#1319).

Provides a lightweight migration framework for SQLite databases used by
IGRIS components (MemoryGraph, EmbeddingStore, MemoryScorer, etc.).

Usage:
    from igris.core.schema_manager import SchemaManager, MIGRATIONS

    mgr = SchemaManager(conn, migrations=MIGRATIONS["memory_graph"])
    mgr.migrate_to_latest()

Each migration is a dict mapping version -> SQL script. The schema_version
table tracks the highest applied version. Migrations run in a transaction
and are logged.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Dict

_log = logging.getLogger(__name__)

# Migration registries per database/component.
# Version 1 is always the initial schema (CREATE TABLE IF NOT EXISTS).
# Future schema changes add versioned ALTER/CREATE scripts.

MIGRATIONS: Dict[str, Dict[int, str]] = {
    "memory_graph": {
        1: """
CREATE TABLE IF NOT EXISTS memory_nodes (
    node_id     TEXT PRIMARY KEY,
    node_type   TEXT NOT NULL,
    content     TEXT NOT NULL,
    confidence  REAL NOT NULL DEFAULT 1.0,
    success_rate REAL NOT NULL DEFAULT 1.0,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    tags        TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS memory_edges (
    edge_id     TEXT PRIMARY KEY,
    src_node    TEXT NOT NULL REFERENCES memory_nodes(node_id),
    dst_node    TEXT NOT NULL REFERENCES memory_nodes(node_id),
    edge_type   TEXT NOT NULL,
    weight      REAL NOT NULL DEFAULT 1.0,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON memory_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_edges_src  ON memory_edges(src_node);
CREATE INDEX IF NOT EXISTS idx_edges_dst  ON memory_edges(dst_node);
""",
    },
    "embedding_store": {
        1: """
CREATE TABLE IF NOT EXISTS embeddings (
    node_id     TEXT PRIMARY KEY,
    node_type   TEXT NOT NULL,
    text_content TEXT NOT NULL,
    vector      BLOB NOT NULL,
    created_at  REAL NOT NULL
);
""",
    },
    "memory_scorer": {
        1: """
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
""",
    },
    "memory_topic_tree": {
        1: """
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
""",
    },
}


class SchemaManager:
    """Manages SQLite schema versioning and migrations.

    Creates a ``schema_version`` table to track applied migrations,
    then runs any pending migrations in order.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        migrations: Dict[int, str],
        component: str = "default",
    ) -> None:
        self.conn = conn
        self.migrations = migrations
        self.component = component

    def _ensure_version_table(self) -> None:
        """Create the schema_version table if it doesn't exist."""
        self.conn.execute(
            """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    component   TEXT NOT NULL DEFAULT 'default',
    applied_at  REAL NOT NULL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (version, component)
)
"""
        )
        self.conn.commit()

    def current_version(self) -> int:
        """Return the highest applied migration version, or 0 if none."""
        self._ensure_version_table()
        row = self.conn.execute(
            "SELECT MAX(version) FROM schema_version WHERE component = ?",
            (self.component,),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def latest_version(self) -> int:
        """Return the latest available migration version."""
        return max(self.migrations.keys()) if self.migrations else 0

    def migrate_to_latest(self) -> int:
        """Run all pending migrations up to the latest version.

        Returns the version reached after migration.
        """
        return self.migrate_to(self.latest_version())

    def migrate_to(self, target: int) -> int:
        """Run migrations from current+1 up to target (inclusive).

        Each migration runs in a transaction. On success, the version is
        recorded in schema_version. On failure, the transaction is rolled
        back and the error is re-raised.

        Returns the version reached after migration.
        """
        current = self.current_version()
        if current >= target:
            _log.debug(
                "schema_manager[%s]: already at version %d (target %d)",
                self.component,
                current,
                target,
            )
            return current

        for v in range(current + 1, target + 1):
            script = self.migrations.get(v)
            if script is None:
                _log.warning(
                    "schema_manager[%s]: migration %d not found, skipping",
                    self.component,
                    v,
                )
                continue

            _log.info(
                "schema_manager[%s]: applying migration %d -> %d",
                self.component,
                current,
                v,
            )

            try:
                # executescript implicitly commits any pending transaction,
                # so we run the script first, then record the version.
                self.conn.executescript(script)
                self.conn.execute(
                    "INSERT INTO schema_version (version, component) VALUES (?, ?)",
                    (v, self.component),
                )
                self.conn.commit()
                _log.info(
                    "schema_manager[%s]: migration %d applied successfully",
                    self.component,
                    v,
                )
                current = v
            except Exception:
                self.conn.rollback()
                _log.error(
                    "schema_manager[%s]: migration %d failed, rolled back",
                    self.component,
                    v,
                    exc_info=True,
                )
                raise

        return current

    def validate(self) -> bool:
        """Check that the current version matches the latest available.

        Returns True if the schema is up-to-date, False otherwise.
        """
        return self.current_version() >= self.latest_version()
