"""Tests for Decision Memory API endpoints."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from igris.web.server import create_app


def _client(tmp_path):
    from igris.models.config import CONFIG
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    (root / ".igris" / "tasks").mkdir(parents=True)
    (root / ".igris" / "timeline").mkdir(parents=True)
    (root / ".igris" / "missions").mkdir(parents=True)
    (root / ".igris" / "memory").mkdir(parents=True)
    os.environ["PROJECT_ROOT"] = str(root)
    os.environ["WORKSPACE_ROOT"] = str(root)
    CONFIG.project_root = Path(str(root))
    return TestClient(create_app())


def test_failures_empty(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/memory/failures")
    assert r.status_code == 200
    assert r.json()["events"] == []


def test_decisions_empty(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/memory/decisions")
    assert r.status_code == 200
    assert r.json()["events"] == []


def test_saturation_empty(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/memory/saturation")
    assert r.status_code == 200
    assert r.json()["saturated_families"] == []


def test_record_decision_event(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/memory/events", json={
        "event_type": "decision",
        "title": "Chose approach A",
        "family": "code",
        "description": "Selected modular approach",
        "outcome": "success",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "Chose approach A"
    assert data["event_type"] == "decision"
    # Verify it appears in list
    r2 = c.get("/api/memory/decisions")
    assert len(r2.json()["events"]) == 1


def test_record_failure_event(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/memory/events", json={
        "event_type": "failure",
        "title": "Tests failed",
        "family": "test",
        "reason": "assertion error in test_foo",
    })
    assert r.status_code == 200
    r2 = c.get("/api/memory/failures")
    assert len(r2.json()["events"]) == 1


def test_record_saturation_event(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/memory/events", json={
        "event_type": "saturation",
        "family": "testing",
        "reason": "too many test tasks",
    })
    assert r.status_code == 200
    r2 = c.get("/api/memory/saturation")
    assert "testing" in r2.json()["saturated_families"]


def test_record_remediation_event(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/memory/events", json={
        "event_type": "remediation",
        "title": "Fix approach B",
        "family": "fix",
        "outcome": "pending",
    })
    assert r.status_code == 200
    assert r.json()["event_type"] == "remediation"


def test_invalid_event_type(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/memory/events", json={
        "event_type": "invalid",
        "title": "Bad",
    })
    assert r.status_code == 400


def test_missing_title(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/memory/events", json={
        "event_type": "decision",
    })
    assert r.status_code == 400


def test_saturation_missing_family(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/memory/events", json={
        "event_type": "saturation",
    })
    assert r.status_code == 400


def test_secret_redacted_in_response(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/memory/events", json={
        "event_type": "decision",
        "title": "Decision with API_KEY=sk-secret123",
        "description": "Used token ghp_abcdef1234567890",
    })
    assert r.status_code == 200
    text = r.text
    assert "sk-secret123" not in text
    assert "ghp_abcdef1234567890" not in text


def test_constraints_reflect_saturation(tmp_path):
    c = _client(tmp_path)
    c.post("/api/memory/events", json={"event_type": "saturation", "family": "code"})
    r = c.get("/api/memory/saturation")
    data = r.json()
    assert "code" in data["saturated_families"]
    assert "code" in data["constraints"]["avoid_families"]


def test_limit_parameter(tmp_path):
    c = _client(tmp_path)
    for i in range(10):
        c.post("/api/memory/events", json={
            "event_type": "decision", "title": f"D{i}", "family": "code",
        })
    r = c.get("/api/memory/decisions?limit=3")
    assert len(r.json()["events"]) == 3
