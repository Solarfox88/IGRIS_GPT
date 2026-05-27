"""Tests for Issue #729 — .igris/ file rotation and size cap."""

from __future__ import annotations

import json
from pathlib import Path


class TestRotateIfNeeded:
    """igris.core.file_rotation.rotate_if_needed()"""

    def test_no_rotation_below_threshold(self, tmp_path):
        """Small files are not rotated."""
        from igris.core.file_rotation import rotate_if_needed
        p = tmp_path / ".igris" / "test.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("[]", encoding="utf-8")

        rotated = rotate_if_needed(p, max_mb=10.0)
        assert not rotated
        assert p.exists()

    def test_rotation_occurs_above_threshold(self, tmp_path):
        """Large files are rotated to archive directory."""
        from igris.core.file_rotation import rotate_if_needed
        p = tmp_path / ".igris" / "smw_knowledge_base.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        # Write a file exceeding threshold (simulate large file with repeated data)
        big_content = json.dumps([{"id": i, "data": "x" * 100} for i in range(200)])
        p.write_text(big_content, encoding="utf-8")

        size_mb = p.stat().st_size / (1024 * 1024)
        rotated = rotate_if_needed(p, max_mb=0.001)  # 1KB threshold
        assert rotated, f"Expected rotation for {size_mb:.3f} MB file"

    def test_rotated_file_is_archived(self, tmp_path):
        """Rotated file appears in .igris/archive/<timestamp>/ directory."""
        from igris.core.file_rotation import rotate_if_needed
        p = tmp_path / ".igris" / "smw_knowledge_base.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("[" + ",".join(['{"x": 1, "pad": "' + "a" * 50 + '"}'] * 200) + "]", encoding="utf-8")

        rotate_if_needed(p, max_mb=0.001)

        archive_dir = tmp_path / ".igris" / "archive"
        assert archive_dir.exists(), "archive/ directory must be created"
        snapshots = list(archive_dir.iterdir())
        assert len(snapshots) >= 1
        archived = snapshots[0] / "smw_knowledge_base.json"
        assert archived.exists(), f"Archived file missing: {archived}"

    def test_original_file_replaced_with_scaffold(self, tmp_path):
        """After rotation the original file is replaced with an empty scaffold."""
        from igris.core.file_rotation import rotate_if_needed
        p = tmp_path / ".igris" / "smw_knowledge_base.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("[" + ",".join(['{"x": 1, "pad": "' + "a" * 50 + '"}'] * 200) + "]", encoding="utf-8")

        rotate_if_needed(p, max_mb=0.001)

        assert p.exists(), "Original file must still exist after rotation"
        content = p.read_text(encoding="utf-8")
        data = json.loads(content)
        assert data == [], f"Scaffold must be empty list, got: {data}"

    def test_prune_keeps_only_recent_archives(self, tmp_path):
        """Old archives beyond *keep* are deleted."""
        from igris.core.file_rotation import rotate_if_needed
        p = tmp_path / ".igris" / "smw_knowledge_base.json"
        p.parent.mkdir(parents=True, exist_ok=True)

        # Create 5 rotations with keep=3 — should leave only 3
        for i in range(5):
            p.write_text("[" + ",".join(['{"x": 1, "pad": "' + "a" * 50 + '"}'] * 200) + "]", encoding="utf-8")
            import time
            time.sleep(0.01)  # ensure different timestamps
            rotate_if_needed(p, max_mb=0.001, keep=3)

        archive_dir = tmp_path / ".igris" / "archive"
        snapshots = [d for d in archive_dir.iterdir() if d.is_dir() and (d / p.name).exists()]
        assert len(snapshots) <= 3, f"Expected <= 3 archives, got {len(snapshots)}"

    def test_nonexistent_file_returns_false(self, tmp_path):
        """rotate_if_needed returns False for non-existent files."""
        from igris.core.file_rotation import rotate_if_needed
        result = rotate_if_needed(tmp_path / ".igris" / "missing.json")
        assert result is False


class TestGetFileStats:
    """igris.core.file_rotation.get_file_stats()"""

    def test_returns_list_with_file_info(self, tmp_path):
        """get_file_stats returns name, size_mb, and archive_snapshots."""
        from igris.core.file_rotation import get_file_stats
        igris_dir = tmp_path / ".igris"
        igris_dir.mkdir()
        (igris_dir / "test.json").write_text("[]", encoding="utf-8")

        stats = get_file_stats(igris_dir)
        assert isinstance(stats, list)
        assert len(stats) >= 1
        entry = next((s for s in stats if s["file"] == "test.json"), None)
        assert entry is not None
        assert "size_mb" in entry
        assert "archive_snapshots" in entry

    def test_empty_igris_dir_returns_empty_list(self, tmp_path):
        """Empty .igris directory returns empty stats."""
        from igris.core.file_rotation import get_file_stats
        igris_dir = tmp_path / ".igris"
        igris_dir.mkdir()
        stats = get_file_stats(igris_dir)
        assert stats == []


class TestStorageStatsEndpoint:
    """GET /api/storage/stats endpoint."""

    def test_storage_stats_endpoint_returns_200(self, tmp_path):
        """GET /api/storage/stats returns 200 with files list."""
        import os
        from unittest.mock import patch
        from igris.web.server import create_app, CONFIG
        CONFIG.project_root = tmp_path
        (tmp_path / ".igris").mkdir(exist_ok=True)
        with patch.dict(os.environ, {"IGRIS_API_KEY": ""}, clear=False):
            app = create_app()
        from starlette.testclient import TestClient
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/storage/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "files" in data
        assert isinstance(data["files"], list)
