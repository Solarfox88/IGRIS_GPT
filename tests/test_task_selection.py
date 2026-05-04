"""Tests for best-task selection logic."""
from igris.core.task_selection import select_next_task
from igris.models.task import Task, TaskStatus


def _make_task(tid, desc, family="other", priority=0, status=TaskStatus.pending, risk="low"):
    return Task(id=tid, description=desc, family=family, priority=priority, status=status, risk=risk)


def test_advisory_honored_when_safe():
    a = _make_task(1, "Task A", family="editing")
    b = _make_task(2, "Task B", family="testing", priority=5)
    result = select_next_task([a, b], advisory_next_task_id=1, history=[])
    assert result.selected_task is not None
    assert result.selected_task.id == 1
    assert result.advisory_honored is True


def test_advisory_rejected_when_saturated():
    a = _make_task(1, "run pytest", family="testing")
    b = _make_task(2, "write code", family="writing")
    history = ["run pytest"] * 5
    result = select_next_task([a, b], advisory_next_task_id=1, history=history)
    assert result.advisory_honored is False
    assert result.saturation_reason is not None
    assert result.selected_task.id == 2


def test_advisory_rejected_when_duplicate():
    """Advisory should be rejected when task is a duplicate of recent history."""
    a = _make_task(1, "run testing", family="testing")
    b = _make_task(2, "write new feature", family="writing")
    # "run testing" should match "run pytest" since both canonicalize to {run, test}
    history = ["run pytest"]
    result = select_next_task([a, b], advisory_next_task_id=1, history=history)
    assert result.advisory_honored is False
    assert result.duplicate_reason is not None
