"""Inventory Catalog — local descriptive catalog of known items/projects/environments (#1251).

SAFE BY DEFAULT:
- Purely descriptive; never executes actions or makes external calls
- All output boundaries apply recursive secret redaction
- ok=True only if real disk persistence succeeds
- No silent except — every failure is logged and returned as error/warning
- No runtime secrets stored raw
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Secret redaction ─────────────────────────────────────────────────────────

_SECRET_RE = re.compile(
    r'(token|passphrase|password|secret|api[_\s]?key|private[_\s]?key|bearer|auth[_\s]?key)'
    r'\s*[=:]\s*\S+',
    re.IGNORECASE,
)


def _redact(text: str) -> str:
    return _SECRET_RE.sub(r'\1=<REDACTED>', str(text)) if text else text


def _redact_any(val: Any) -> Any:
    if isinstance(val, dict):
        return {k: _redact_any(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [_redact_any(i) for i in val]
    elif isinstance(val, str):
        return _redact(val)
    return val


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class InventoryItem:
    item_id: str
    item_type: str
    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    priority: int = 50
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return _redact_any({
            "item_id": self.item_id,
            "item_type": self.item_type,
            "name": self.name,
            "description": self.description,
            "tags": list(self.tags),
            "priority": self.priority,
            "enabled": self.enabled,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })

    @classmethod
    def from_dict(cls, d: dict) -> "InventoryItem":
        return cls(
            item_id=d.get("item_id", ""),
            item_type=d.get("item_type", ""),
            name=d.get("name", ""),
            description=d.get("description", ""),
            tags=list(d.get("tags") or []),
            priority=int(d.get("priority", 50)),
            enabled=bool(d.get("enabled", True)),
            metadata=dict(d.get("metadata") or {}),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )


@dataclass
class InventoryOperationResult:
    ok: bool
    action: str
    item_id: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return _redact_any({
            "ok": self.ok,
            "action": self.action,
            "item_id": self.item_id,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "metadata": dict(self.metadata),
        })


# ── InventoryCatalog ──────────────────────────────────────────────────────────

_CATALOG_VERSION = 1
_DEFAULT_STORAGE_REL = Path(".igris") / "catalog" / "inventory_catalog.json"


class InventoryCatalog:
    """Local descriptive catalog for Jarvis Core.

    Purely read-oriented: stores item metadata, never executes operations.
    Thread-safety: not guaranteed — use one instance per task/request in concurrent contexts.
    """

    def __init__(
        self,
        project_root: str | Path | None = None,
        storage_path: str | Path | None = None,
    ) -> None:
        self.project_root = Path(project_root) if project_root else Path.cwd()
        if storage_path:
            self.storage_path = Path(storage_path)
        else:
            self.storage_path = self.project_root / _DEFAULT_STORAGE_REL

        self._items: dict[str, InventoryItem] = {}
        self._load_warnings: list[str] = []

        # Auto-load if file exists; ignore gracefully if missing
        if self.storage_path.exists():
            result = self.reload()
            if not result.ok:
                logger.warning(
                    "InventoryCatalog: failed to load %s: %s",
                    self.storage_path,
                    result.errors,
                )

    # ── Persistence ──────────────────────────────────────────────────────────

    def save(self) -> InventoryOperationResult:
        """Persist current state to disk. ok=True only if write succeeds."""
        result = InventoryOperationResult(ok=False, action="save")
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": _CATALOG_VERSION,
                "items": [item.to_dict() for item in self._items.values()],
            }
            raw = json.dumps(payload, indent=2, ensure_ascii=False)
            self.storage_path.write_text(raw, encoding="utf-8")
            result.ok = True
            result.metadata["saved_count"] = len(self._items)
        except Exception as exc:
            msg = f"save failed: {exc}"
            result.errors.append(msg)
            logger.warning("InventoryCatalog.save: %s", msg)
        return result

    def reload(self) -> InventoryOperationResult:
        """Reload items from disk. Handles missing/invalid/corrupt files gracefully."""
        result = InventoryOperationResult(ok=False, action="reload")
        self._load_warnings = []

        if not self.storage_path.exists():
            result.ok = True  # empty catalog is valid
            result.warnings.append("storage_file_missing")
            self._items = {}
            return result

        try:
            raw = self.storage_path.read_text(encoding="utf-8")
        except Exception as exc:
            msg = f"read failed: {exc}"
            result.errors.append(msg)
            logger.warning("InventoryCatalog.reload: %s", msg)
            return result

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            msg = f"invalid json: {exc}"
            result.errors.append(msg)
            logger.warning("InventoryCatalog.reload: %s", msg)
            return result

        if not isinstance(data, dict):
            msg = "storage root is not a dict"
            result.errors.append(msg)
            logger.warning("InventoryCatalog.reload: %s", msg)
            return result

        items_raw = data.get("items")
        if not isinstance(items_raw, list):
            msg = "items field is not a list"
            result.errors.append(msg)
            result.warnings.append("items_not_list")
            self._items = {}
            # Partial success — catalog cleared
            return result

        loaded: dict[str, InventoryItem] = {}
        skipped = 0
        for raw_item in items_raw:
            if not isinstance(raw_item, dict):
                skipped += 1
                continue
            item_id = raw_item.get("item_id", "").strip()
            name = raw_item.get("name", "").strip()
            item_type = raw_item.get("item_type", "").strip()
            if not item_id or not name:
                skipped += 1
                continue
            try:
                loaded[item_id] = InventoryItem.from_dict(raw_item)
            except Exception as exc:
                skipped += 1
                logger.debug("InventoryCatalog.reload: skip item %s: %s", item_id, exc)

        self._items = loaded
        result.ok = True
        result.metadata["loaded_count"] = len(loaded)
        if skipped:
            result.warnings.append(f"skipped_{skipped}_invalid_items")
        return result

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def create_item(self, item: InventoryItem) -> InventoryOperationResult:
        """Add a new item to the catalog and persist to disk."""
        result = InventoryOperationResult(ok=False, action="create", item_id=item.item_id)

        if not item.item_id or not item.item_id.strip():
            result.errors.append("item_id_required")
            return result
        if not item.name or not item.name.strip():
            result.errors.append("name_required")
            return result
        if item.item_id in self._items:
            result.errors.append(f"duplicate_item_id:{item.item_id}")
            return result

        now = _now_iso()
        if not item.created_at:
            item.created_at = now
        if not item.updated_at:
            item.updated_at = now

        self._items[item.item_id] = item
        save_r = self.save()
        if not save_r.ok:
            # Rollback in-memory
            del self._items[item.item_id]
            result.errors.extend(save_r.errors)
            result.errors.append("persist_failed_rollback")
            return result

        result.ok = True
        return result

    def get_item(self, item_id: str) -> InventoryItem | None:
        """Return item by id or None if not found."""
        return self._items.get(item_id)

    def list_items(
        self,
        *,
        item_type: str | None = None,
        tag: str | None = None,
        enabled_only: bool = True,
    ) -> list[InventoryItem]:
        """Return items matching filters, sorted by priority descending then name."""
        items = list(self._items.values())
        if enabled_only:
            items = [i for i in items if i.enabled]
        if item_type is not None:
            items = [i for i in items if i.item_type == item_type]
        if tag is not None:
            items = [i for i in items if tag in i.tags]
        items.sort(key=lambda i: (-i.priority, i.name.lower()))
        return items

    def update_item(self, item_id: str, /, **updates: Any) -> InventoryOperationResult:
        """Update allowed fields of an existing item and persist."""
        result = InventoryOperationResult(ok=False, action="update", item_id=item_id)

        item = self._items.get(item_id)
        if item is None:
            result.errors.append(f"item_not_found:{item_id}")
            return result

        # Disallow changing item_id
        if "item_id" in updates:
            result.warnings.append("item_id_change_ignored")
            del updates["item_id"]

        _ALLOWED = {"item_type", "name", "description", "tags", "priority", "enabled", "metadata"}
        for k, v in updates.items():
            if k not in _ALLOWED:
                result.warnings.append(f"unknown_field_ignored:{k}")
                continue
            setattr(item, k, v)

        item.updated_at = _now_iso()

        save_r = self.save()
        if not save_r.ok:
            result.errors.extend(save_r.errors)
            result.errors.append("persist_failed")
            return result

        result.ok = True
        return result

    def disable_item(self, item_id: str) -> InventoryOperationResult:
        """Set enabled=False for an item and persist."""
        result = InventoryOperationResult(ok=False, action="disable", item_id=item_id)

        item = self._items.get(item_id)
        if item is None:
            result.errors.append(f"item_not_found:{item_id}")
            return result

        item.enabled = False
        item.updated_at = _now_iso()

        save_r = self.save()
        if not save_r.ok:
            result.errors.extend(save_r.errors)
            result.errors.append("persist_failed")
            return result

        result.ok = True
        return result

    def delete_item(self, item_id: str) -> InventoryOperationResult:
        """Remove an item from the catalog (local only) and persist."""
        result = InventoryOperationResult(ok=False, action="delete", item_id=item_id)

        if item_id not in self._items:
            result.errors.append(f"item_not_found:{item_id}")
            return result

        removed = self._items.pop(item_id)
        save_r = self.save()
        if not save_r.ok:
            # Restore
            self._items[item_id] = removed
            result.errors.extend(save_r.errors)
            result.errors.append("persist_failed_rollback")
            return result

        result.ok = True
        return result

    # ── Export / healthcheck ─────────────────────────────────────────────────

    def export_safe(self) -> dict:
        """Return a redacted summary of the catalog. No raw secrets."""
        items = list(self._items.values())
        enabled_count = sum(1 for i in items if i.enabled)
        return _redact_any({
            "version": _CATALOG_VERSION,
            "count": len(items),
            "enabled_count": enabled_count,
            "items": [i.to_dict() for i in items],
        })

    def healthcheck(self) -> dict:
        """Return catalog health status. No raw secrets."""
        items = list(self._items.values())
        enabled_count = sum(1 for i in items if i.enabled)
        warnings = list(self._load_warnings)
        errors: list[str] = []
        storage_exists = self.storage_path.exists()
        return _redact_any({
            "ok": True,
            "storage_path": str(self.storage_path),
            "exists": storage_exists,
            "count": len(items),
            "enabled_count": enabled_count,
            "warnings": warnings,
            "errors": errors,
        })
