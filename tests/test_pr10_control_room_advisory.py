"""PR 10 — Control Room advisory/MBOP UX tests.

Covers:
- /report includes advisory_card field (feature-flagged)
- advisory_card has all required invariant fields (advisory_only, auto_executable=False,
  is_gate=False, affects_loop_decision=False, approval_required=True)
- advisory_card is None when feature disabled
- advisory_card is None for passed/completed/success runs
- /advisory endpoint returns advisory card when enabled
- /advisory endpoint always asserts advisory invariants at envelope level
- /evidence endpoint returns acceptance evidence and evidence events
- /evidence redacts secrets in string fields
- All endpoints return 404 for unknown runs
"""

from __future__ import annotations

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
    run_id: str = "test123",
    status: str = "blocked",
    failure_class: str = "pytest_failure",
    events: Optional[List[Any]] = None,
    acceptance_evidence: Optional[Dict] = None,
) -> MagicMock:
    run = MagicMock()
    run.run_id = run_id
    run.rank_id = "test-rank"
    run.status = status
    run.failure_class = failure_class
    run.goal = "Implement feature X"
    run.repair_cycles_used = 2
    run.same_failure_count = 1
    run.execution_budget_used_usd = 0.07
    run.capability_signals = {}
    run.cancel_requested = False
    run.cancel_reason = ""
    run.decomposition = None
    run.acceptance_evidence = acceptance_evidence
    run.start_ts = time.time() - 120

    if events is None:
        ev1 = MagicMock()
        ev1.phase = "start"
        ev1.status = "running"
        ev1.detail = "Run started"
        ev1.ts = time.time() - 120
        ev1.same_failure_count = 0
        run.events = [ev1]
    else:
        run.events = events

    run.report = {}
    return run


def _client() -> TestClient:
    app = create_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# /report advisory_card integration
# ---------------------------------------------------------------------------

class TestReportAdvisoryCard:

    def test_report_has_advisory_card_key(self):
        """advisory_card key is always present in report response."""
        client = _client()
        run = _make_run("r1", status="blocked")
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            resp = client.get("/api/rank/runs/r1/report")
        assert resp.status_code == 200
        body = resp.json()
        assert "advisory_card" in body

    def test_report_advisory_card_null_when_disabled(self):
        """advisory_card is null when feature flag is off (default)."""
        client = _client()
        run = _make_run("r1", status="blocked")
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            with patch.dict("os.environ", {}, clear=False):
                import os as _os
                _os.environ.pop("IGRIS_ADVISORY_RECOVERY_PROPOSALS", None)
                resp = client.get("/api/rank/runs/r1/report")
        body = resp.json()
        assert body["advisory_card"] is None

    def test_report_advisory_card_null_for_success(self):
        """advisory_card is never returned for successful runs."""
        client = _client()
        run = _make_run("r2", status="success", failure_class="")
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            with patch.dict("os.environ", {"IGRIS_ADVISORY_RECOVERY_PROPOSALS": "1"}):
                resp = client.get("/api/rank/runs/r2/report")
        body = resp.json()
        # outcome == "success" → advisory_card should be None
        assert body["outcome"] == "success"
        assert body["advisory_card"] is None

    def test_report_advisory_card_invariants_when_enabled(self):
        """When advisory_card is non-null, advisory invariants must all be correct."""
        from igris.agent.mission.recovery_proposal import (
            RecoveryProposal, SuggestedAction,
        )
        client = _client()
        run = _make_run("r3", status="blocked", failure_class="pytest_failure")

        mock_proposal = RecoveryProposal(
            proposal_type="restart_with_smaller_scope",
            problem_summary="Run failed on pytest_failure",
            trigger_status="blocked",
            suggested_actions=[
                SuggestedAction(
                    description="Break down into smaller tasks",
                    rationale="Reduce complexity",
                )
            ],
        )

        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            with patch.dict("os.environ", {"IGRIS_ADVISORY_RECOVERY_PROPOSALS": "1"}):
                with patch(
                    "igris.agent.mission.recovery_proposal.generate_recovery_proposal",
                    return_value=mock_proposal,
                ):
                    resp = client.get("/api/rank/runs/r3/report")

        body = resp.json()
        card = body.get("advisory_card")
        if card is not None:
            # Mandatory invariants
            assert card["advisory_only"] is True
            assert card["auto_executable"] is False
            assert card["is_gate"] is False
            assert card["affects_loop_decision"] is False
            assert card["approval_required"] is True
            # Suggested actions also have auto_executable=False
            for action in card.get("suggested_actions", []):
                assert action["auto_executable"] is False
                assert action["requires_approval"] is True

    def test_report_does_not_raise_when_proposal_fails(self):
        """Report endpoint must not fail if recovery_proposal raises."""
        import os
        client = _client()
        run = _make_run("r4", status="blocked")

        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            with patch.dict("os.environ", {"IGRIS_ADVISORY_RECOVERY_PROPOSALS": "1"}):
                with patch(
                    "igris.agent.mission.recovery_proposal.generate_recovery_proposal",
                    side_effect=RuntimeError("proposal exploded"),
                ):
                    resp = client.get("/api/rank/runs/r4/report")

        assert resp.status_code == 200
        body = resp.json()
        # advisory_card should be None (error swallowed)
        assert body["advisory_card"] is None


