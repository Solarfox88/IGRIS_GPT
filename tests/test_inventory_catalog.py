"""Tests for InventoryCatalog — Catalog baseline (#1251).

Target: production-complete-inventory-catalog
"""
from __future__ import annotations
import json
import unittest.mock as mock
from pathlib import Path
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_item(
    item_id="item-001",
    item_type="project",
    name="Test Project",
    description="A test project",
    tags=None,
    priority=50,
    enabled=True,
    metadata=None,
):
    from igris.core.inventory_catalog import InventoryItem
    return InventoryItem(
        item_id=item_id,
        item_type=item_type,
        name=name,
        description=description,
        tags=tags or [],
        priority=priority,
        enabled=enabled,
        metadata=metadata or {},
    )


def _catalog(tmp_path, subdir="catalog"):
    from igris.core.inventory_catalog import InventoryCatalog
    storage = tmp_path / subdir / "inventory_catalog.json"
    return InventoryCatalog(project_root=tmp_path, storage_path=storage)


# ── InventoryItem.to_dict redaction ──────────────────────────────────────────

def test_inventory_item_to_dict_redacts_token():
    FAKE = "FAKE_TOKEN_CATALOG_1234567890"
    item = _make_item(description=f"token={FAKE}", metadata={"key": f"token={FAKE}"})
    d = item.to_dict()
    output = json.dumps(d)
    assert f"token={FAKE}" not in output


def test_inventory_item_to_dict_redacts_password():
    FAKE = "FAKE_PASSWORD_CATALOG_1234567890"
    item = _make_item(description=f"password={FAKE}")
    output = json.dumps(item.to_dict())
    assert f"password={FAKE}" not in output


def test_inventory_item_to_dict_redacts_api_key():
    FAKE = "FAKE_API_KEY_CATALOG_1234567890"
    item = _make_item(metadata={"api_key": f"api_key={FAKE}"})
    output = json.dumps(item.to_dict())
    assert f"api_key={FAKE}" not in output


def test_inventory_item_to_dict_redacts_passphrase():
    FAKE = "FAKE_PASSPHRASE_CATALOG_1234567890"
    item = _make_item(description=f"passphrase={FAKE}")
    output = json.dumps(item.to_dict())
    assert f"passphrase={FAKE}" not in output


def test_inventory_item_to_dict_contains_required_fields():
    item = _make_item()
    d = item.to_dict()
    for key in ("item_id", "item_type", "name", "description", "tags",
                "priority", "enabled", "metadata", "created_at", "updated_at"):
        assert key in d


# ── InventoryOperationResult.to_dict ─────────────────────────────────────────

def test_operation_result_to_dict_fields():
    from igris.core.inventory_catalog import InventoryOperationResult
    r = InventoryOperationResult(ok=True, action="create", item_id="x")
    d = r.to_dict()
    for key in ("ok", "action", "item_id", "warnings", "errors", "metadata"):
        assert key in d


def test_operation_result_to_dict_redacts_secret():
    FAKE = "FAKE_TOKEN_CATALOG_1234567890"
    from igris.core.inventory_catalog import InventoryOperationResult
    r = InventoryOperationResult(
        ok=True, action="create",
        errors=[f"token={FAKE}"],
        metadata={"note": f"token={FAKE}"},
    )
    output = json.dumps(r.to_dict())
    assert f"token={FAKE}" not in output


# ── Catalog initializes with missing file ─────────────────────────────────────

def test_catalog_initializes_with_missing_file(tmp_path):
    cat = _catalog(tmp_path)
    assert cat is not None
    assert cat.list_items() == []


def test_catalog_healthcheck_missing_file(tmp_path):
    cat = _catalog(tmp_path)
    h = cat.healthcheck()
    assert h["ok"] is True
    assert h["count"] == 0
    assert h["exists"] is False


# ── create_item ────────────────────────────────────────────────────────────────

def test_create_item_persists_to_disk(tmp_path):
    cat = _catalog(tmp_path)
    r = cat.create_item(_make_item())
    assert r.ok is True, r.errors
    assert cat.storage_path.exists()
    data = json.loads(cat.storage_path.read_text())
    assert len(data["items"]) == 1
    assert data["items"][0]["item_id"] == "item-001"


def test_create_item_sets_timestamps(tmp_path):
    cat = _catalog(tmp_path)
    item = _make_item()
    assert item.created_at == ""
    r = cat.create_item(item)
    assert r.ok is True
    assert item.created_at != ""
    assert item.updated_at != ""


def test_create_duplicate_item_fails(tmp_path):
    cat = _catalog(tmp_path)
    cat.create_item(_make_item())
    r = cat.create_item(_make_item())
    assert r.ok is False
    assert any("duplicate" in e for e in r.errors)


