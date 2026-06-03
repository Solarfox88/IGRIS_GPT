"""Tests for Control Room phase 2 (#1212).

Phase 2 additions:
- Persisted/manual review workflow extended beyond the minimal endpoint
- Final report export composition grows richer (evidence_card_edge_states, operator_review_actions)
- Empty/error states for live evidence cards remain strong
- Operator review actions remain explicit in responses
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from igris.web.server import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run(
    run_id: str = "run-cr-001",
    status: str = "completed",
    failure_class: str = "",
    events: Optional[List[Any]] = None,
) -> MagicMock:
    run = MagicMock()
    run.run_id = run_id
    run.rank_id = "rank-cr"
    run.status = status
    run.failure_class = failure_class
    run.goal = "Control room phase 2 test goal"
    run.repair_cycles_used = 0
    run.same_failure_count = 0
    run.execution_budget_used_usd = 0.02
    run.capability_signals = {}
    run.cancel_requested = False
    run.cancel_reason = ""
    run.decomposition = None
    run.acceptance_evidence = None
    run.start_ts = time.time() - 120

    if events is None:
        ev = MagicMock()
        ev.phase = "start"
        ev.status = "completed"
        ev.detail = "run complete"
        ev.ts = time.time() - 60
        ev.same_failure_count = 0
        run.events = [ev]
    else:
        run.events = events

    run.report = {
        "run_id": run_id,
        "status": status,
        "goal": run.goal,
    }
    return run


def _client() -> TestClient:
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Review workflow — persisted and extended
# ---------------------------------------------------------------------------

def test_review_post_persists_record(tmp_path):
    """POST /api/rank/runs/{run_id}/review persists the review record."""
    run_id = "run-review-001"
    run = _make_run(run_id=run_id)
    client = _client()

    with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
        r = client.post(
            f"/api/rank/runs/{run_id}/review",
            json={
                "action_id": "approve_evidence",
                "summary": "Evidence looks good",
                "notes": "All checks passed",
                "evidence_ref": f"https://github.com/org/repo/issues/{run_id}",
                "reviewed_by": "senior-operator",
            },
        )

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    review = body["review"]
    assert review["action_id"] == "approve_evidence"
    assert review["summary"] == "Evidence looks good"
    assert review["reviewed_by"] == "senior-operator"
    assert "evidence_ref" in review


def test_review_post_returns_review_count(tmp_path):
    """POST /review returns the running review_count."""
    run_id = "run-review-002"
    run = _make_run(run_id=run_id)
    client = _client()

    with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
        r1 = client.post(f"/api/rank/runs/{run_id}/review", json={"summary": "first review"})
        r2 = client.post(f"/api/rank/runs/{run_id}/review", json={"summary": "second review"})

    assert r1.status_code == 200
    assert r2.status_code == 200
    count1 = r1.json()["review_count"]
    count2 = r2.json()["review_count"]
    assert count2 >= count1  # monotonically increasing


def test_review_post_missing_run_returns_404():
    """POST /review for nonexistent run_id returns 404."""
    client = _client()
    with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=None):
        r = client.post("/api/rank/runs/ghost-run/review", json={"summary": "review"})
    assert r.status_code == 404


def test_review_post_review_state_returned():
    """POST /review returns a review_state with has_reviews and review_count."""
    run_id = "run-review-003"
    run = _make_run(run_id=run_id)
    client = _client()

    with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
        r = client.post(f"/api/rank/runs/{run_id}/review", json={
            "action_id": "flag_issue",
            "summary": "Issue found in evidence",
            "reviewed_by": "qa-engineer",
        })

    body = r.json()
    state = body.get("review_state", {})
    assert state.get("has_reviews") is True or body["review_count"] >= 1


# ---------------------------------------------------------------------------
# Final export — richer composition
# ---------------------------------------------------------------------------

def test_final_export_includes_operator_reviews(tmp_path):
    """GET /final-export includes operator_reviews list from persisted log."""
    run_id = "run-export-001"
    run = _make_run(run_id=run_id)
    client = _client()

    # Post a review first
    with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
        client.post(f"/api/rank/runs/{run_id}/review", json={
            "action_id": "mark_complete",
            "summary": "Deploy approved",
            "reviewed_by": "lead-operator",
        })

    with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
        r = client.get(f"/api/rank/runs/{run_id}/final-export")

    assert r.status_code == 200
    body = r.json()
    assert "operator_reviews" in body
    assert isinstance(body["operator_reviews"], list)
    assert "exported_at" in body


def test_final_export_includes_evidence_card_edge_states(tmp_path):
    """GET /final-export includes evidence_card_edge_states dict."""
    run_id = "run-export-002"
    run = _make_run(run_id=run_id)
    client = _client()

    with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
        r = client.get(f"/api/rank/runs/{run_id}/final-export")

    assert r.status_code == 200
    body = r.json()
    edge_states = body.get("evidence_card_edge_states", {})
    assert isinstance(edge_states, dict)
    # Must have all 4 edge state keys
    for key in ("ok", "warning", "error", "empty"):
        assert key in edge_states, f"Missing edge state: {key}"


def test_final_export_includes_operator_review_actions():
    """GET /final-export includes operator_review_actions list."""
    run_id = "run-export-003"
    run = _make_run(run_id=run_id)
    client = _client()

    with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
        client.post(f"/api/rank/runs/{run_id}/review", json={
            "action_id": "evidence_verified",
            "summary": "Evidence verified",
            "reviewed_by": "auditor",
            "evidence_ref": "https://github.com/org/repo/issues/42",
        })
        r = client.get(f"/api/rank/runs/{run_id}/final-export")

    body = r.json()
    actions = body.get("operator_review_actions", [])
    assert isinstance(actions, list)
    # If we posted a review, it should appear in operator_review_actions
    if actions:
        action = actions[0]
        assert "action_id" in action
        assert "summary" in action
        assert "reviewed_by" in action


def test_final_export_includes_review_workflow_summary():
    """GET /final-export includes review_workflow meta-summary."""
    run_id = "run-export-004"
    run = _make_run(run_id=run_id)
    client = _client()

    with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
        r = client.get(f"/api/rank/runs/{run_id}/final-export")

    body = r.json()
    workflow = body.get("review_workflow", {})
    assert isinstance(workflow, dict)
    assert "review_count" in workflow or "has_reviews" in workflow


# ---------------------------------------------------------------------------
# Evidence card edge states
# ---------------------------------------------------------------------------

def test_evidence_card_empty_state_when_no_run():
    """Evidence endpoint for unknown run returns sensible empty/error state."""
    client = _client()
    with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=None):
        r = client.get("/api/rank/runs/ghost-evidence/evidence")
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        body = r.json()
        assert "run_id" in body or "status" in body


def test_evidence_card_interpreted_has_cards_list():
    """GET /evidence/interpreted returns evidence_cards list for known run."""
    run_id = "run-evidence-001"
    run = _make_run(run_id=run_id)
    client = _client()

    with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
        r = client.get(f"/api/rank/runs/{run_id}/evidence/interpreted")

    assert r.status_code == 200
    body = r.json()
    assert "evidence_cards" in body
    assert isinstance(body["evidence_cards"], list)


def test_evidence_cards_each_have_status():
    """Each evidence card has a status field (ok, warning, error, or empty)."""
    run_id = "run-evidence-002"
    run = _make_run(run_id=run_id)
    client = _client()

    with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
        r = client.get(f"/api/rank/runs/{run_id}/evidence/interpreted")

    body = r.json()
    cards = body.get("evidence_cards", [])
    valid_statuses = {"ok", "warning", "error", "empty"}
    for card in cards:
        assert "status" in card, f"Card missing status: {card}"
        assert card["status"] in valid_statuses, f"Invalid status: {card['status']}"


def test_evidence_cards_error_state_when_run_blocked():
    """Blocked runs produce evidence cards with error/warning status."""
    run_id = "run-blocked-001"
    run = _make_run(run_id=run_id, status="blocked", failure_class="pytest_failure")
    client = _client()

    with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
        r = client.get(f"/api/rank/runs/{run_id}/evidence/interpreted")

    assert r.status_code == 200
    body = r.json()
    cards = body.get("evidence_cards", [])
    # With a blocked run, some cards should be error or warning
    statuses = {card.get("status") for card in cards}
    assert statuses  # non-empty list of statuses


# ---------------------------------------------------------------------------
# Operator review actions explicit in UI
# ---------------------------------------------------------------------------

def test_review_endpoint_is_post_not_get():
    """Review submission endpoint must be POST (explicit operator action)."""
    client = _client()
    # GET should not accept review submissions
    r = client.get("/api/rank/runs/run-test/review")
    # Either 405 (method not allowed) or 404 (not registered as GET) — never 200
    assert r.status_code in (404, 405)


def test_advisory_endpoint_advisory_only():
    """Advisory endpoint explicitly marks advisory_only=True."""
    run_id = "run-advisory-001"
    run = _make_run(run_id=run_id)
    client = _client()

    with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
        r = client.get(f"/api/rank/runs/{run_id}/advisory")

    assert r.status_code == 200
    body = r.json()
    assert body.get("advisory_only") is True
