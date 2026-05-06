"""API tests for Context Manager endpoints — Epic #60."""

import pytest
from fastapi.testclient import TestClient

from igris.web.server import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


class TestContextBuildAPI:
    """Test POST /api/context/build."""

    def test_build_basic(self, client):
        resp = client.post("/api/context/build", json={
            "goal": "Add /api/ping endpoint",
            "role": "coder",
            "profile": "default",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "mission_context" in data
        assert "file_context" in data
        assert "role" in data
        assert data["role"] == "coder"

    def test_build_with_errors(self, client):
        resp = client.post("/api/context/build", json={
            "goal": "fix failing test",
            "recent_errors": [{"type": "test_failure", "message": "assert 1 == 2"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "assert 1 == 2" in data["error_context"]

    def test_build_empty(self, client):
        resp = client.post("/api/context/build", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["budget_chars"], int)


class TestContextBudgetsAPI:
    """Test GET /api/context/budgets."""

    def test_budgets(self, client):
        resp = client.get("/api/context/budgets")
        assert resp.status_code == 200
        data = resp.json()
        assert "default" in data
        assert "local_light" in data
        assert data["default"]["approximate_tokens"] > 0


class TestContextScoreFilesAPI:
    """Test POST /api/context/score-files."""

    def test_score_files(self, client):
        resp = client.post("/api/context/score-files", json={
            "files": ["server.py", "utils.py", "readme.md"],
            "keywords": ["server"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["files"]) == 3
        # server.py should be ranked first due to keyword match
        assert data["files"][0]["path"] == "server.py"
        assert data["files"][0]["score"] > 0

    def test_score_empty(self, client):
        resp = client.post("/api/context/score-files", json={"files": [], "keywords": []})
        assert resp.status_code == 200
        data = resp.json()
        assert data["files"] == []
