"""Tests for SQLite schema migration system (#1319)."""
import sqlite3
from pathlib import Path

import pytest

from igris.core.schema_manager import SchemaManager, MIGRATIONS


class TestSchemaManager:
    """Unit tests for SchemaManager."""

    def test_fresh_database_migrates_to_latest(self, tmp_path: Path) -> None:
        """A fresh database should migrate from 0 to latest version."""
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        mgr = SchemaManager(conn, MIGRATIONS["memory_graph"], component="memory_graph")
        version = mgr.migrate_to_latest()
        assert version == mgr.latest_version()
        assert version >= 1
        row = conn.execute("SELECT version FROM schema_version WHERE component='memory_graph'").fetchone()
        assert row is not None
        assert row[0] == version
        conn.close()

    def test_existing_database_migrates_without_data_loss(self, tmp_path: Path) -> None:
        """An existing database with data should preserve data through migration."""
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        conn.executescript(MIGRATIONS["memory_graph"][1])
        conn.execute(
            "INSERT INTO memory_nodes (node_id, node_type, content, confidence, success_rate, created_at, updated_at, tags) "
            "VALUES ('n1', 'test', 'hello', 1.0, 1.0, 1.0, 1.0, '[]')"
        )
        conn.commit()

        mgr = SchemaManager(conn, MIGRATIONS["memory_graph"], component="memory_graph")
        version = mgr.migrate_to_latest()
        assert version >= 1

        row = conn.execute("SELECT node_id, content FROM memory_nodes WHERE node_id='n1'").fetchone()
        assert row is not None
        assert row[0] == "n1"
        assert row[1] == "hello"
        conn.close()

    def test_idempotent_migration(self, tmp_path: Path) -> None:
        """Running migration twice should be a no-op the second time."""
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        mgr = SchemaManager(conn, MIGRATIONS["memory_graph"], component="memory_graph")
        v1 = mgr.migrate_to_latest()
        v2 = mgr.migrate_to_latest()
        assert v1 == v2
        conn.close()

    def test_current_version_starts_at_zero(self, tmp_path: Path) -> None:
        """A fresh database should report version 0 before any migration."""
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        mgr = SchemaManager(conn, MIGRATIONS["memory_graph"], component="memory_graph")
        assert mgr.current_version() == 0
        conn.close()

    def test_validate_returns_true_after_migration(self, tmp_path: Path) -> None:
        """validate() should return True after migrating to latest."""
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        mgr = SchemaManager(conn, MIGRATIONS["memory_graph"], component="memory_graph")
        mgr.migrate_to_latest()
        assert mgr.validate() is True
        conn.close()

    def test_validate_returns_false_before_migration(self, tmp_path: Path) -> None:
        """validate() should return False before any migration."""
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        mgr = SchemaManager(conn, MIGRATIONS["memory_graph"], component="memory_graph")
        assert mgr.validate() is False
        conn.close()

    def test_migration_with_multiple_versions(self, tmp_path: Path) -> None:
        """Migrations with multiple versions should apply in order."""
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        migrations = {
            1: "CREATE TABLE IF NOT EXISTS t1 (id INTEGER PRIMARY KEY);",
            2: "CREATE TABLE IF NOT EXISTS t2 (id INTEGER PRIMARY KEY);",
            3: "CREATE TABLE IF NOT EXISTS t3 (id INTEGER PRIMARY KEY);",
        }
        mgr = SchemaManager(conn, migrations, component="test_multi")
        version = mgr.migrate_to_latest()
        assert version == 3
        conn.execute("SELECT * FROM t1")
        conn.execute("SELECT * FROM t2")
        conn.execute("SELECT * FROM t3")
        conn.close()

    def test_migration_failure_rolls_back(self, tmp_path: Path) -> None:
        """A failed migration should roll back and not advance the version."""
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        migrations = {
            1: "CREATE TABLE IF NOT EXISTS good (id INTEGER PRIMARY KEY);",
            2: "INVALID SQL STATEMENT HERE;",
        }
        mgr = SchemaManager(conn, migrations, component="test_fail")
        v1 = mgr.migrate_to(1)
        assert v1 == 1
        with pytest.raises(Exception):
            mgr.migrate_to(2)
        assert mgr.current_version() == 1
        conn.close()

    def test_partial_migration_to_specific_version(self, tmp_path: Path) -> None:
        """migrate_to should stop at the specified version."""
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        migrations = {
            1: "CREATE TABLE IF NOT EXISTS t1 (id INTEGER PRIMARY KEY);",
            2: "CREATE TABLE IF NOT EXISTS t2 (id INTEGER PRIMARY KEY);",
            3: "CREATE TABLE IF NOT EXISTS t3 (id INTEGER PRIMARY KEY);",
        }
        mgr = SchemaManager(conn, migrations, component="test_partial")
        v = mgr.migrate_to(2)
        assert v == 2
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("SELECT * FROM t3")
        conn.close()

    def test_all_registered_migrations_are_valid_sql(self) -> None:
        """All migration scripts in the registry should be valid SQL."""
        for component, versions in MIGRATIONS.items():
            for version, sql in versions.items():
                conn = sqlite3.connect(":memory:")
                try:
                    conn.executescript(sql)
                    conn.commit()
                except sqlite3.Error as e:
                    pytest.fail(f"Migration {component} v{version} has invalid SQL: {e}")
                conn.close()


class TestMemoryGraphMigration:
    """Integration tests for MemoryGraph using SchemaManager."""

    def test_memory_graph_creates_schema_version_table(self, tmp_path: Path) -> None:
        """MemoryGraph should create a schema_version table on init."""
        from igris.core.memory_graph import MemoryGraph

        mg = MemoryGraph(project_root=str(tmp_path))
        row = mg.conn.execute(
            "SELECT version FROM schema_version WHERE component='memory_graph'"
        ).fetchone()
        assert row is not None
        assert row[0] >= 1

    def test_memory_graph_preserves_data_on_reinit(self, tmp_path: Path) -> None:
        """Re-opening a MemoryGraph should preserve existing nodes."""
        from igris.core.memory_graph import MemoryGraph

        mg1 = MemoryGraph(project_root=str(tmp_path))
        node_id = mg1.add_node("project_fact", {"text": "hello world"}, tags=["t1"])
        mg1.conn.commit()

        mg2 = MemoryGraph(project_root=str(tmp_path))
        node = mg2.get_node(node_id)
        assert node is not None
        assert "hello world" in str(node["content"])
