"""Tests for backup manager (#1330)."""
import json
import time
from pathlib import Path

import pytest

from igris.core.backup_manager import BackupManager, BackupInfo


class TestBackupManager:
    """Unit tests for BackupManager."""

    def test_backup_creates_backup_directory(self, tmp_path: Path) -> None:
        """backup() should create a backup directory with .igris contents."""
        igris = tmp_path / ".igris"
        igris.mkdir(parents=True)
        (igris / "memory").mkdir()
        (igris / "memory" / "test.db").write_text("test data")
        (igris / "tasks").mkdir()
        (igris / "tasks" / "task1.json").write_text('{"id": 1}')

        mgr = BackupManager(str(tmp_path), retention=5)
        info = mgr.backup()

        assert info.status == "ok"
        assert info.file_count >= 2
        assert info.size_bytes > 0
        assert Path(info.path).exists()
        # Verify backup contains the files
        assert (Path(info.path) / "memory" / "test.db").exists()
        assert (Path(info.path) / "tasks" / "task1.json").exists()

    def test_backup_returns_failed_when_no_igris(self, tmp_path: Path) -> None:
        """backup() should return failed status when .igris/ doesn't exist."""
        mgr = BackupManager(str(tmp_path))
        info = mgr.backup()
        assert info.status == "failed"
        assert ".igris/ does not exist" in info.error

    def test_list_backups_empty(self, tmp_path: Path) -> None:
        """list_backups() should return empty list when no backups exist."""
        mgr = BackupManager(str(tmp_path))
        assert mgr.list_backups() == []

    def test_list_backups_returns_sorted(self, tmp_path: Path) -> None:
        """list_backups() should return backups sorted newest first."""
        igris = tmp_path / ".igris"
        igris.mkdir(parents=True)
        (igris / "test.txt").write_text("data")

        mgr = BackupManager(str(tmp_path), retention=10)
        info1 = mgr.backup()
        time.sleep(0.1)
        info2 = mgr.backup()

        backups = mgr.list_backups()
        assert len(backups) == 2
        # Newest first
        assert backups[0].backup_id == info2.backup_id
        assert backups[1].backup_id == info1.backup_id

    def test_restore_restores_files(self, tmp_path: Path) -> None:
        """restore() should restore files from a backup."""
        igris = tmp_path / ".igris"
        igris.mkdir(parents=True)
        (igris / "memory").mkdir()
        (igris / "memory" / "graph.db").write_text("graph data")

        mgr = BackupManager(str(tmp_path), retention=5)
        info = mgr.backup()

        # Delete original files
        (igris / "memory" / "graph.db").unlink()

        # Restore
        result = mgr.restore(info.backup_id)
        assert result is True
        assert (igris / "memory" / "graph.db").exists()
        assert (igris / "memory" / "graph.db").read_text() == "graph data"

    def test_restore_returns_false_for_missing_backup(self, tmp_path: Path) -> None:
        """restore() should return False for a non-existent backup."""
        mgr = BackupManager(str(tmp_path))
        assert mgr.restore("nonexistent") is False

    def test_cleanup_removes_old_backups(self, tmp_path: Path) -> None:
        """cleanup() should remove backups beyond retention count."""
        igris = tmp_path / ".igris"
        igris.mkdir(parents=True)
        (igris / "test.txt").write_text("data")

        mgr = BackupManager(str(tmp_path), retention=3)
        for _ in range(5):
            mgr.backup()
            time.sleep(0.05)

        backups = mgr.list_backups()
        assert len(backups) == 3  # retention=3

    def test_backup_excludes_pycache_and_logs(self, tmp_path: Path) -> None:
        """backup() should exclude __pycache__, .log, .lock files."""
        igris = tmp_path / ".igris"
        igris.mkdir(parents=True)
        (igris / "data.json").write_text('{"key": "value"}')
        (igris / "debug.log").write_text("log entry")
        (igris / "app.lock").write_text("locked")
        pycache = igris / "__pycache__"
        pycache.mkdir()
        (pycache / "module.cpython-312.pyc").write_text("bytecode")

        mgr = BackupManager(str(tmp_path), retention=5)
        info = mgr.backup()

        backup_path = Path(info.path)
        assert (backup_path / "data.json").exists()
        assert not (backup_path / "debug.log").exists()
        assert not (backup_path / "app.lock").exists()
        assert not (backup_path / "__pycache__").exists()

    def test_backup_excludes_checkpoints_and_backups(self, tmp_path: Path) -> None:
        """backup() should exclude checkpoints/ and backups/ directories."""
        igris = tmp_path / ".igris"
        igris.mkdir(parents=True)
        (igris / "memory").mkdir()
        (igris / "memory" / "graph.db").write_text("data")
        (igris / "checkpoints").mkdir()
        (igris / "checkpoints" / "loop_m1.json").write_text("{}")

        mgr = BackupManager(str(tmp_path), retention=5)
        info = mgr.backup()

        backup_path = Path(info.path)
        assert (backup_path / "memory" / "graph.db").exists()
        assert not (backup_path / "checkpoints").exists()
        # backups/ dir should not contain itself
        assert not (backup_path / "backups").exists()

    def test_backup_metadata_written(self, tmp_path: Path) -> None:
        """backup() should write _backup_meta.json with metadata."""
        igris = tmp_path / ".igris"
        igris.mkdir(parents=True)
        (igris / "test.txt").write_text("data")

        mgr = BackupManager(str(tmp_path), retention=5)
        info = mgr.backup()

        meta_path = Path(info.path) / "_backup_meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["backup_id"] == info.backup_id
        assert meta["file_count"] == info.file_count
        assert meta["size_bytes"] == info.size_bytes

    def test_backup_status_returns_summary(self, tmp_path: Path) -> None:
        """backup_status() should return a summary dict."""
        igris = tmp_path / ".igris"
        igris.mkdir(parents=True)
        (igris / "test.txt").write_text("data")

        mgr = BackupManager(str(tmp_path), retention=5)
        mgr.backup()

        status = mgr.backup_status()
        assert status["total_backups"] == 1
        assert status["retention"] == 5
        assert status["latest_backup"] is not None
        assert status["igris_dir_exists"] is True

    def test_backup_preserves_database_integrity(self, tmp_path: Path) -> None:
        """backup() should preserve SQLite database integrity."""
        import sqlite3

        igris = tmp_path / ".igris"
        igris.mkdir(parents=True)
        db_path = igris / "memory" / "graph.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, data TEXT)")
        conn.execute("INSERT INTO nodes VALUES ('n1', 'test data')")
        conn.commit()
        conn.close()

        mgr = BackupManager(str(tmp_path), retention=5)
        info = mgr.backup()

        # Verify backup database is readable
        backup_db = Path(info.path) / "memory" / "graph.db"
        conn2 = sqlite3.connect(str(backup_db))
        row = conn2.execute("SELECT id, data FROM nodes WHERE id='n1'").fetchone()
        assert row is not None
        assert row[0] == "n1"
        assert row[1] == "test data"
        conn2.close()

    def test_multiple_backups_no_interference(self, tmp_path: Path) -> None:
        """Multiple backups should not interfere with each other."""
        igris = tmp_path / ".igris"
        igris.mkdir(parents=True)
        (igris / "v1.txt").write_text("version 1")

        mgr = BackupManager(str(tmp_path), retention=10)
        info1 = mgr.backup()

        # Change data
        (igris / "v1.txt").write_text("version 2")
        time.sleep(0.1)
        info2 = mgr.backup()

        # First backup should still have version 1
        assert (Path(info1.path) / "v1.txt").read_text() == "version 1"
        # Second backup should have version 2
        assert (Path(info2.path) / "v1.txt").read_text() == "version 2"
