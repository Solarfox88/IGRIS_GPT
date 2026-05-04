"""API tests for decision reports endpoints (Sprint 15)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from igris.web.server import create_app


@pytest.fixture
def client(tmp_path):
    from igris.models.config import CONFIG
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    for d in [".igris/tasks", ".igris/timeline", ".igris/memory", ".igris/reports/decisions"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    os.environ["PROJECT_ROOT"] = str(root)
    os.environ["WORKSPACE_ROOT"] = str(root)
    CONFIG.project_root = Path(str(root))
    return TestClient(create_app())


class TestDecisionReportAPI:
    def test_list_empty(self, client):
        r = client.get("/api/decision-reports")
        assert r.status_code == 200
        assert r.json()["reports"] == []

    def test_create_report(self, client):
        r = client.post("/api/decision-reports", json={
            "step_number": 1,
            "action_type": "execute_command",
            "action_detail": "ran tests",
            "outcome": "success",
        })
        assert r.status_code == 200
        d = r.json()
        assert d["step_number"] == 1
        assert d["id"]
        assert "project_snapshot" in d
        assert "memory_constraints" in d

    def test_get_report(self, client):
        r1 = client.post("/api/decision-reports", json={
            "step_number": 1,
            "outcome": "success",
        })
        rid = r1.json()["id"]
        r2 = client.get(f"/api/decision-reports/{rid}")
        assert r2.status_code == 200
        assert r2.json()["id"] == rid

    def test_get_404(self, client):
        r = client.get("/api/decision-reports/nonexistent")
        assert r.status_code == 404

    def test_list_after_create(self, client):
        client.post("/api/decision-reports", json={"step_number": 1, "outcome": "ok"})
        client.post("/api/decision-reports", json={"step_number": 2, "outcome": "ok"})
        r = client.get("/api/decision-reports")
        assert len(r.json()["reports"]) == 2

    def test_no_secrets(self, client):
        r = client.post("/api/decision-reports", json={
            "step_number": 1,
            "action_detail": "with sk-abcdefghijklmnopqrstuvwxyz",
            "outcome": "success",
        })
        text = json.dumps(r.json())
        assert "sk-" not in text

    def test_report_with_safety_decisions(self, client):
        r = client.post("/api/decision-reports", json={
            "step_number": 1,
            "outcome": "blocked",
            "safety_decisions": [{"check": "rate_limit", "passed": False}],
        })
        assert r.status_code == 200
        assert len(r.json()["safety_decisions"]) == 1
