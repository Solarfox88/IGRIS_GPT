"""Tests for file browser hardening."""
import os
from fastapi.testclient import TestClient
from igris.web.server import create_app
from igris.models.config import CONFIG


def _client(tmp_path):
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    os.environ["PROJECT_ROOT"] = str(root)
    CONFIG.project_root = root
    return TestClient(create_app())


def test_traversal_blocked(tmp_path):
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    (root / "foo.txt").write_text("safe content")
    os.environ["PROJECT_ROOT"] = str(root)
    CONFIG.project_root = root
    client = TestClient(create_app())
    resp = client.get("/api/files/preview", params={"path": "../pyproject.toml"})
    assert resp.status_code == 403


def test_dotenv_blocked(tmp_path):
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    (root / ".env").write_text("SECRET=abc123")
    os.environ["PROJECT_ROOT"] = str(root)
    CONFIG.project_root = root
    client = TestClient(create_app())
    resp = client.get("/api/files/preview", params={"path": ".env"})
    assert resp.status_code == 403


def test_binary_file_blocked(tmp_path):
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    (root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    os.environ["PROJECT_ROOT"] = str(root)
    CONFIG.project_root = root
    client = TestClient(create_app())
    resp = client.get("/api/files/preview", params={"path": "image.png"})
    assert resp.status_code == 400


def test_secret_content_redacted(tmp_path):
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    (root / "readme.txt").write_text("my key is sk-abc123def456ghi789jkl012mno345pqr")
    os.environ["PROJECT_ROOT"] = str(root)
    CONFIG.project_root = root
    client = TestClient(create_app())
    resp = client.get("/api/files/preview", params={"path": "readme.txt"})
    assert resp.status_code == 200
    assert "REDACTED" in resp.json()["preview"]
