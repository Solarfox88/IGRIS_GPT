"""Tests for #876 — Goal/Run Status Bridge module.

Verifies:
- All 16 (run, goal) pairs return expected combined_status
- All 16 pairs return valid next_action_recommendation
- bridge() is deterministic
- bridge_cycle() augments without modifying original
- normalize aliases work
- unknown inputs handled gracefully
- completed is ONLY for run=passed + goal=completed
- goal=completed + run!=passed → anomaly, never completed
- aggregate_bridge_cycles() produces correct distributions
"""
from __future__ import annotations

import pytest

from igris.agent.mission.status_bridge import (
    COMBINED_BLOCKED_GOAL_FAILED,
    COMBINED_BLOCKED_GOAL_PROGRESS,
    COMBINED_COMPLETED,
    COMBINED_GOAL_COMPLETE_RUN_BLOCKED,
    COMBINED_GOAL_COMPLETE_RUN_FAILED,
    COMBINED_HARD_FAILURE,
    COMBINED_INSUFFICIENT_CONTEXT,
    COMBINED_STATUSES,
    COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS,
    COMBINED_TECHNICAL_SUCCESS_GOAL_INCOMPLETE,
    GOAL_COMPLETED,
    GOAL_FAILED,
    GOAL_PARTIAL,
    GOAL_STATUSES,
    GOAL_UNKNOWN,
    NEXT_ACTIONS,
    NEXT_DIAGNOSE_FAILURE,
    NEXT_MARK_COMPLETE,
    NEXT_RECOVER_FROM_PARTIAL,
    NEXT_REQUEST_CONTEXT,
    NEXT_REVIEW_ANOMALY,
    NEXT_UNBLOCK_THEN_CONTINUE,
    RUN_BLOCKED,
    RUN_FAILED,
    RUN_PASSED,
    RUN_STATUSES,
    RUN_UNKNOWN,
    aggregate_bridge_cycles,
    bridge,
    bridge_cycle,
    _normalize_goal_status,
    _normalize_run_status,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _cycle(run: str, goal: str, cycle_id: str = "c1") -> dict:
    return {
        "cycle_id": cycle_id,
        "current_loop_decision": run,
        "mission_brain_decision": goal,
        "agreement": run == goal,
    }


# ---------------------------------------------------------------------------
# bridge() — all 16 pairs
# ---------------------------------------------------------------------------

class TestBridgeMapping:
    def test_passed_completed(self):
        r = bridge(RUN_PASSED, GOAL_COMPLETED)
        assert r["combined_status"] == COMBINED_COMPLETED
        assert r["next_action_recommendation"] == NEXT_MARK_COMPLETE

    def test_passed_partial(self):
        r = bridge(RUN_PASSED, GOAL_PARTIAL)
        assert r["combined_status"] == COMBINED_TECHNICAL_SUCCESS_GOAL_INCOMPLETE

    def test_passed_failed(self):
        r = bridge(RUN_PASSED, GOAL_FAILED)
        assert r["next_action_recommendation"] == NEXT_REVIEW_ANOMALY

    def test_passed_unknown(self):
        r = bridge(RUN_PASSED, GOAL_UNKNOWN)
        assert r["combined_status"] == COMBINED_INSUFFICIENT_CONTEXT

    def test_failed_completed(self):
        r = bridge(RUN_FAILED, GOAL_COMPLETED)
        assert r["combined_status"] == COMBINED_GOAL_COMPLETE_RUN_FAILED
        assert r["next_action_recommendation"] == NEXT_REVIEW_ANOMALY

    def test_failed_partial(self):
        r = bridge(RUN_FAILED, GOAL_PARTIAL)
        assert r["combined_status"] == COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS
        assert r["next_action_recommendation"] == NEXT_RECOVER_FROM_PARTIAL

    def test_failed_failed(self):
        r = bridge(RUN_FAILED, GOAL_FAILED)
        assert r["combined_status"] == COMBINED_HARD_FAILURE
        assert r["next_action_recommendation"] == NEXT_DIAGNOSE_FAILURE

    def test_failed_unknown(self):
        r = bridge(RUN_FAILED, GOAL_UNKNOWN)
        assert r["combined_status"] == COMBINED_INSUFFICIENT_CONTEXT

    def test_blocked_completed(self):
        r = bridge(RUN_BLOCKED, GOAL_COMPLETED)
        assert r["combined_status"] == COMBINED_GOAL_COMPLETE_RUN_BLOCKED
        assert r["next_action_recommendation"] == NEXT_REVIEW_ANOMALY

    def test_blocked_partial(self):
        r = bridge(RUN_BLOCKED, GOAL_PARTIAL)
        assert r["combined_status"] == COMBINED_BLOCKED_GOAL_PROGRESS
        assert r["next_action_recommendation"] == NEXT_UNBLOCK_THEN_CONTINUE

    def test_blocked_failed(self):
        r = bridge(RUN_BLOCKED, GOAL_FAILED)
        assert r["combined_status"] == COMBINED_BLOCKED_GOAL_FAILED

    def test_blocked_unknown(self):
        r = bridge(RUN_BLOCKED, GOAL_UNKNOWN)
        assert r["combined_status"] == COMBINED_INSUFFICIENT_CONTEXT

    def test_unknown_completed(self):
        r = bridge(RUN_UNKNOWN, GOAL_COMPLETED)
        assert r["combined_status"] == COMBINED_INSUFFICIENT_CONTEXT

    def test_unknown_partial(self):
        r = bridge(RUN_UNKNOWN, GOAL_PARTIAL)
        assert r["combined_status"] == COMBINED_INSUFFICIENT_CONTEXT

    def test_unknown_failed(self):
        r = bridge(RUN_UNKNOWN, GOAL_FAILED)
        assert r["combined_status"] == COMBINED_INSUFFICIENT_CONTEXT

    def test_unknown_unknown(self):
        r = bridge(RUN_UNKNOWN, GOAL_UNKNOWN)
        assert r["combined_status"] == COMBINED_INSUFFICIENT_CONTEXT
        assert r["next_action_recommendation"] == NEXT_REQUEST_CONTEXT


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------

class TestSafetyInvariants:
    @pytest.mark.parametrize("run", [RUN_FAILED, RUN_BLOCKED, RUN_UNKNOWN])
    def test_goal_completed_run_not_passed_never_combined_completed(self, run: str):
        r = bridge(run, GOAL_COMPLETED)
        assert r["combined_status"] != COMBINED_COMPLETED, (
            f"run={run}, goal=completed must NOT produce combined=completed; "
            f"got {r['combined_status']!r}"
        )

    def test_only_passed_completed_gives_combined_completed(self):
        """Exhaustive: the ONLY path to combined=completed is passed+completed."""
        for run in RUN_STATUSES:
            for goal in GOAL_STATUSES:
                r = bridge(run, goal)
                if r["combined_status"] == COMBINED_COMPLETED:
                    assert run == RUN_PASSED and goal == GOAL_COMPLETED, (
                        f"combined=completed found for run={run}, goal={goal} — INVARIANT VIOLATED"
                    )

    def test_all_pairs_return_valid_combined_status(self):
        for run in RUN_STATUSES:
            for goal in GOAL_STATUSES:
                r = bridge(run, goal)
                assert r["combined_status"] in COMBINED_STATUSES, (
                    f"run={run}, goal={goal}: unknown combined={r['combined_status']!r}"
                )

    def test_all_pairs_return_valid_next_action(self):
        for run in RUN_STATUSES:
            for goal in GOAL_STATUSES:
                r = bridge(run, goal)
                assert r["next_action_recommendation"] in NEXT_ACTIONS, (
                    f"run={run}, goal={goal}: unknown next={r['next_action_recommendation']!r}"
                )

    def test_bridge_is_deterministic(self):
        for run in RUN_STATUSES:
            for goal in GOAL_STATUSES:
                r1 = bridge(run, goal)
                r2 = bridge(run, goal)
                assert r1 == r2


# ---------------------------------------------------------------------------
# Graceful fallback for unknown/invalid inputs
# ---------------------------------------------------------------------------

class TestUnknownInputFallback:
    def test_none_run_status(self):
        r = bridge(None, GOAL_PARTIAL)
        assert r["combined_status"] == COMBINED_INSUFFICIENT_CONTEXT

    def test_none_goal_status(self):
        r = bridge(RUN_FAILED, None)
        assert r["combined_status"] == COMBINED_INSUFFICIENT_CONTEXT

    def test_garbage_run_status(self):
        r = bridge("xyz_garbage_999", GOAL_PARTIAL)
        assert r["combined_status"] == COMBINED_INSUFFICIENT_CONTEXT

    def test_garbage_goal_status(self):
        # garbage goal_status is normalized to GOAL_UNKNOWN → failed+unknown → insufficient_context
        r = bridge(RUN_FAILED, "xyz_garbage_999")
        assert r["combined_status"] == COMBINED_INSUFFICIENT_CONTEXT

    def test_empty_string_inputs(self):
        r = bridge("", "")
        assert r["combined_status"] == COMBINED_INSUFFICIENT_CONTEXT


# ---------------------------------------------------------------------------
# _normalize_run_status / _normalize_goal_status
# ---------------------------------------------------------------------------

class TestNormalization:
    def test_run_alias_success(self):
        assert _normalize_run_status("success") == RUN_PASSED

    def test_run_alias_completed(self):
        assert _normalize_run_status("completed") == RUN_PASSED

    def test_run_alias_fail(self):
        assert _normalize_run_status("fail") == RUN_FAILED

    def test_run_alias_block(self):
        assert _normalize_run_status("block") == RUN_BLOCKED

    def test_run_none_returns_unknown(self):
        assert _normalize_run_status(None) == RUN_UNKNOWN

    def test_goal_alias_complete(self):
        assert _normalize_goal_status("complete") == GOAL_COMPLETED

    def test_goal_alias_done(self):
        assert _normalize_goal_status("done") == GOAL_COMPLETED

    def test_goal_alias_in_progress(self):
        assert _normalize_goal_status("in_progress") == GOAL_PARTIAL

    def test_goal_none_returns_unknown(self):
        assert _normalize_goal_status(None) == GOAL_UNKNOWN


# ---------------------------------------------------------------------------
# bridge_cycle()
# ---------------------------------------------------------------------------

class TestBridgeCycle:
    def test_adds_combined_status_field(self):
        c = _cycle(RUN_FAILED, GOAL_PARTIAL)
        result = bridge_cycle(c)
        assert "combined_status" in result
        assert result["combined_status"] == COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS

    def test_adds_next_action_field(self):
        c = _cycle(RUN_FAILED, GOAL_PARTIAL)
        result = bridge_cycle(c)
        assert "next_action_recommendation" in result
        assert result["next_action_recommendation"] == NEXT_RECOVER_FROM_PARTIAL

    def test_does_not_modify_original(self):
        c = _cycle(RUN_FAILED, GOAL_PARTIAL)
        original_keys = set(c.keys())
        _ = bridge_cycle(c)
        assert set(c.keys()) == original_keys

    def test_preserves_original_fields(self):
        c = _cycle(RUN_PASSED, GOAL_COMPLETED, "cycle_42")
        result = bridge_cycle(c)
        assert result["cycle_id"] == "cycle_42"
        assert result["current_loop_decision"] == RUN_PASSED
        assert result["mission_brain_decision"] == GOAL_COMPLETED

    def test_bridge_run_status_normalized(self):
        c = _cycle(RUN_BLOCKED, GOAL_PARTIAL)
        result = bridge_cycle(c)
        assert result["bridge_run_status"] == RUN_BLOCKED

    def test_bridge_goal_status_normalized(self):
        c = _cycle(RUN_FAILED, GOAL_PARTIAL)
        result = bridge_cycle(c)
        assert result["bridge_goal_status"] == GOAL_PARTIAL


# ---------------------------------------------------------------------------
# aggregate_bridge_cycles()
# ---------------------------------------------------------------------------

class TestAggregateBridgeCycles:
    def _build_batch(self):
        """17 blocked+partial, 3 blocked+failed (mirrors #868 dataset)."""
        cycles = (
            [_cycle(RUN_BLOCKED, GOAL_PARTIAL, f"blocked_partial_{i}") for i in range(17)]
            + [_cycle(RUN_BLOCKED, GOAL_FAILED, f"blocked_failed_{i}") for i in range(3)]
        )
        assert len(cycles) == 20
        return cycles

    def test_returns_dict(self):
        assert isinstance(aggregate_bridge_cycles(self._build_batch()), dict)

    def test_total_cycles(self):
        r = aggregate_bridge_cycles(self._build_batch())
        assert r["total_cycles"] == 20

    def test_blocked_with_goal_progress_count(self):
        r = aggregate_bridge_cycles(self._build_batch())
        assert r["blocked_with_goal_progress_count"] == 17

    def test_hard_failure_count_zero(self):
        r = aggregate_bridge_cycles(self._build_batch())
        assert r["hard_failure_count"] == 0

    def test_completed_count_zero(self):
        r = aggregate_bridge_cycles(self._build_batch())
        assert r["completed_count"] == 0

    def test_distribution_sums_to_total(self):
        r = aggregate_bridge_cycles(self._build_batch())
        dist_sum = sum(r["combined_status_distribution"].values())
        assert dist_sum == r["total_cycles"]

    def test_empty_cycles(self):
        r = aggregate_bridge_cycles([])
        assert r["total_cycles"] == 0
        assert r["completed_count"] == 0
        assert r["hard_failure_count"] == 0

    def test_all_completed(self):
        cycles = [_cycle(RUN_PASSED, GOAL_COMPLETED, f"c{i}") for i in range(5)]
        r = aggregate_bridge_cycles(cycles)
        assert r["completed_count"] == 5
        assert r["hard_failure_count"] == 0

    def test_next_action_distribution_present(self):
        r = aggregate_bridge_cycles(self._build_batch())
        assert "next_action_recommendation_distribution" in r
        assert sum(r["next_action_recommendation_distribution"].values()) == 20
