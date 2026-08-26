"""Automatic backup of .igris/ directory (#1330).

Provides scheduled backup of critical IGRIS data (memory, tasks, credentials)
to .igris/backups/ with retention policy, restore capability, and failure
notification via logging.

Usage:
    from igris.core.backup_manager import BackupManager

    mgr = BackupManager(project_root="/path/to/project")
    mgr.backup()           # create a backup
    mgr.list_backups()     # list available backups
    mgr.restore(backup_id) # restore from a backup
    mgr.cleanup()          # apply retention policy
"""
from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)

# Default retention: keep last 10 backups
DEFAULT_RETENTION = int(os.environ.get("IGRIS_BACKUP_RETENTION", "10"))

# Directories/files to exclude from backup (temporary, transient)
EXCLUDE_PATTERNS = {
    "__pycache__",
    ".tmp",
    "checkpoints",  # transient loop checkpoints (#1321)
    "backups",      # don't backup backups
    "*.lock",
    "*.log",
    "*.pid",
}


@dataclass
class BackupInfo:
    """Metadata for a single backup."""
    backup_id: str
    timestamp: float
    path: str
    size_bytes: int
    file_count: int
    status: str = "ok"  # ok, partial, failed
    error: str = ""


class BackupManager:
    """Manages automatic backups of the .igris/ directory.

    Backups are stored as timestamped directories under .igris/backups/.
    A retention policy automatically cleans up old backups.
    """

    def __init__(
        self,
        project_root: str,
        retention: int = DEFAULT_RETENTION,
        backup_dir: Optional[str] = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.igris_dir = self.project_root / ".igris"
        if backup_dir:
            self.backup_dir = Path(backup_dir)
        else:
            self.backup_dir = self.igris_dir / "backups"
        self.retention = retention

    def _should_exclude(self, path: Path) -> bool:
        """Check if a path should be excluded from backup."""
        name = path.name
        for pattern in EXCLUDE_PATTERNS:
            if pattern.startswith("*"):
                if name.endswith(pattern[1:]):
                    return True
            elif name == pattern:
                return True
        return False

    def _copy_tree(self, src: Path, dst: Path) -> tuple[int, int]:
        """Copy a directory tree, excluding unwanted files.

        Returns (file_count, total_size_bytes).
        """
        file_count = 0
        total_size = 0

        dst.mkdir(parents=True, exist_ok=True)

        for item in src.iterdir():
            if self._should_exclude(item):
                continue

            dst_item = dst / item.name

            if item.is_dir():
                # Skip if it's a __pycache__ or other excluded dir
                if item.name in EXCLUDE_PATTERNS:
                    continue
                # Don't backup the backups directory itself
                if item.resolve() == self.backup_dir.resolve():
                    continue
                fc, ts = self._copy_tree(item, dst_item)
                file_count += fc
                total_size += ts
            elif item.is_file():
                try:
                    shutil.copy2(str(item), str(dst_item))
                    file_count += 1
                    total_size += item.stat().st_size
                except (OSError, PermissionError) as exc:
                    _log.warning("backup: failed to copy %s: %s", item, exc)
            # Skip symlinks and special files

        return file_count, total_size

    def backup(self) -> BackupInfo:
        """Create a backup of the .igris/ directory.

        Returns BackupInfo with metadata about the backup.
        """
        if not self.igris_dir.exists():
            _log.warning("backup: .igris/ does not exist at %s", self.igris_dir)
            return BackupInfo(
                backup_id="",
                timestamp=time.time(),
                path="",
                size_bytes=0,
                file_count=0,
                status="failed",
                error=".igris/ does not exist",
            )

        backup_id = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        # Add milliseconds to avoid collisions when multiple backups happen in the same second
        backup_id += f"-{int((time.time() % 1) * 1000):03d}"
        backup_path = self.backup_dir / backup_id

        # Ensure backup directory exists
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        _log.info("backup: starting backup %s -> %s", self.igris_dir, backup_path)

        try:
            file_count, total_size = self._copy_tree(self.igris_dir, backup_path)

            # Write backup metadata
            meta_path = backup_path / "_backup_meta.json"
            import json
            meta = {
                "backup_id": backup_id,
                "timestamp": time.time(),
                "size_bytes": total_size,
                "file_count": file_count,
                "source": str(self.igris_dir),
            }
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

            _log.info(
                "backup: completed %s (%d files, %d bytes)",
                backup_id,
                file_count,
                total_size,
            )

            # Apply retention policy after successful backup
            self.cleanup()

            return BackupInfo(
                backup_id=backup_id,
                timestamp=time.time(),
                path=str(backup_path),
                size_bytes=total_size,
                file_count=file_count,
                status="ok",
            )
        except Exception as exc:
            _log.error("backup: failed %s: %s", backup_id, exc, exc_info=True)
            # Clean up partial backup
            if backup_path.exists():
                shutil.rmtree(backup_path, ignore_errors=True)
            return BackupInfo(
                backup_id=backup_id,
                timestamp=time.time(),
                path=str(backup_path),
                size_bytes=0,
                file_count=0,
                status="failed",
                error=str(exc),
            )

    def list_backups(self) -> List[BackupInfo]:
        """List all available backups, sorted by timestamp (newest first)."""
        if not self.backup_dir.exists():
            return []

        backups = []
        for item in sorted(self.backup_dir.iterdir(), reverse=True):
            if not item.is_dir():
                continue
            meta_path = item / "_backup_meta.json"
            if meta_path.exists():
                try:
                    import json
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    backups.append(BackupInfo(
                        backup_id=meta.get("backup_id", item.name),
                        timestamp=meta.get("timestamp", 0),
                        path=str(item),
                        size_bytes=meta.get("size_bytes", 0),
                        file_count=meta.get("file_count", 0),
                        status="ok",
                    ))
                except (json.JSONDecodeError, OSError):
                    continue
            else:
                # Legacy backup without metadata
                try:
                    size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                    count = sum(1 for f in item.rglob("*") if f.is_file())
                    backups.append(BackupInfo(
                        backup_id=item.name,
                        timestamp=item.stat().st_mtime,
                        path=str(item),
                        size_bytes=size,
                        file_count=count,
                        status="ok",
                    ))
                except OSError:
                    continue

        return backups

    def restore(self, backup_id: str) -> bool:
        """Restore .igris/ from a backup.

        Args:
            backup_id: The backup ID (timestamp string like "20260826-143000")

        Returns True if restore succeeded, False otherwise.
        """
        backup_path = self.backup_dir / backup_id
        if not backup_path.exists():
            _log.error("backup: restore failed — backup %s not found", backup_id)
            return False

        if not self.igris_dir.exists():
            self.igris_dir.mkdir(parents=True, exist_ok=True)

        _log.info("backup: restoring from %s -> %s", backup_path, self.igris_dir)

        try:
            # Copy backup contents back to .igris/
            for item in backup_path.iterdir():
                if item.name == "_backup_meta.json":
                    continue
                dst = self.igris_dir / item.name
                if item.is_dir():
                    if dst.exists():
                        shutil.rmtree(dst, ignore_errors=True)
                    shutil.copytree(str(item), str(dst), dirs_exist_ok=True)
                elif item.is_file():
                    shutil.copy2(str(item), str(dst))

            _log.info("backup: restore completed from %s", backup_id)
            return True
        except Exception as exc:
            _log.error("backup: restore failed: %s", exc, exc_info=True)
            return False

    def cleanup(self) -> int:
        """Apply retention policy — remove old backups beyond retention count.

        Returns the number of backups removed.
        """
        backups = self.list_backups()
        if len(backups) <= self.retention:
            return 0

        to_remove = backups[self.retention:]
        removed = 0
        for backup in to_remove:
            try:
                shutil.rmtree(backup.path, ignore_errors=True)
                removed += 1
                _log.info("backup: cleaned up old backup %s", backup.backup_id)
            except OSError as exc:
                _log.warning("backup: failed to remove %s: %s", backup.backup_id, exc)

        return removed

    def backup_status(self) -> Dict[str, Any]:
        """Return current backup status summary."""
        backups = self.list_backups()
        total_size = sum(b.size_bytes for b in backups)
        return {
            "total_backups": len(backups),
            "total_size_bytes": total_size,
            "retention": self.retention,
            "latest_backup": backups[0].backup_id if backups else None,
            "latest_timestamp": backups[0].timestamp if backups else None,
            "igris_dir_exists": self.igris_dir.exists(),
            "backup_dir": str(self.backup_dir),
        }
