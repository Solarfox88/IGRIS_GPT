import os
import pytest
from fastapi.testclient import TestClient
from igris.web.server import create_app


def test_preview_blocks_traversal(tmp_path):
    # Setup a temporary project root with a file
    proj_root = tmp_path / "project"
    proj_root.mkdir()
    os.environ["PROJECT_ROOT"] = str(proj_root)
    (proj_root / "foo.txt").write_text("content")
    app = create_app()
    client = TestClient(app)
    # Request path traversal
    resp = client.get("/api/files/preview", params={"path": "../foo.txt"})
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert "path" in detail.lower() or "escape" in detail.lower()