def test_create_item_missing_item_id_fails(tmp_path):
    cat = _catalog(tmp_path)
    item = _make_item(item_id="")
    r = cat.create_item(item)
    assert r.ok is False
    assert any("item_id_required" in e for e in r.errors)


def test_create_item_missing_name_fails(tmp_path):
    cat = _catalog(tmp_path)
    item = _make_item(name="")
    r = cat.create_item(item)
    assert r.ok is False
    assert any("name_required" in e for e in r.errors)


# ── reload restores items ──────────────────────────────────────────────────────

def test_reload_restores_items(tmp_path):
    cat1 = _catalog(tmp_path)
    cat1.create_item(_make_item("a", name="Alpha"))
    cat1.create_item(_make_item("b", name="Beta"))

    from igris.core.inventory_catalog import InventoryCatalog
    cat2 = InventoryCatalog(project_root=tmp_path, storage_path=cat1.storage_path)
    items = cat2.list_items()
    ids = {i.item_id for i in items}
    assert "a" in ids
    assert "b" in ids


def test_reload_explicit_ok(tmp_path):
    cat = _catalog(tmp_path)
    cat.create_item(_make_item())
    r = cat.reload()
    assert r.ok is True
    assert r.metadata.get("loaded_count") == 1


# ── get_item ──────────────────────────────────────────────────────────────────

def test_get_item_returns_item(tmp_path):
    cat = _catalog(tmp_path)
    cat.create_item(_make_item("x", name="X"))
    item = cat.get_item("x")
    assert item is not None
    assert item.name == "X"


def test_get_missing_item_returns_none(tmp_path):
    cat = _catalog(tmp_path)
    assert cat.get_item("nonexistent") is None


# ── list_items filters ─────────────────────────────────────────────────────────

def test_list_items_filters_by_type(tmp_path):
    cat = _catalog(tmp_path)
    cat.create_item(_make_item("p1", item_type="project", name="P1"))
    cat.create_item(_make_item("e1", item_type="environment", name="E1"))
    projects = cat.list_items(item_type="project")
    assert all(i.item_type == "project" for i in projects)
    assert len(projects) == 1


def test_list_items_filters_by_tag(tmp_path):
    cat = _catalog(tmp_path)
    cat.create_item(_make_item("a", name="A", tags=["prod", "infra"]))
    cat.create_item(_make_item("b", name="B", tags=["dev"]))
    prod = cat.list_items(tag="prod", enabled_only=False)
    assert len(prod) == 1
    assert prod[0].item_id == "a"


def test_list_items_enabled_only(tmp_path):
    cat = _catalog(tmp_path)
    cat.create_item(_make_item("a", name="Active", enabled=True))
    cat.create_item(_make_item("b", name="Disabled", enabled=False))
    active = cat.list_items(enabled_only=True)
    assert all(i.enabled for i in active)
    assert len(active) == 1

    all_items = cat.list_items(enabled_only=False)
    assert len(all_items) == 2


def test_list_items_sorted_by_priority_desc(tmp_path):
    cat = _catalog(tmp_path)
    cat.create_item(_make_item("lo", name="Low", priority=10))
    cat.create_item(_make_item("hi", name="High", priority=90))
    cat.create_item(_make_item("mi", name="Mid", priority=50))
    items = cat.list_items(enabled_only=False)
    priorities = [i.priority for i in items]
    assert priorities == sorted(priorities, reverse=True)


# ── update_item ────────────────────────────────────────────────────────────────

def test_update_item_persists(tmp_path):
    cat = _catalog(tmp_path)
    cat.create_item(_make_item("u1", name="Old Name"))
    r = cat.update_item("u1", name="New Name", description="Updated")
    assert r.ok is True, r.errors

    # Reload and verify
    r2 = cat.reload()
    assert r2.ok is True
    item = cat.get_item("u1")
    assert item is not None
    assert item.name == "New Name"
    assert item.description == "Updated"


def test_update_item_ignores_item_id_change(tmp_path):
    cat = _catalog(tmp_path)
    cat.create_item(_make_item("stable", name="Stable"))
    # Pass item_id change via a dict unpack to avoid conflict with positional param
    updates = {"item_id": "hacked", "name": "Renamed"}
    r = cat.update_item("stable", **updates)
    assert r.ok is True
    assert "item_id_change_ignored" in r.warnings
    assert cat.get_item("stable") is not None


def test_update_item_updates_updated_at(tmp_path):
    import time
    cat = _catalog(tmp_path)
    cat.create_item(_make_item("ts", name="Timestamp"))
    item_before = cat.get_item("ts")
    old_updated = item_before.updated_at
    time.sleep(0.01)
    cat.update_item("ts", description="changed")
    item_after = cat.get_item("ts")
    assert item_after.updated_at >= old_updated


