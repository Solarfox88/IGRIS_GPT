"""Tests for the outcome router."""
from igris.core.outcome_router import decide_next_after_result


def test_success_returns_idle():
    result = {"success": True}
    rec = decide_next_after_result(result, "run pytest", ["run pytest"])
    assert rec["next_action"] == "idle"


def test_test_failure_returns_validation():
    result = {"success": False, "failure_type": "test_failed", "stderr": "1 failed"}
    rec = decide_next_after_result(result, "run pytest", ["run pytest"])
    assert rec["next_action"] == "validation"


def test_generic_error_calls_teacher():
    result = {"success": False, "failure_type": "command_error", "stderr": "error occurred"}
    rec = decide_next_after_result(result, "edit code", ["edit code"])
    assert rec["should_call_teacher"] is True


def test_saturated_family_shifts():
    history = ["run pytest"] * 5
    result = {"success": False, "failure_type": "command_error", "stderr": "error"}
    rec = decide_next_after_result(result, "run pytest", history, threshold=3)
    assert rec["next_action"] in ("shift_strategy", "teacher_review")
