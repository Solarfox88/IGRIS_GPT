"""Tests for execution reports."""
import os
from igris.core import execution_report
from igris.models.config import CONFIG


def test_create_and_retrieve_report(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    os.environ["PROJECT_ROOT"] = str(root)
    CONFIG.project_root = root

    report = execution_report.create_report(
        command_id="run_tests",
        capability_id="validation.run_tests",
        returncode=0,
        stdout="8 passed",
        stderr="",
        started_at="2024-01-01T00:00:00Z",
        finished_at="2024-01-01T00:00:01Z",
        duration_ms=1000,
    )
    assert report["success"] is True
    assert report["report_id"]

    fetched = execution_report.get_report(report["report_id"])
    assert fetched is not None
    assert fetched["command_id"] == "run_tests"


def test_recent_reports(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    os.environ["PROJECT_ROOT"] = str(root)
    CONFIG.project_root = root

    execution_report.create_report(
        command_id="git_status", capability_id="execution.run_safe_command",
        returncode=0, stdout="", stderr="",
        started_at="2024-01-01T00:00:00Z", finished_at="2024-01-01T00:00:00Z",
        duration_ms=50,
    )
    reports = execution_report.recent_reports()
    assert len(reports) >= 1


def test_report_redacts_secrets(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    os.environ["PROJECT_ROOT"] = str(root)
    CONFIG.project_root = root

    report = execution_report.create_report(
        command_id="run_tests", capability_id="validation.run_tests",
        returncode=1,
        stdout="key is sk-abc123def456ghi789jkl012mno345pqr678",
        stderr="",
        started_at="2024-01-01T00:00:00Z", finished_at="2024-01-01T00:00:01Z",
        duration_ms=500,
    )
    assert "sk-abc123" not in report["stdout_truncated"]
    assert "REDACTED" in report["stdout_truncated"]