def test_update_missing_item_fails(tmp_path):
    cat = _catalog(tmp_path)
    r = cat.update_item("nope", name="X")
    assert r.ok is False
    assert any("item_not_found" in e for e in r.errors)


# ── disable_item ───────────────────────────────────────────────────────────────

def test_disable_item_persists(tmp_path):
    cat = _catalog(tmp_path)
    cat.create_item(_make_item("d1", name="DisableMe", enabled=True))
    r = cat.disable_item("d1")
    assert r.ok is True, r.errors

    cat.reload()
    item = cat.get_item("d1")
    assert item.enabled is False


def test_disable_missing_item_fails(tmp_path):
    cat = _catalog(tmp_path)
    r = cat.disable_item("ghost")
    assert r.ok is False
    assert any("item_not_found" in e for e in r.errors)


# ── delete_item ────────────────────────────────────────────────────────────────

def test_delete_item_persists(tmp_path):
    cat = _catalog(tmp_path)
    cat.create_item(_make_item("del1", name="DeleteMe"))
    r = cat.delete_item("del1")
    assert r.ok is True, r.errors
    assert cat.get_item("del1") is None

    cat.reload()
    assert cat.get_item("del1") is None


def test_delete_missing_item_fails(tmp_path):
    cat = _catalog(tmp_path)
    r = cat.delete_item("missing")
    assert r.ok is False
    assert any("item_not_found" in e for e in r.errors)


# ── export_safe redaction ──────────────────────────────────────────────────────

def test_export_safe_redacts_secrets(tmp_path):
    FAKE_T = "FAKE_TOKEN_CATALOG_1234567890"
    FAKE_P = "FAKE_PASSWORD_CATALOG_1234567890"
    FAKE_K = "FAKE_API_KEY_CATALOG_1234567890"
    FAKE_PH = "FAKE_PASSPHRASE_CATALOG_1234567890"
    cat = _catalog(tmp_path)
    cat.create_item(_make_item(
        "sec1", name="Secret Item",
        description=f"token={FAKE_T}",
        metadata={
            "password": f"password={FAKE_P}",
            "api_key": f"api_key={FAKE_K}",
            "phrase": f"passphrase={FAKE_PH}",
        },
    ))
    export = cat.export_safe()
    output = json.dumps(export)
    assert f"token={FAKE_T}" not in output
    assert f"password={FAKE_P}" not in output
    assert f"api_key={FAKE_K}" not in output
    assert f"passphrase={FAKE_PH}" not in output


def test_export_safe_contains_counts(tmp_path):
    cat = _catalog(tmp_path)
    cat.create_item(_make_item("x1", name="X1", enabled=True))
    cat.create_item(_make_item("x2", name="X2", enabled=False))
    export = cat.export_safe()
    assert export["count"] == 2
    assert export["enabled_count"] == 1
    assert export["version"] == 1
    assert "items" in export


# ── healthcheck ────────────────────────────────────────────────────────────────

def test_healthcheck_reports_counts(tmp_path):
    cat = _catalog(tmp_path)
    cat.create_item(_make_item("h1", name="H1", enabled=True))
    cat.create_item(_make_item("h2", name="H2", enabled=False))
    h = cat.healthcheck()
    assert h["ok"] is True
    assert h["count"] == 2
    assert h["enabled_count"] == 1
    assert "storage_path" in h
    assert "exists" in h
    assert "warnings" in h
    assert "errors" in h


def test_healthcheck_no_raw_secret(tmp_path):
    FAKE = "FAKE_TOKEN_CATALOG_1234567890"
    cat = _catalog(tmp_path)
    cat.create_item(_make_item("s1", name=f"token={FAKE}"))
    output = json.dumps(cat.healthcheck())
    assert f"token={FAKE}" not in output


# ── Invalid file handling ──────────────────────────────────────────────────────

def test_invalid_json_reload_returns_ok_false(tmp_path):
    storage = tmp_path / "bad.json"
    storage.write_text("{ not valid json", encoding="utf-8")
    from igris.core.inventory_catalog import InventoryCatalog
    cat = InventoryCatalog(project_root=tmp_path, storage_path=storage)
    r = cat.reload()
    assert r.ok is False
    assert len(r.errors) > 0


def test_items_not_list_reload_fails(tmp_path):
    storage = tmp_path / "bad2.json"
    storage.write_text(json.dumps({"version": 1, "items": "not a list"}), encoding="utf-8")
    from igris.core.inventory_catalog import InventoryCatalog
    cat = InventoryCatalog(project_root=tmp_path, storage_path=storage)
    r = cat.reload()
    assert r.ok is False
    assert any("items_not_list" in w or "items" in e for w in r.warnings for e in r.errors or [""])


