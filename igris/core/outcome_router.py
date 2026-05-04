"""
Outcome routing logic.

This module defines heuristics for deciding what action should be taken
next after a task has been executed.  It inspects the result of the
execution, the task metadata, and recent history to propose a next
action such as running tests, requesting a teacher remediation or
switching strategy.

The design follows the MVP philosophy: decisions are simple and
deterministic, but the structure allows future expansion into more
sophisticated reasoning.
"""

from __future__ import annotations

from typing import Iterable, Optional, Dict, Any

from igris.core import anti_loop


def decide_next_after_result(
    result: Dict[str, Any], task_description: str, history: Iterable[str], threshold: int = 3
) -> Dict[str, Any]:
    """Decide the next action after executing a task.

    :param result: A dictionary describing the outcome of the task.  It may
      include keys such as ``success`` (bool), ``failure_type`` (str),
      ``stderr`` (str) and ``stdout`` (str).  The exact schema is
      intentionally loose to accommodate future extensions.
    :param task_description: The description of the task that was executed.
    :param history: The list of previous task descriptions (including the
      current one).
    :param threshold: The saturation threshold for anti‑loop heuristics.
    :returns: A dictionary containing the recommended next action and
      rationale.
    """
    success = result.get("success", False)
    failure_type = result.get("failure_type")
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    # Start with a neutral recommendation
    recommendation: Dict[str, Any] = {
        "next_action": None,
        "reason": None,
        "recommended_family": None,
        "should_call_teacher": False,
        "should_run_tests": False,
        "should_block_task": False,
    }
    # If the task succeeded, simply move on
    if success:
        recommendation["next_action"] = "idle"
        recommendation["reason"] = "Task completed successfully."
        return recommendation
    # If the failure type indicates a test failure or the stderr mentions failed tests
    if failure_type == "test_failed" or "failed" in stderr.lower():
        recommendation["next_action"] = "validation"
        recommendation["reason"] = "Tests failed; a validation/remediation task is required."
        recommendation["should_run_tests"] = True
        return recommendation
    # If an error occurred (generic)
    if failure_type == "command_error" or stderr:
        # Check if current family is saturated and recommend a shift
        current_family = anti_loop.classify_task_family(task_description)
        required_shift = anti_loop.required_strategy_shift_family(current_family, history, threshold=threshold)
        if required_shift:
            recommendation["next_action"] = "shift_strategy"
            recommendation["recommended_family"] = required_shift
            recommendation["reason"] = (
                f"Current family '{current_family}' is saturated or error prone; shifting to '{required_shift}'."
            )
            recommendation["should_call_teacher"] = True
        else:
            recommendation["next_action"] = "teacher_review"
            recommendation["reason"] = "Error encountered; teacher intervention recommended."
            recommendation["should_call_teacher"] = True
        return recommendation
    # Default: call teacher
    recommendation["next_action"] = "teacher_review"
    recommendation["reason"] = "Unable to determine next step; deferring to teacher."
    recommendation["should_call_teacher"] = True
    return recommendation


def route_outcome(report: Dict[str, Any], task_description: str = "",
                  history: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Route an execution report outcome and return recommendation.

    Wraps ``decide_next_after_result`` with report-specific fields and adds
    ``report_id`` to the returned recommendation.
    """
    result = {
        "success": report.get("success", False),
        "failure_type": report.get("failure_type"),
        "stdout": report.get("stdout_truncated", ""),
        "stderr": report.get("stderr_truncated", ""),
    }
    recommendation = decide_next_after_result(
        result, task_description, list(history or []),
    )
    recommendation["report_id"] = report.get("report_id")
    return recommendation