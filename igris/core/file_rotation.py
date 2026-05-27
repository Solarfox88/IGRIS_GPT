"""Issue #729 — .igris/ file rotation and size cap.

Provides ``rotate_if_needed(path)`` which rotates a JSON file to an
archive directory when it exceeds the configured size cap.

Usage
-----
from igris.core.file_rotation import rotate_if_needed
rotate_if_needed(Path(project_root) / ".igris" / "smw_knowledge_base.json")

Environment variables
---------------------
IGRIS_MAX_FILE_MB       Max file size in MB before rotation.  Default: 5.
IGRIS_ARCHIVE_KEEP      Number of archive snapshots to keep per file.  Default: 7.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path

_logger = logging.getLogger("igris.file_rotation")

_DEFAULT_MAX_MB: float = float(os.getenv("IGRIS_MAX_FILE_MB", "5"))
_DEFAULT_KEEP: int = int(os.getenv("IGRIS_ARCHIVE_KEEP", "7"))


def rotate_if_needed(
    path: Path,
    max_mb: float = _DEFAULT_MAX_MB,
    keep: int = _DEFAULT_KEEP,
) -> bool:
    """Rotate *path* to archive if it exceeds *max_mb* megabytes.

    Returns True if rotation occurred, False otherwise.

    Archive layout::

        .igris/archive/<YYYY-MM-DD_HHMMSS>/<filename>

    Old archives beyond *keep* are pruned automatically.
    """
    if not path.exists():
        return False

    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb < max_mb:
        return False

    archive_dir = path.parent / "archive"
    timestamp = time.strftime("%Y-%m-%d_%H%M%S", time.gmtime())
    dest_dir = archive_dir / timestamp
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / path.name
        shutil.copy2(str(path), str(dest))
        # Truncate (replace with empty scaffold) rather than delete so the
        # file always exists for readers.
        _write_empty_scaffold(path)
        _logger.warning(
            "File rotation: %s (%.1f MB) archived to %s",
            path.name, size_mb, dest,
        )
    except OSError as exc:
        _logger.warning("File rotation failed for %s: %s", path, exc)
        return False

    # Prune old archives (keep the most recent *keep* snapshots)
    _prune_archives(archive_dir, path.name, keep)
    return True


def _write_empty_scaffold(path: Path) -> None:
    """Write a minimal valid JSON scaffold after rotation."""
    import json
    # Detect the structure from the first character of the existing content
    # (array vs object) — fall back to empty array.
    scaffolds: dict = {
        "supervisor_runs.json": '{"runs": {}}',
        "smw_knowledge_base.json": "[]",
        "rank_log.json": "[]",
        "failure_patterns.json": '{"patterns": [], "file_patterns": {}, "goal_patterns": {}}',
    }
    scaffold = scaffolds.get(path.name, "[]")
    try:
        tmp = path.with_suffix(".rot_tmp")
        tmp.write_text(scaffold, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        _logger.warning("Could not write scaffold after rotation: %s", exc)


def _prune_archives(archive_dir: Path, filename: str, keep: int) -> None:
    """Remove oldest archive snapshots beyond *keep* for *filename*."""
    if not archive_dir.exists():
        return
    snapshots = sorted(
        (d for d in archive_dir.iterdir() if d.is_dir() and (d / filename).exists()),
        key=lambda d: d.name,  # timestamp-based name → lexicographic = chronological
    )
    to_delete = snapshots[:-keep] if len(snapshots) > keep else []
    for old_dir in to_delete:
        try:
            shutil.rmtree(str(old_dir))
            _logger.info("Pruned old archive: %s", old_dir)
        except OSError:
            pass


def get_file_stats(igris_dir: Path) -> list:
    """Return a list of dicts with size info for all .igris/ JSON files."""
    stats = []
    for p in sorted(igris_dir.glob("*.json")):
        size_mb = p.stat().st_size / (1024 * 1024) if p.exists() else 0.0
        archive_dir = igris_dir / "archive"
        archive_count = 0
        if archive_dir.exists():
            archive_count = sum(
                1 for d in archive_dir.iterdir()
                if d.is_dir() and (d / p.name).exists()
            )
        stats.append({
            "file": p.name,
            "size_mb": round(size_mb, 3),
            "archive_snapshots": archive_count,
        })
    return stats
