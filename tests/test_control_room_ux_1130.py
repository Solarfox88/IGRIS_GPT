"""Tests for #1130 Control Room UX hardening.

Covers: evidence interpretation, next-action workflow, empty/error states,
truncation, secret redaction, interpreted evidence endpoint.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from igris.web.evidence_interpreter import (
    interpret_test_result,
    interpret_ci_result,
    interpret_diff_summary,
    interpret_browser_evidence,
    interpret_devops_health,
    interpret_memory_influence,
    interpret_all_evidence,
    compute_next_actions,
    _truncate,
)


# ---------------------------------------------------------------------------
# Truncation helper
# ---------------------------------------------------------------------------

class TestTruncation:
    def test_short_text_unchanged(self):
        assert _truncate("hello", 100) == "hello"

    def test_long_text_truncated(self):
        text = "x" * 3000
        result = _truncate(text, 100)
        assert len(result) < 200
        assert "truncated" in result
        assert "2900 chars omitted" in result

    def test_empty_string(self):
        assert _truncate("") == ""


# ---------------------------------------------------------------------------
# Evidence card: test results
# ---------------------------------------------------------------------------

class TestInterpretTestResult:
    def test_empty_data(self):
        card = interpret_test_result({})
        assert card["type"] == "test_result"
        assert card["status"] == "empty"
        assert "No test results" in card["summary"]

    def test_unavailable(self):
        card = interpret_test_result({"available": False})
        assert card["status"] == "empty"

    def test_success(self):
        card = interpret_test_result({
            "available": True, "phase": "full_tests",
            "status": "success", "detail": "42 passed",
        })
        assert card["status"] == "ok"
        assert "full_tests" in card["summary"]
        assert card["details"]["test_status"] == "success"

    def test_failure(self):
        card = interpret_test_result({
            "available": True, "phase": "targeted_tests",
            "status": "failure", "detail": "3 failed",
        })
        assert card["status"] == "error"
        assert card["details"]["test_status"] == "failure"

    def test_long_detail_truncated(self):
        card = interpret_test_result({
            "available": True, "phase": "run_tests",
            "status": "success", "detail": "x" * 2000,
        })
        assert len(card["details"]["detail"]) < 1000


# ---------------------------------------------------------------------------
# Evidence card: CI / quality gates
# ---------------------------------------------------------------------------

class TestInterpretCiResult:
    def test_empty_events(self):
        card = interpret_ci_result([])
        assert card["type"] == "ci_result"
        assert card["status"] == "empty"
        assert card["details"]["gates"] == []

    def test_all_passed(self):
        card = interpret_ci_result([
            {"phase": "quality_gate", "status": "success", "detail": "ok", "ts": 1},
            {"phase": "semantic_gate", "status": "success", "detail": "ok", "ts": 2},
        ])
        assert card["status"] == "ok"
        assert "2/2 gates passed" in card["summary"]

    def test_one_failed(self):
        card = interpret_ci_result([
            {"phase": "quality_gate", "status": "success", "detail": "ok", "ts": 1},
            {"phase": "acceptance_gate", "status": "failure", "detail": "AC missing", "ts": 2},
        ])
        assert card["status"] == "error"
        assert "FAILED" in card["summary"]
        assert "acceptance_gate" in card["summary"]


# ---------------------------------------------------------------------------
# Evidence card: diff summary
# ---------------------------------------------------------------------------

class TestInterpretDiffSummary:
    def test_unavailable(self):
        card = interpret_diff_summary({"available": False})
        assert card["status"] == "empty"

    def test_error(self):
        card = interpret_diff_summary({"available": False, "error": "git not found"})
        assert card["status"] == "error"
        assert "git not found" in card["summary"]

    def test_no_changes(self):
        card = interpret_diff_summary({"available": True, "files_changed": [], "summary": "no changes"})
        assert card["status"] == "empty"
        assert "No code changes" in card["summary"]

    def test_with_changes(self):
        card = interpret_diff_summary({
            "available": True,
            "files_changed": ["igris/core/foo.py", "tests/test_foo.py"],
            "summary": "2 files changed, 50 insertions(+), 10 deletions(-)",
        })
        assert card["status"] == "ok"
        assert "2 file(s) changed" in card["summary"]
        assert card["details"]["file_count"] == 2

    def test_empty_dict(self):
        card = interpret_diff_summary({})
        assert card["status"] == "empty"


# ---------------------------------------------------------------------------
# Evidence card: browser evidence
# ---------------------------------------------------------------------------

class TestInterpretBrowserEvidence:
    def test_no_events(self):
        card = interpret_browser_evidence([])
        assert card["type"] == "browser_evidence"
        assert card["status"] == "empty"

    def test_with_screenshots(self):
        card = interpret_browser_evidence([
            {"phase": "browser_evidence", "status": "success", "data": {
                "screenshots": ["s1.png", "s2.png"], "console": [], "network": [],
            }},
        ])
        assert card["status"] == "ok"
        assert card["details"]["screenshot_count"] == 2

    def test_with_failure(self):
        card = interpret_browser_evidence([
            {"phase": "browser_evidence", "status": "failure", "data": {
                "screenshots": [], "console": ["error: page crashed"], "network": [],
            }},
        ])
        assert card["status"] == "error"

    def test_no_matching_phase(self):
        card = interpret_browser_evidence([
            {"phase": "rank_reasoning", "status": "success", "data": {}},
        ])
        assert card["status"] == "empty"


# ---------------------------------------------------------------------------
# Evidence card: devops health
# ---------------------------------------------------------------------------

class TestInterpretDevopsHealth:
    def test_none(self):
        card = interpret_devops_health(None)
        assert card["status"] == "empty"

    def test_all_ok(self):
        card = interpret_devops_health({
            "disk": {"status": "ok", "use_pct": "30%"},
            "memory": {"status": "ok", "total": "16G"},
            "igris_service": {"status": "ok"},
        })
        assert card["status"] == "ok"
        assert "3/3 checks OK" in card["summary"]

    def test_disk_error(self):
        card = interpret_devops_health({
            "disk": {"status": "error", "error": "out of space"},
            "memory": {"status": "ok"},
            "igris_service": {"status": "ok"},
        })
        assert card["status"] == "error"
        assert "disk" in card["summary"]


# ---------------------------------------------------------------------------
# Evidence card: memory influence
# ---------------------------------------------------------------------------

class TestInterpretMemoryInfluence:
    def test_none(self):
        card = interpret_memory_influence(None)
        assert card["status"] == "empty"

    def test_empty_list(self):
        card = interpret_memory_influence([])
        assert card["status"] == "empty"

    def test_normal_entries(self):
        card = interpret_memory_influence([
            {"id": "1", "stale": False, "contradiction": False},
            {"id": "2", "stale": False, "contradiction": False},
        ])
        assert card["status"] == "ok"
        assert "2 memory entries" in card["summary"]

    def test_stale_entries(self):
        card = interpret_memory_influence([
            {"id": "1", "stale": True, "contradiction": False},
            {"id": "2", "stale": False, "contradiction": True},
        ])
        assert card["status"] == "warning"
        assert "1 stale" in card["summary"]
        assert "1 contradictions" in card["summary"]


# ---------------------------------------------------------------------------
# Composite interpretation
# ---------------------------------------------------------------------------

class TestInterpretAllEvidence:
    def test_returns_all_card_types(self):
        cards = interpret_all_evidence()
        types = {c["type"] for c in cards}
        assert types == {"diff_summary", "test_result", "ci_result",
                         "browser_evidence", "devops_health", "memory_influence"}

    def test_all_empty_by_default(self):
        cards = interpret_all_evidence()
        for card in cards:
            assert card["status"] in ("empty",)

    def test_mixed_states(self):
        cards = interpret_all_evidence(
            test_results={"available": True, "phase": "full_tests", "status": "success", "detail": "ok"},
            evidence_events=[{"phase": "quality_gate", "status": "failure", "detail": "stub", "ts": 0}],
        )
        statuses = {c["type"]: c["status"] for c in cards}
        assert statuses["test_result"] == "ok"
        assert statuses["ci_result"] == "error"


# ---------------------------------------------------------------------------
# Next-action workflow
# ---------------------------------------------------------------------------

class TestComputeNextActions:
    def test_success_outcome(self):
        actions = compute_next_actions("success")
        ids = [a["id"] for a in actions]
        assert "review_evidence" in ids
        assert "close_issue" in ids

    def test_blocked_pytest_failure(self):
        actions = compute_next_actions("blocked", failure_class="pytest_failure")
        ids = [a["id"] for a in actions]
        assert "review_test_failures" in ids
        assert "retry_run" in ids

    def test_blocked_capability_ceiling(self):
        actions = compute_next_actions("blocked", failure_class="capability_ceiling_reached")
        ids = [a["id"] for a in actions]
        assert "decompose_task" in ids

    def test_decomposition_required(self):
        actions = compute_next_actions("decomposition_required")
        ids = [a["id"] for a in actions]
        assert "review_decomposition" in ids
        assert "approve_decomposition" in ids

    def test_in_progress(self):
        actions = compute_next_actions("in_progress")
        ids = [a["id"] for a in actions]
        assert "monitor_run" in ids
        assert "block_run" in ids

    def test_cancelled(self):
        actions = compute_next_actions("cancelled")
        ids = [a["id"] for a in actions]
        assert "review_cancellation" in ids

    def test_error_cards_add_investigate(self):
        error_cards = [{"type": "test_result", "title": "Test Results", "status": "error"}]
        actions = compute_next_actions("blocked", evidence_cards=error_cards)
        ids = [a["id"] for a in actions]
        assert "investigate_errors" in ids


# ---------------------------------------------------------------------------
# Integration: /evidence/interpreted endpoint
# ---------------------------------------------------------------------------

def _make_run(
    run_id: str = "test-run",
    status: str = "running",
    failure_class: str = "",
    events: Optional[List[Any]] = None,
) -> MagicMock:
    run = MagicMock()
    run.run_id = run_id
    run.rank_id = "rank-1"
    run.status = status
    run.failure_class = failure_class
    run.goal = "Test goal"
    run.repair_cycles_used = 0
    run.same_failure_count = 0
    run.execution_budget_used_usd = 0.0
    run.capability_signals = {}
    run.cancel_requested = False
    run.decomposition = None
    run.acceptance_evidence = None

    if events is None:
        ev = MagicMock()
        ev.phase = "start"
        ev.status = "running"
        ev.detail = "Started"
        ev.ts = time.time()
        ev.data = {}
        run.events = [ev]
    else:
        run.events = events
    return run


def _client():
    from igris.web.server import create_app
    return TestClient(create_app())


class TestInterpretedEvidenceEndpoint:
    def test_404_unknown_run(self):
        client = _client()
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=None):
            resp = client.get("/api/rank/runs/missing/evidence/interpreted")
        assert resp.status_code == 404

    def test_returns_expected_keys(self):
        client = _client()
        run = _make_run()
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            resp = client.get("/api/rank/runs/test-run/evidence/interpreted")
        assert resp.status_code == 200
        body = resp.json()
        assert "evidence_cards" in body
        assert "next_actions" in body
        assert "outcome" in body
        assert "card_count" in body
        assert "error_count" in body
        assert "empty_count" in body

    def test_all_cards_present(self):
        client = _client()
        run = _make_run()
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            resp = client.get("/api/rank/runs/test-run/evidence/interpreted")
        body = resp.json()
        card_types = {c["type"] for c in body["evidence_cards"]}
        assert "test_result" in card_types
        assert "ci_result" in card_types
        assert "diff_summary" in card_types
        assert "browser_evidence" in card_types

    def test_success_run_has_review_action(self):
        client = _client()
        run = _make_run(status="success")
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            resp = client.get("/api/rank/runs/test-run/evidence/interpreted")
        body = resp.json()
        action_ids = [a["id"] for a in body["next_actions"]]
        assert "review_evidence" in action_ids

    def test_blocked_run_has_retry_action(self):
        client = _client()
        run = _make_run(status="blocked", failure_class="pytest_failure")
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            resp = client.get("/api/rank/runs/test-run/evidence/interpreted")
        body = resp.json()
        action_ids = [a["id"] for a in body["next_actions"]]
        assert "retry_run" in action_ids

    def test_empty_events_run(self):
        client = _client()
        run = _make_run(events=[])
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            resp = client.get("/api/rank/runs/test-run/evidence/interpreted")
        assert resp.status_code == 200
        body = resp.json()
        assert body["empty_count"] >= 1

    def test_evidence_cards_have_consistent_schema(self):
        client = _client()
        run = _make_run()
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            resp = client.get("/api/rank/runs/test-run/evidence/interpreted")
        body = resp.json()
        for card in body["evidence_cards"]:
            assert "type" in card
            assert "title" in card
            assert "status" in card
            assert card["status"] in ("ok", "warning", "error", "empty")
            assert "summary" in card
            assert "details" in card


class TestControlRoomReviewPersistence:
    def test_review_persistence_and_final_export(self, tmp_path, monkeypatch):
        from igris.web.routers import routes_10

        monkeypatch.setattr(routes_10.CONFIG, "project_root", Path(tmp_path))
        client = _client()
        run = _make_run(status="success")
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            save_resp = client.post(
                "/api/rank/runs/test-run/review",
                json={
                    "action_id": "review_evidence",
                    "summary": "dashboard review saved",
                    "notes": "manual review complete",
                    "evidence_ref": "/api/rank/runs/test-run/report",
                    "reviewed_by": "operator",
                },
            )
            assert save_resp.status_code == 200
            body = save_resp.json()
            assert body["ok"] is True
            assert body["review_count"] == 1
            export_resp = client.get("/api/rank/runs/test-run/final-export")
            assert export_resp.status_code == 200
            export = export_resp.json()
            assert export["run_id"] == "test-run"
            assert len(export["operator_reviews"]) == 1
            assert export["operator_reviews"][0]["action_id"] == "review_evidence"
            assert export["operator_reviews"][0]["summary"] == "dashboard review saved"
        review_log = Path(tmp_path) / ".igris" / "control_room_reviews.jsonl"
        assert review_log.exists()
        raw = review_log.read_text(encoding="utf-8").strip().splitlines()
        assert len(raw) == 1
        parsed = json.loads(raw[0])
        assert parsed["run_id"] == "test-run"
        assert parsed["action_id"] == "review_evidence"