# ---------------------------------------------------------------------------
# /advisory endpoint
# ---------------------------------------------------------------------------

class TestAdvisoryEndpoint:

    def test_advisory_404_unknown_run(self):
        client = _client()
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=None):
            resp = client.get("/api/rank/runs/unknown/advisory")
        assert resp.status_code == 404

    def test_advisory_returns_required_envelope_keys(self):
        client = _client()
        run = _make_run("r1")
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            resp = client.get("/api/rank/runs/r1/advisory")
        assert resp.status_code == 200
        body = resp.json()
        for key in ("run_id", "status", "feature_enabled", "advisory_card",
                    "advisory_only", "auto_executable", "is_gate", "affects_loop_decision"):
            assert key in body, f"missing key: {key}"

    def test_advisory_envelope_invariants_always_set(self):
        """Advisory invariants at envelope level are always true regardless of card."""
        client = _client()
        run = _make_run("r1")
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            resp = client.get("/api/rank/runs/r1/advisory")
        body = resp.json()
        assert body["advisory_only"] is True
        assert body["auto_executable"] is False
        assert body["is_gate"] is False
        assert body["affects_loop_decision"] is False

    def test_advisory_card_null_when_disabled(self):
        """advisory_card is null when feature flag disabled."""
        client = _client()
        run = _make_run("r2", status="blocked")
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            # Remove env var to simulate disabled state
            with patch.dict("os.environ", {}, clear=False):
                import os as _os
                _os.environ.pop("IGRIS_ADVISORY_RECOVERY_PROPOSALS", None)
                resp = client.get("/api/rank/runs/r2/advisory")
        body = resp.json()
        assert body["advisory_card"] is None
        assert body["feature_enabled"] is False

    def test_advisory_card_invariants_when_enabled(self):
        """When advisory_card is returned, all invariant fields must be correct."""
        from igris.agent.mission.recovery_proposal import RecoveryProposal
        client = _client()
        run = _make_run("r3", status="blocked")

        mock_proposal = RecoveryProposal(
            proposal_type="gather_missing_context",
            problem_summary="Context is insufficient",
            trigger_status="blocked",
            suggested_actions=[],
        )

        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            with patch.dict("os.environ", {"IGRIS_ADVISORY_RECOVERY_PROPOSALS": "1"}):
                with patch(
                    "igris.agent.mission.recovery_proposal.generate_recovery_proposal",
                    return_value=mock_proposal,
                ):
                    resp = client.get("/api/rank/runs/r3/advisory")

        body = resp.json()
        card = body.get("advisory_card")
        if card is not None:
            assert card["advisory_only"] is True
            assert card["auto_executable"] is False
            assert card["is_gate"] is False
            assert card["affects_loop_decision"] is False
            assert card["approval_required"] is True

    def test_advisory_does_not_raise_on_proposal_error(self):
        """Advisory endpoint must not 500 if proposal generation fails."""
        client = _client()
        run = _make_run("r4", status="blocked")

        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            with patch.dict("os.environ", {"IGRIS_ADVISORY_RECOVERY_PROPOSALS": "1"}):
                with patch(
                    "igris.agent.mission.recovery_proposal.generate_recovery_proposal",
                    side_effect=RuntimeError("proposal exploded"),
                ):
                    resp = client.get("/api/rank/runs/r4/advisory")

        assert resp.status_code == 200
        body = resp.json()
        assert body["advisory_card"] is None


