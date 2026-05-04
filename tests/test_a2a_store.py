"""Tests for igris.a2a.task_store."""

from __future__ import annotations

from pathlib import Path

import pytest

from igris.a2a.task_store import (
    MAX_ARTIFACT_SIZE,
    TERMINAL_STATUSES,
    VALID_STATUSES,
    add_artifact,
    cancel_a2a_task,
    create_a2a_task,
    get_a2a_task,
    get_artifacts,
    get_events,
    list_a2a_tasks,
    update_a2a_task_status,
)


@pytest.fixture
def project_dir(tmp_path: Path) -> str:
    (tmp_path / ".igris" / "a2a" / "tasks").mkdir(parents=True, exist_ok=True)
    return str(tmp_path)


class TestCreateTask:
    def test_create(self, project_dir: str) -> None:
        task = create_a2a_task("My Task", "Do something", project_root=project_dir)
        assert task["title"] == "My Task"
        assert task["status"] == "submitted"
        assert len(task["events"]) == 1

    def test_create_persists(self, project_dir: str) -> None:
        task = create_a2a_task("T1", project_root=project_dir)
        loaded = get_a2a_task(task["id"], project_root=project_dir)
        assert loaded is not None
        assert loaded["title"] == "T1"


class TestStatusTransitions:
    def test_submitted_to_working(self, project_dir: str) -> None:
        task = create_a2a_task("T", project_root=project_dir)
        updated = update_a2a_task_status(task["id"], "working", project_root=project_dir)
        assert updated["status"] == "working"

    def test_working_to_completed(self, project_dir: str) -> None:
        task = create_a2a_task("T", project_root=project_dir)
        update_a2a_task_status(task["id"], "working", project_root=project_dir)
        updated = update_a2a_task_status(task["id"], "completed", project_root=project_dir)
        assert updated["status"] == "completed"

    def test_working_to_input_required(self, project_dir: str) -> None:
        task = create_a2a_task("T", project_root=project_dir)
        update_a2a_task_status(task["id"], "working", project_root=project_dir)
        updated = update_a2a_task_status(task["id"], "input_required", detail="Need API key", project_root=project_dir)
        assert updated["status"] == "input_required"
        assert any("Need API key" in e.get("detail", "") for e in updated["events"])

    def test_cannot_transition_from_terminal(self, project_dir: str) -> None:
        task = create_a2a_task("T", project_root=project_dir)
        update_a2a_task_status(task["id"], "completed", project_root=project_dir)
        result = update_a2a_task_status(task["id"], "working", project_root=project_dir)
        assert result is None

    def test_invalid_status(self, project_dir: str) -> None:
        task = create_a2a_task("T", project_root=project_dir)
        result = update_a2a_task_status(task["id"], "invalid", project_root=project_dir)
        assert result is None


class TestCancel:
    def test_cancel_task(self, project_dir: str) -> None:
        task = create_a2a_task("T", project_root=project_dir)
        result = cancel_a2a_task(task["id"], reason="No longer needed", project_root=project_dir)
        assert result["status"] == "canceled"

    def test_cancel_completed_fails(self, project_dir: str) -> None:
        task = create_a2a_task("T", project_root=project_dir)
        update_a2a_task_status(task["id"], "completed", project_root=project_dir)
        result = cancel_a2a_task(task["id"], project_root=project_dir)
        assert result is None

    def test_cancel_nonexistent(self, project_dir: str) -> None:
        result = cancel_a2a_task("nonexistent", project_root=project_dir)
        assert result is None


class TestArtifacts:
    def test_add_artifact(self, project_dir: str) -> None:
        task = create_a2a_task("T", project_root=project_dir)
        art = add_artifact(task["id"], "result.txt", "Hello world", project_root=project_dir)
        assert art["name"] == "result.txt"
        assert art["content"] == "Hello world"

    def test_list_artifacts(self, project_dir: str) -> None:
        task = create_a2a_task("T", project_root=project_dir)
        add_artifact(task["id"], "a1.txt", "C1", project_root=project_dir)
        add_artifact(task["id"], "a2.txt", "C2", project_root=project_dir)
        arts = get_artifacts(task["id"], project_root=project_dir)
        assert len(arts) == 2

    def test_artifact_too_large(self, project_dir: str) -> None:
        task = create_a2a_task("T", project_root=project_dir)
        big = "x" * (MAX_ARTIFACT_SIZE + 1)
        result = add_artifact(task["id"], "big.txt", big, project_root=project_dir)
        assert "error" in result

    def test_artifact_secret_redacted(self, project_dir: str) -> None:
        task = create_a2a_task("T", project_root=project_dir)
        art = add_artifact(task["id"], "secret.txt", "API_KEY=sk-secrettest1234567890123456", project_root=project_dir)
        assert "sk-secrettest1234567890123456" not in art["content"]

    def test_artifact_nonexistent_task(self, project_dir: str) -> None:
        result = add_artifact("nonexistent", "a.txt", "c", project_root=project_dir)
        assert result is None

    def test_get_artifacts_nonexistent(self, project_dir: str) -> None:
        result = get_artifacts("nonexistent", project_root=project_dir)
        assert result is None


class TestEvents:
    def test_events_on_create(self, project_dir: str) -> None:
        task = create_a2a_task("T", project_root=project_dir)
        events = get_events(task["id"], project_root=project_dir)
        assert len(events) >= 1
        assert events[0]["type"] == "status_change"

    def test_events_accumulate(self, project_dir: str) -> None:
        task = create_a2a_task("T", project_root=project_dir)
        update_a2a_task_status(task["id"], "working", project_root=project_dir)
        add_artifact(task["id"], "a.txt", "c", project_root=project_dir)
        events = get_events(task["id"], project_root=project_dir)
        assert len(events) >= 3

    def test_events_nonexistent(self, project_dir: str) -> None:
        result = get_events("nonexistent", project_root=project_dir)
        assert result is None


class TestListTasks:
    def test_list_empty(self, project_dir: str) -> None:
        tasks = list_a2a_tasks(project_root=project_dir)
        assert tasks == []

    def test_list_multiple(self, project_dir: str) -> None:
        create_a2a_task("T1", project_root=project_dir)
        create_a2a_task("T2", project_root=project_dir)
        tasks = list_a2a_tasks(project_root=project_dir)
        assert len(tasks) == 2


class TestSecretRedaction:
    def test_title_redacted(self, project_dir: str) -> None:
        task = create_a2a_task("API_KEY=sk-secrettest1234567890123456", project_root=project_dir)
        assert "sk-secrettest1234567890123456" not in task["title"]

    def test_event_detail_redacted(self, project_dir: str) -> None:
        task = create_a2a_task("T", project_root=project_dir)
        update_a2a_task_status(task["id"], "working", detail="password=mysecret123", project_root=project_dir)
        events = get_events(task["id"], project_root=project_dir)
        for e in events:
            assert "mysecret123" not in e.get("detail", "")
