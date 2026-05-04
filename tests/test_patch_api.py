"""Tests for patch proposal API endpoints."""

import os

from fastapi.testclient import TestClient

from igris.web.server import create_app


def _client(tmp_path):
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    (root / "docs").mkdir()
    (root / "README.md").write_text("# Test\n")
    os.environ["PROJECT_ROOT"] = str(root)
    os.environ["WORKSPACE_ROOT"] = str(root)
    return TestClient(create_app())


def test_list_patches_empty(tmp_path):
    client = _client(tmp_path)
    r = client.get("/api/patches")
    assert r.status_code == 200
    assert "patches" in r.json()


def test_propose_patch(tmp_path):
    client = _client(tmp_path)
    r = client.post("/api/patches/propose", json={
        "title": "Add doc",
        "description": "Test proposal",
        "files": [{"path": "docs/test.md", "action": "create", "after": "# Test\n"}],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["id"]
    assert data["status"] == "proposed"
    assert len(data["files"]) == 1
    assert data["files"][0]["diff"]


def test_propose_no_files(tmp_path):
    client = _client(tmp_path)
    r = client.post("/api/patches/propose", json={
        "title": "Empty",
        "files": [],
    })
    assert r.status_code == 400


def test_get_patch_detail(tmp_path):
    client = _client(tmp_path)
    r1 = client.post("/api/patches/propose", json={
        "title": "Detail test",
        "files": [{"path": "docs/d.md", "action": "create", "after": "d\n"}],
    })
    pid = r1.json()["id"]
    r2 = client.get(f"/api/patches/{pid}")
    assert r2.status_code == 200
    assert r2.json()["title"] == "Detail test"


def test_get_patch_not_found(tmp_path):
    client = _client(tmp_path)
    r = client.get("/api/patches/nonexistent")
    assert r.status_code == 404


def test_validate_patch(tmp_path):
    client = _client(tmp_path)
    r1 = client.post("/api/patches/propose", json={
        "title": "Validate test",
        "files": [{"path": "docs/v.md", "action": "create", "after": "valid\n"}],
    })
    pid = r1.json()["id"]
    r2 = client.post(f"/api/patches/{pid}/validate")
    assert r2.status_code == 200
    assert r2.json()["validation"]["valid"] is True
    assert r2.json()["status"] == "validated"


def test_validate_blocks_env(tmp_path):
    client = _client(tmp_path)
    r1 = client.post("/api/patches/propose", json={
        "title": "Env patch",
        "files": [{"path": ".env", "action": "modify", "after": "SECRET=x"}],
    })
    pid = r1.json()["id"]
    r2 = client.post(f"/api/patches/{pid}/validate")
    assert r2.status_code == 200
    assert r2.json()["validation"]["valid"] is False


def test_apply_validated_patch(tmp_path):
    client = _client(tmp_path)
    r1 = client.post("/api/patches/propose", json={
        "title": "Apply test",
        "files": [{"path": "docs/applied.md", "action": "create", "after": "# Applied\n"}],
    })
    pid = r1.json()["id"]
    client.post(f"/api/patches/{pid}/validate")
    r3 = client.post(f"/api/patches/{pid}/apply")
    assert r3.status_code == 200
    assert r3.json()["success"] is True


def test_apply_without_validate_fails(tmp_path):
    client = _client(tmp_path)
    r1 = client.post("/api/patches/propose", json={
        "title": "No validate",
        "files": [{"path": "docs/nv.md", "action": "create", "after": "nv\n"}],
    })
    pid = r1.json()["id"]
    r2 = client.post(f"/api/patches/{pid}/apply")
    assert r2.status_code == 400


def test_reject_patch(tmp_path):
    client = _client(tmp_path)
    r1 = client.post("/api/patches/propose", json={
        "title": "Reject test",
        "files": [{"path": "docs/rej.md", "action": "create", "after": "r\n"}],
    })
    pid = r1.json()["id"]
    r2 = client.post(f"/api/patches/{pid}/reject", json={"reason": "Not needed"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "rejected"


def test_timeline_receives_patch_event(tmp_path):
    client = _client(tmp_path)
    client.post("/api/patches/propose", json={
        "title": "Timeline test",
        "files": [{"path": "docs/tl.md", "action": "create", "after": "tl\n"}],
    })
    r = client.get("/api/agent/timeline")
    assert r.status_code == 200
    events = r.json().get("timeline", [])
    patch_events = [e for e in events if e.get("type") == "patch"]
    assert len(patch_events) > 0


def test_no_secrets_in_response(tmp_path):
    client = _client(tmp_path)
    r = client.post("/api/patches/propose", json={
        "title": "Safe response",
        "files": [{"path": "docs/s.md", "action": "create", "after": "safe content\n"}],
    })
    body = r.text
    assert "sk-" not in body
    assert "OPENAI_API_KEY" not in body
