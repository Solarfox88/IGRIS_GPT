from pathlib import Path

from igris.agent.mission.validation_runner import run_validation_suite


def test_validation_runner_generates_reports(tmp_path: Path):
    json_path, md_path = run_validation_suite(project_root=str(tmp_path))
    assert json_path.exists()
    assert md_path.exists()
    text = md_path.read_text(encoding="utf-8")
    assert "Mission Brain MVP Validation Report" in text
    assert "Scenario Scorecard" in text

