"""Tests for pre-run dependency validator in SelfRepairSupervisor (#615).

Validates:
- _parse_issue_number() helper
- RankSupervisorConfig.from_dict() extracts issue_number from data or goal
- _run_preflight_phase() blocks when DependencyChecker returns unsatisfied deps
- _run_preflight_phase() passes dep check when deps are satisfied
- Dep check error is non-fatal (best-effort)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from igris.core.self_repair_supervisor import (
    RankSupervisorConfig,
    SelfRepairSupervisor,
    SupervisorRun,
    _parse_issue_number,
)


# ---------------------------------------------------------------------------
# _parse_issue_number
# ---------------------------------------------------------------------------

class TestParseIssueNumber:
    def test_explicit_int(self):
        assert _parse_issue_number(614, "") == 614

    def test_explicit_string_int(self):
        assert _parse_issue_number("819", "") == 819

    def test_explicit_zero_falls_back_to_goal(self):
        assert _parse_issue_number(0, "Fix #522: outcome quality tracker") == 522

    def test_explicit_none_falls_back_to_goal(self):
        assert _parse_issue_number(None, "Implement #615 — dep validator") == 615

    def test_goal_first_hash(self):
        assert _parse_issue_number(0, "Resolve #100 and #200") == 100

    def test_no_issue_returns_zero(self):
        assert _parse_issue_number(0, "No issue reference here") == 0

    def test_negative_explicit_falls_back_to_goal(self):
        assert _parse_issue_number(-5, "Fix #42") == 42

    def test_empty_goal_returns_zero(self):
        assert _parse_issue_number(0, "") == 0


# ---------------------------------------------------------------------------
# RankSupervisorConfig.from_dict — issue_number propagation
# ---------------------------------------------------------------------------

class TestRankSupervisorConfigIssueNumber:
    def test_explicit_issue_number_in_data(self):
        config = RankSupervisorConfig.from_dict({"goal": "some task", "issue_number": 614})
        assert config.issue_number == 614

    def test_issue_number_parsed_from_goal(self):
        config = RankSupervisorConfig.from_dict({"goal": "Fix #522: outcome quality tracker"})
        assert config.issue_number == 522

    def test_no_issue_number_is_zero(self):
        config = RankSupervisorConfig.from_dict({"goal": "No issue reference"})
        assert config.issue_number == 0

    def test_explicit_overrides_goal(self):
        config = RankSupervisorConfig.from_dict({"goal": "Fix #522", "issue_number": 614})
        assert config.issue_number == 614


# ---------------------------------------------------------------------------
# _run_preflight_phase — dependency check integration
# ---------------------------------------------------------------------------

def _make_supervisor(tmp_path):
    sup = SelfRepairSupervisor(project_root=str(tmp_path))
    ok_result = MagicMock()
    ok_result.success = True
    ok_result.output = ""
    sup.backend = MagicMock()
    sup.backend.git_status.return_value = ok_result
    sup.backend.git_log_head.return_value = ok_result
    sup.backend.api_helper_is_configured.return_value = False
    return sup


def _make_run():
    return SupervisorRun(run_id="test-run", rank_id="test")


class TestPreflightDependencyCheck:
    def test_no_issue_number_skips_dep_check(self, tmp_path):
        """When issue_number=0, no dependency_check event is logged."""
        sup = _make_supervisor(tmp_path)
        config = RankSupervisorConfig(
            goal="some task",
            rank_id="test",
            dry_run=True,
            issue_number=0,
        )
        run = _make_run()

        with patch("igris.core.dependency_checker.DependencyChecker.check",
                   return_value=(False, [999])) as mock_check, \
             patch.object(sup, "_cancel_if_requested", return_value=None):
            # If it were called, it'd block. Since issue_number=0, it should not be called.
            try:
                sup._run_preflight_phase(run, config)
            except Exception:
                pass
            # Verify no dep check event was logged
            dep_events = [e for e in run.events if e.phase == "dependency_check"]
            assert dep_events == [], "dep check should not run when issue_number=0"
            mock_check.assert_not_called()

    def test_dep_unsatisfied_blocks_run(self, tmp_path):
        """Unsatisfied deps must block the run (ctx=None, blocked event)."""
        sup = _make_supervisor(tmp_path)
        config = RankSupervisorConfig(
            goal="Fix #500",
            rank_id="test",
            dry_run=True,
            issue_number=500,
        )
        run = _make_run()

        with patch("igris.core.dependency_checker.DependencyChecker.check",
                   return_value=(False, [614, 522])), \
             patch.object(sup, "_cancel_if_requested", return_value=None):
            result, ctx = sup._run_preflight_phase(run, config)

        assert ctx is None, "ctx must be None when blocked by dep check"
        dep_events = [e for e in run.events if e.phase == "dependency_check"]
        assert dep_events, "dependency_check event must be logged"
        assert dep_events[0].status == "blocked"

    def test_dep_satisfied_logs_satisfied_event(self, tmp_path):
        """Satisfied deps must log a 'satisfied' event and not block on dep check."""
        sup = _make_supervisor(tmp_path)
        config = RankSupervisorConfig(
            goal="Fix #614",
            rank_id="test",
            dry_run=True,
            issue_number=614,
        )
        run = _make_run()

        with patch("igris.core.dependency_checker.DependencyChecker.check",
                   return_value=(True, [])), \
             patch.object(sup, "_cancel_if_requested", return_value=None):
            # Preflight will proceed past dep check but may block elsewhere — that's fine
            try:
                result, ctx = sup._run_preflight_phase(run, config)
            except Exception:
                pass

        dep_events = [e for e in run.events if e.phase == "dependency_check"]
        assert dep_events, "dependency_check event must be logged even when satisfied"
        assert dep_events[0].status == "satisfied"

    def test_dep_check_error_is_non_fatal(self, tmp_path):
        """If DependencyChecker raises, run continues (error logged, not blocked)."""
        sup = _make_supervisor(tmp_path)
        config = RankSupervisorConfig(
            goal="Fix #614",
            rank_id="test",
            dry_run=True,
            issue_number=614,
        )
        run = _make_run()

        with patch("igris.core.dependency_checker.DependencyChecker.check",
                   side_effect=RuntimeError("gh CLI unavailable")), \
             patch.object(sup, "_cancel_if_requested", return_value=None):
            try:
                result, ctx = sup._run_preflight_phase(run, config)
            except Exception:
                pytest.fail("Dep check error should be swallowed, not propagated")

        dep_events = [e for e in run.events if e.phase == "dependency_check"]
        assert dep_events, "dep check error event should be logged"
        assert dep_events[0].status == "error"
        # Must NOT be blocked specifically due to dep check
        dep_event = dep_events[0]
        assert dep_event.status == "error", "dep check error must log 'error', not 'blocked'"