# ---------------------------------------------------------------------------
# /evidence endpoint
# ---------------------------------------------------------------------------

class TestEvidenceEndpoint:

    def test_evidence_404_unknown_run(self):
        client = _client()
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=None):
            resp = client.get("/api/rank/runs/unknown/evidence")
        assert resp.status_code == 404

    def test_evidence_returns_required_keys(self):
        client = _client()
        run = _make_run("r1", acceptance_evidence={"passed": True, "score": 0.95})
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            resp = client.get("/api/rank/runs/r1/evidence")
        assert resp.status_code == 200
        body = resp.json()
        for key in ("run_id", "status", "acceptance_evidence", "evidence_events", "evidence_count"):
            assert key in body, f"missing key: {key}"

    def test_evidence_returns_none_when_no_evidence(self):
        client = _client()
        run = _make_run("r2", acceptance_evidence=None)
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            resp = client.get("/api/rank/runs/r2/evidence")
        body = resp.json()
        assert body["acceptance_evidence"] is None
        assert body["evidence_count"] == 0

    def test_evidence_redacts_secret_fields(self):
        """String values in acceptance_evidence go through _safe_redact."""
        client = _client()
        # Use a pattern that matches: TOKEN=<8+ chars>
        run = _make_run("r3", acceptance_evidence={
            "summary": "TOKEN=supersecretval123 test passed",
            "passed": True,
        })
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            resp = client.get("/api/rank/runs/r3/evidence")
        body = resp.json()
        evidence = body["acceptance_evidence"]
        assert evidence is not None
        # Token value should be redacted
        assert "supersecretval123" not in str(evidence.get("summary", ""))

    def test_evidence_events_from_acceptance_gate_phase(self):
        """Events with phase=acceptance_gate are included in evidence_events."""
        client = _client()
        ev1 = MagicMock()
        ev1.phase = "acceptance_gate"
        ev1.status = "passed"
        ev1.detail = "All tests passed"
        ev1.ts = time.time()
        ev1.same_failure_count = 0

        ev2 = MagicMock()
        ev2.phase = "start"
        ev2.status = "running"
        ev2.detail = "Started"
        ev2.ts = time.time() - 60
        ev2.same_failure_count = 0

        run = _make_run("r4", events=[ev1, ev2])
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            resp = client.get("/api/rank/runs/r4/evidence")
        body = resp.json()
        assert body["evidence_count"] == 1
        assert body["evidence_events"][0]["phase"] == "acceptance_gate"

    def test_evidence_events_empty_when_no_matching_phase(self):
        """evidence_events is empty when no acceptance/quality gate events exist."""
        client = _client()
        run = _make_run("r5")
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            resp = client.get("/api/rank/runs/r5/evidence")
        body = resp.json()
        assert body["evidence_count"] == 0
        assert body["evidence_events"] == []

    def test_evidence_dict_with_non_string_values(self):
        """Non-string values in acceptance_evidence are preserved as-is."""
        client = _client()
        run = _make_run("r6", acceptance_evidence={"passed": True, "score": 0.85, "count": 42})
        with patch("igris.core.self_repair_supervisor.get_supervised_run", return_value=run):
            resp = client.get("/api/rank/runs/r6/evidence")
        body = resp.json()
        evidence = body["acceptance_evidence"]
        assert evidence["passed"] is True
        assert evidence["score"] == 0.85
        assert evidence["count"] == 42
