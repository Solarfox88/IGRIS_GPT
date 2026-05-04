"""Tests for decision reports per loop cycle (Sprint 15)."""

from __future__ import annotations

import json

import pytest

from igris.core.decision_report import (
    DecisionReport,
    create_decision_report,
    get_decision_report,
    list_decision_reports,
    save_decision_report,
)
from igris.models.task import Task, TaskStatus


def _task(id: int, desc: str, family: str = "other", status: str = "pending") -> Task:
    return Task(id=id, description=desc, family=family, status=TaskStatus(status))


class TestDecisionReportModel:
    def test_to_dict(self):
        r = DecisionReport(
            step_number=1,
            action_detail="ran sk-abcdefghijklmnopqrstuvwxyz cmd",
            outcome="success",
        )
        d = r.to_dict()
        assert d["step_number"] == 1
        assert "sk-" not in d["action_detail"]
        assert d["outcome"] == "success"
        assert d["id"]

    def test_selected_task_redacted(self):
        r = DecisionReport(
            selected_task={
                "id": 1,
                "title": "task with sk-abcdefghijklmnopqrstuvwxyz",
                "description": "desc with ghp_abcdefghijklmnopqrstuvwxyz1234567890",
            }
        )
        d = r.to_dict()
        assert "sk-" not in d["selected_task"]["title"]
        assert "ghp_" not in d["selected_task"]["description"]

    def test_rejected_candidates_redacted(self):
        r = DecisionReport(
            rejected_candidates=[
                {"title": "task with sk-abcdefghijklmnopqrstuvwxyz", "score": -50}
            ]
        )
        d = r.to_dict()
        assert "sk-" not in d["rejected_candidates"][0]["title"]


class TestPersistence:
    def test_save_and_get(self, tmp_path):
        (tmp_path / ".igris" / "reports" / "decisions").mkdir(parents=True)
        (tmp_path / ".igris" / "memory").mkdir(parents=True)
        pr = str(tmp_path)
        r = DecisionReport(step_number=1, outcome="success")
        rid = save_decision_report(r, project_root=pr)
        loaded = get_decision_report(rid, project_root=pr)
        assert loaded is not None
        assert loaded["step_number"] == 1
        assert loaded["outcome"] == "success"

    def test_get_nonexistent(self, tmp_path):
        (tmp_path / ".igris" / "reports" / "decisions").mkdir(parents=True)
        loaded = get_decision_report("nope", project_root=str(tmp_path))
        assert loaded is None

    def test_list_reports(self, tmp_path):
        (tmp_path / ".igris" / "reports" / "decisions").mkdir(parents=True)
        (tmp_path / ".igris" / "memory").mkdir(parents=True)
        pr = str(tmp_path)
        for i in range(3):
            r = DecisionReport(step_number=i, outcome="success")
            save_decision_report(r, project_root=pr)
        reports = list_decision_reports(limit=10, project_root=pr)
        assert len(reports) == 3

    def test_list_empty(self, tmp_path):
        (tmp_path / ".igris" / "reports" / "decisions").mkdir(parents=True)
        reports = list_decision_reports(project_root=str(tmp_path))
        assert reports == []


class TestCreateReport:
    def test_create_with_tasks(self, tmp_path):
        (tmp_path / ".igris" / "memory").mkdir(parents=True)
        (tmp_path / ".igris" / "reports" / "decisions").mkdir(parents=True)
        pr = str(tmp_path)
        tasks = [
            _task(1, "run tests", family="test"),
            _task(2, "deploy app", family="deploy", status="completed"),
        ]
        report = create_decision_report(
            step_number=1,
            tasks=tasks,
            action_type="execute_command",
            action_detail="ran tests",
            outcome="success",
            project_root=pr,
        )
        assert report.step_number == 1
        assert report.action_type == "execute_command"
        assert report.project_snapshot["task_counts"]["total"] == 2
        assert report.project_snapshot["task_counts"]["pending"] == 1
        assert report.memory_constraints is not None

    def test_create_empty_tasks(self, tmp_path):
        (tmp_path / ".igris" / "memory").mkdir(parents=True)
        (tmp_path / ".igris" / "reports" / "decisions").mkdir(parents=True)
        report = create_decision_report(
            step_number=0,
            tasks=[],
            outcome="skipped",
            outcome_reason="no tasks",
            project_root=str(tmp_path),
        )
        assert report.project_snapshot["task_counts"]["total"] == 0
        assert report.selected_task is None

    def test_report_persisted(self, tmp_path):
        (tmp_path / ".igris" / "memory").mkdir(parents=True)
        (tmp_path / ".igris" / "reports" / "decisions").mkdir(parents=True)
        pr = str(tmp_path)
        report = create_decision_report(
            step_number=1,
            tasks=[_task(1, "test")],
            outcome="success",
            project_root=pr,
        )
        loaded = get_decision_report(report.id, project_root=pr)
        assert loaded is not None
        assert loaded["id"] == report.id

    def test_safety_decisions_included(self, tmp_path):
        (tmp_path / ".igris" / "memory").mkdir(parents=True)
        (tmp_path / ".igris" / "reports" / "decisions").mkdir(parents=True)
        report = create_decision_report(
            step_number=1,
            tasks=[],
            safety_decisions=[{"check": "allowlist", "passed": True}],
            project_root=str(tmp_path),
        )
        assert len(report.safety_decisions) == 1

    def test_teacher_recommendation(self, tmp_path):
        (tmp_path / ".igris" / "memory").mkdir(parents=True)
        (tmp_path / ".igris" / "reports" / "decisions").mkdir(parents=True)
        report = create_decision_report(
            step_number=1,
            tasks=[],
            teacher_recommendation={"action": "retry", "reason": "transient error"},
            project_root=str(tmp_path),
        )
        assert report.teacher_recommendation["action"] == "retry"
