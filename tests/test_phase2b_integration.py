"""Integration tests for Phase 2B — end-to-end flows.

Verifies that Agent contracts, WorkSession, and DeliveryWorkflow interact
correctly across boundaries. All LLM and subprocess calls are mocked.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from igris.core.agent_contracts import AgentCoordinator, validate_agent_action
from igris.core.agent_registry import ESCALATION_PATH, TOOL_PERMISSIONS
from igris.core.work_session import DeliveryReport, WorkPhase, WorkSession
from igris.core.delivery_workflow import CIStatus, DeliveryWorkflow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_delivery_report(ws: WorkSession) -> DeliveryReport:
    return DeliveryReport(
        work_session_id=ws.session_id,
        goal=ws.goal,
        files_modified=["igris/core/foo.py"],
        diff_summary="+ def foo(): ...",
        test_output="1 passed",
        ci_status="green",
        pr_url="https://github.com/Solarfox88/IGRIS_GPT/pull/999",
        pr_number=999,
        healthcheck_url="",
        residual_risks=[],
        rollback_available=True,
        run_id=f"run-{uuid.uuid4().hex[:8]}",
        last_failure_class="",
        repair_cycles_used=1,
        capability_signals={"test_pass_rate": 1.0},
    )


# ---------------------------------------------------------------------------
# 1. Contract violation → lesson in graph → escalation after repeat
# ---------------------------------------------------------------------------

class TestContractViolationToGraph:
    """Full cycle: violation → lesson written → repeat triggers escalation."""

    def test_violation_lesson_and_escalation(self, tmp_path):
        coord = AgentCoordinator(str(tmp_path))
        with patch("igris.core.memory_graph.MemoryGraph") as mg_cls:
            mg = mg_cls.return_value
            # First violation
            mg.query_lessons_for_failure_class.return_value = [
                {"content": {"role": "cost_guardian", "action_type": "edit_file"}},
                {"content": {"role": "cost_guardian", "action_type": "edit_file"}},
            ]
            coord._mg = mg  # inject mock directly
            allowed, reason = coord.check_and_record("cost_guardian", "edit_file", "refactor cost module")

        assert not allowed
        assert "cost_guardian" in reason
        # lesson written
        assert any(c.args[0] == "lesson" for c in mg.add_node.call_args_list)
        # escalation triggered (repeat_count >= 2)
        assert any(c.args[0] == "run_event" for c in mg.add_node.call_args_list)

    def test_unknown_role_fails_open(self, tmp_path):
        coord = AgentCoordinator(str(tmp_path))
        allowed, reason = coord.check_and_record("nonexistent_role", "edit_file", "goal")
        assert allowed  # fail-open
        assert reason == ""

    def test_graph_failure_fails_open(self, tmp_path):
        coord = AgentCoordinator(str(tmp_path))
        with patch("igris.core.memory_graph.MemoryGraph", side_effect=RuntimeError("db error")):
            coord._mg = None  # force re-init
            allowed, reason = coord.check_and_record("cost_guardian", "edit_file", "goal")
        assert not allowed  # violation still detected
        # but no exception raised — fail-open on graph side


# ---------------------------------------------------------------------------
# 2. WorkSession full lifecycle
# ---------------------------------------------------------------------------

class TestWorkSessionLifecycle:
    """WorkSession advances through all 8 phases, delivers, remembers."""

    def test_full_cycle_to_remember(self, tmp_path):
        ws = WorkSession.create(goal="implement /api/voice endpoint")

        for phase in [WorkPhase.UNDERSTAND, WorkPhase.PLAN, WorkPhase.ACT,
                      WorkPhase.OBSERVE, WorkPhase.FIX, WorkPhase.VERIFY]:
            ws.advance_phase(phase, outcome="success")

        ws.advance_phase(WorkPhase.DELIVER)
        report = _make_delivery_report(ws)
        ws.complete_deliver(report)

        assert ws.status == "delivered"
        assert ws.delivery_report is not None
        assert ws.delivery_report.ci_status == "green"

        # Remember phase writes to graph
        with patch("igris.core.memory_graph.MemoryGraph") as mg_cls:
            mg = mg_cls.return_value
            ws.advance_phase(WorkPhase.REMEMBER)
            ws.remember(str(tmp_path))

        # Should have written lesson + world_state_snapshot
        node_types = [c.args[0] for c in mg.add_node.call_args_list]
        assert "lesson" in node_types
        assert "world_state_snapshot" in node_types

    def test_pr_review_request_fields_match_delivery_report(self):
        ws = WorkSession.create(goal="add tests")
        report = _make_delivery_report(ws)
        ws.complete_deliver(report)

        prr = ws.to_pr_review_request()
        assert prr["pr_number"] == 999
        assert prr["ci_passed"] is True
        assert prr["run_id"] == report.run_id
        assert prr["repair_cycles_used"] == 1
        assert prr["capability_signals"] == {"test_pass_rate": 1.0}


# ---------------------------------------------------------------------------
# 3. DeliveryWorkflow — CI green path
# ---------------------------------------------------------------------------

class TestDeliveryWorkflowCIGreen:

    def test_ci_green_returns_true_and_writes_lesson(self, tmp_path):
        wf = DeliveryWorkflow(str(tmp_path))
        green_checks = json.dumps([
            {"name": "test", "status": "completed", "conclusion": "success"}
        ])
        with patch("subprocess.run") as mock_run, \
             patch("igris.core.memory_graph.MemoryGraph") as mg_cls:
            mock_run.return_value = MagicMock(returncode=0, stdout=green_checks)
            mg = mg_cls.return_value
            result = wf.fix_ci_loop(pr_number=999, max_attempts=1)

        assert result is True
        assert any(c.args[0] == "lesson" for c in mg.add_node.call_args_list)

    def test_ci_timeout_returns_false(self, tmp_path):
        wf = DeliveryWorkflow(str(tmp_path))
        with patch("subprocess.run") as mock_run, patch("time.sleep"):
            mock_run.return_value = MagicMock(returncode=0, stdout="[]")
            status = wf.wait_for_ci(999, timeout=1, poll=1)
        assert status.status == "timeout"


# ---------------------------------------------------------------------------
# 4. Contract → WorkSession → DeliveryWorkflow chain
# ---------------------------------------------------------------------------

class TestFullPhase2BChain:
    """Simulate the full Phase 2B chain in one test."""

    def test_contract_check_then_worksession_deliver(self, tmp_path):
        # Step 1: validate action (passes for backend_coder)
        ok, _ = validate_agent_action("backend_coder", "edit_file")
        assert ok

        # Step 2: create WorkSession and advance to deliver
        ws = WorkSession.create(goal="fix memory leak in goap_planner")
        ws.advance_phase(WorkPhase.UNDERSTAND)
        ws.advance_phase(WorkPhase.ACT, outcome="success")
        ws.advance_phase(WorkPhase.VERIFY, outcome="success")
        ws.advance_phase(WorkPhase.DELIVER)
        report = _make_delivery_report(ws)
        ws.complete_deliver(report)

        # Step 3: DeliveryWorkflow merges the PR
        wf = DeliveryWorkflow(str(tmp_path))
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            merged = wf.merge_pr(999)
        assert merged is True

        # Step 4: unsaturate family after successful merge
        with patch("igris.core.memory_graph.MemoryGraph") as mg_cls:
            wf.verify_and_unsaturate("goap_planner")
            mg_cls.return_value.unsaturate_family.assert_called_once_with("goap_planner")

        # Step 5: remember to graph
        with patch("igris.core.memory_graph.MemoryGraph") as mg_cls:
            ws.advance_phase(WorkPhase.REMEMBER)
            ws.remember(str(tmp_path))
        node_types = [c.args[0] for c in mg_cls.return_value.add_node.call_args_list]
        assert "lesson" in node_types

    def test_escalation_path_covers_all_roles(self):
        """All roles with violations have an escalation path defined."""
        for role in TOOL_PERMISSIONS:
            assert role in ESCALATION_PATH, f"Missing escalation path for role: {role}"
