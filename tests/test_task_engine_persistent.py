"""Tests for the persistent task engine."""
import os
from igris.core.task_engine import TaskEngine
from igris.models.config import CONFIG


def test_task_persists_on_disk(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    os.environ["PROJECT_ROOT"] = str(root)
    CONFIG.project_root = root

    engine = TaskEngine(runtime_root=root / ".igris")
    task = engine.create_task("persistent task")
    task_id = task.id

    # New engine instance should reload
    engine2 = TaskEngine(runtime_root=root / ".igris")
    reloaded = engine2.get_task(task_id)
    assert reloaded is not None
    assert reloaded.description == "persistent task"


def test_blocked_task_persists(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    os.environ["PROJECT_ROOT"] = str(root)
    CONFIG.project_root = root

    engine = TaskEngine(runtime_root=root / ".igris")
    task = engine.create_task("block me")
    engine.block_task(task.id, reason="waiting for input")

    engine2 = TaskEngine(runtime_root=root / ".igris")
    reloaded = engine2.get_task(task.id)
    assert reloaded.status.value == "blocked"
    assert reloaded.blocked_reason == "waiting for input"


def test_completed_task_persists(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    os.environ["PROJECT_ROOT"] = str(root)
    CONFIG.project_root = root

    engine = TaskEngine(runtime_root=root / ".igris")
    task = engine.create_task("complete me")
    engine.complete_task(task.id, result="done")

    engine2 = TaskEngine(runtime_root=root / ".igris")
    reloaded = engine2.get_task(task.id)
    assert reloaded.status.value == "completed"


def test_igris_not_tracked_by_git(tmp_path):
    """Verify .igris is in .gitignore entries."""
    import pathlib
    gitignore = pathlib.Path(__file__).resolve().parent.parent / ".gitignore"
    content = gitignore.read_text()
    assert ".igris/" in content


def test_timeline_persists(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    os.environ["PROJECT_ROOT"] = str(root)
    CONFIG.project_root = root

    engine = TaskEngine(runtime_root=root / ".igris")
    engine.create_task("task for timeline")
    events = engine.recent_timeline_events(limit=10)
    assert len(events) >= 1
    assert events[0]["event"] == "task_created"
