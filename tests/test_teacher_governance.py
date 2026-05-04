"""Tests for teacher governance improvements."""
from igris.core.teacher import (
    build_teacher_payload,
    validate_teacher_assignment,
    propose_remediation_task,
)


def test_teacher_rejects_saturated_without_differentiator():
    history = ["run pytest", "run pytest", "run pytest"]
    assignment = {
        "selected_family": "testing",
        "differentiator": None,
        "success_criteria": ["tests pass"],
    }
    result = validate_teacher_assignment(assignment, history, threshold=3)
    assert result["valid"] is False
    assert "saturated" in result["reason"]


def test_teacher_accepts_saturated_with_differentiator():
    history = ["run pytest", "run pytest", "run pytest"]
    assignment = {
        "selected_family": "testing",
        "differentiator": "Focus specifically on integration tests for the A2A module",
        "success_criteria": ["a2a integration tests pass"],
    }
    result = validate_teacher_assignment(assignment, history, threshold=3)
    assert result["valid"] is True


def test_payload_contains_saturated_families():
    tasks = ["run pytest", "run pytest", "run pytest", "write code"]
    payload = build_teacher_payload(tasks, threshold=3)
    assert "testing" in payload["saturated_families"]
    assert payload["required_strategy_shift"] is not None or payload["current_family"] is not None


def test_payload_contains_policy():
    tasks = ["run pytest"]
    payload = build_teacher_payload(tasks)
    assert "policy" in payload
    assert len(payload["policy"]) > 0


def test_remediation_changes_family():
    payload = {
        "saturated_families": ["testing"],
        "current_family": "testing",
        "required_strategy_shift": "editing",
    }
    remediation = propose_remediation_task(payload)
    assert remediation.get("family") == "editing" or remediation.get("selected_family") == "editing"
    assert "switch" in remediation["task_description"].lower() or "shift" in remediation["task_description"].lower()


def test_assignment_requires_success_criteria():
    assignment = {
        "selected_family": "editing",
        "differentiator": "something",
        "success_criteria": [],
    }
    result = validate_teacher_assignment(assignment, [])
    assert result["valid"] is False
    assert "success_criteria" in result["reason"]