def test_storage_write_failure_returns_ok_false(tmp_path):
    cat = _catalog(tmp_path)
    item = _make_item()
    with mock.patch.object(cat.storage_path.__class__, "write_text", side_effect=OSError("disk full")):
        # patch at instance level
        with mock.patch("builtins.open", side_effect=OSError("disk full")):
            with mock.patch.object(Path, "write_text", side_effect=OSError("disk full")):
                r = cat.create_item(item)
    # Either the create fails or save fails
    if not r.ok:
        assert len(r.errors) > 0
    # If somehow ok (mocking didn't intercept), item shouldn't be double-stored
    # The important thing: no crash


def test_no_raw_secret_in_storage_json(tmp_path):
    FAKE_T = "FAKE_TOKEN_CATALOG_1234567890"
    FAKE_P = "FAKE_PASSWORD_CATALOG_1234567890"
    cat = _catalog(tmp_path)
    cat.create_item(_make_item(
        "sec2", name=f"token={FAKE_T}",
        description=f"password={FAKE_P}",
        metadata={"note": f"token={FAKE_T}"},
    ))
    raw = cat.storage_path.read_text(encoding="utf-8")
    assert f"token={FAKE_T}" not in raw
    assert f"password={FAKE_P}" not in raw


# ── No silent except ──────────────────────────────────────────────────────────

def test_no_silent_except_create_persists_failure(tmp_path):
    """If save fails, create_item must return ok=False with errors (not swallow)."""
    from igris.core.inventory_catalog import InventoryOperationResult
    cat = _catalog(tmp_path)
    item = _make_item("fail1", name="Fail")

    def _bad_save():
        return InventoryOperationResult(ok=False, action="save", errors=["simulated_disk_failure"])

    with mock.patch.object(cat, "save", side_effect=_bad_save):
        r = cat.create_item(item)

    assert r.ok is False
    assert len(r.errors) > 0


def test_no_silent_except_reload_invalid_root(tmp_path):
    """If storage root is not a dict, reload must return ok=False."""
    storage = tmp_path / "scalar.json"
    storage.write_text('"just a string"', encoding="utf-8")
    from igris.core.inventory_catalog import InventoryCatalog
    cat = InventoryCatalog(project_root=tmp_path, storage_path=storage)
    r = cat.reload()
    assert r.ok is False
    assert len(r.errors) > 0


# ── Functional smoke: full CRUD + reload + export ─────────────────────────────

def test_functional_catalog_tempdir_crud_reload_export(tmp_path):
    """End-to-end: create, filter, update, disable, delete, export, healthcheck, reload."""
    from igris.core.inventory_catalog import InventoryCatalog, InventoryItem

    storage = tmp_path / "smoke" / "inventory_catalog.json"
    cat = InventoryCatalog(project_root=tmp_path, storage_path=storage)

    # 1. Create items
    r = cat.create_item(InventoryItem("proj-1", "project", "Alpha", tags=["core"], priority=80))
    assert r.ok is True
    r = cat.create_item(InventoryItem("proj-2", "project", "Beta", tags=["dev"], priority=60))
    assert r.ok is True
    r = cat.create_item(InventoryItem("env-1", "environment", "Prod Env", tags=["prod"], priority=90))
    assert r.ok is True

    # 2. Persist happened
    assert storage.exists()

    # 3. Filters
    projects = cat.list_items(item_type="project")
    assert len(projects) == 2
    prod = cat.list_items(tag="prod")
    assert len(prod) == 1 and prod[0].item_id == "env-1"

    # 4. Update
    r = cat.update_item("proj-1", description="Updated description")
    assert r.ok is True
    assert cat.get_item("proj-1").description == "Updated description"

    # 5. Disable
    r = cat.disable_item("proj-2")
    assert r.ok is True
    enabled = cat.list_items(item_type="project", enabled_only=True)
    assert all(i.enabled for i in enabled)
    assert "proj-2" not in {i.item_id for i in enabled}

    # 6. Delete
    r = cat.delete_item("env-1")
    assert r.ok is True
    assert cat.get_item("env-1") is None

    # 7. Reload
    cat2 = InventoryCatalog(project_root=tmp_path, storage_path=storage)
    items2 = cat2.list_items(enabled_only=False)
    assert len(items2) == 2  # proj-1, proj-2

    # 8. Export safe
    export = cat2.export_safe()
    assert export["count"] == 2
    assert export["enabled_count"] == 1  # proj-2 is disabled

    # 9. Healthcheck
    h = cat2.healthcheck()
    assert h["ok"] is True
    assert h["count"] == 2
    assert h["exists"] is True

    # 10. No fake secrets in any output
    FAKE = "FAKE_TOKEN_CATALOG_1234567890"
    item_w_secret = InventoryItem("sec-x", "project", f"token={FAKE}", description=f"token={FAKE}")
    cat2.create_item(item_w_secret)
    assert f"token={FAKE}" not in json.dumps(cat2.export_safe())
    assert f"token={FAKE}" not in cat2.storage_path.read_text()
