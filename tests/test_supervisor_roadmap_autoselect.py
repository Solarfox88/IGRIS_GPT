import json
from pathlib import Path
from unittest.mock import patch, MagicMock


def _make_issue(number, title, labels=None):
    return {"number": number, "title": title, "labels": [{"name": l} for l in (labels or [])]}


class TestSelectNextRoadmapIssue:

    def _make_supervisor(self, tmp_path):
        from igris.core.self_repair_supervisor import SelfRepairSupervisor, RankSupervisorConfig
        sup = SelfRepairSupervisor.__new__(SelfRepairSupervisor)
        sup.project_root = str(tmp_path)
        sup._failure_memory = MagicMock()
        return sup, RankSupervisorConfig(goal="test", allow_roadmap_autoselect=True)

    def test_skips_epics(self, tmp_path):
        sup, config = self._make_supervisor(tmp_path)
        issues = [_make_issue(1, "Epic: redesign everything", ["epic"]),
                  _make_issue(2, "fix: small bug")]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(issues))
            result = sup._select_next_roadmap_issue(config)
        assert result["number"] == 2

    def test_priority_order(self, tmp_path):
        sup, config = self._make_supervisor(tmp_path)
        issues = [_make_issue(10, "low priority task", ["p2"]),
                  _make_issue(5, "high priority task", ["p1"])]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(issues))
            result = sup._select_next_roadmap_issue(config)
        assert result["number"] == 5

    def test_returns_none_for_child_run(self, tmp_path):
        sup, config = self._make_supervisor(tmp_path)
        config = config.__class__(goal="test", autochain_depth=1, allow_roadmap_autoselect=True)
        result = sup._select_next_roadmap_issue(config)
        assert result is None

    def test_hint_file_written(self, tmp_path):
        sup, config = self._make_supervisor(tmp_path)
        issues = [_make_issue(42, "next task")]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(issues))
            result = sup._select_next_roadmap_issue(config)
        hint_path = Path(tmp_path) / ".igris" / "next_roadmap_target.json"
        hint_path.parent.mkdir(parents=True, exist_ok=True)
        hint_path.write_text(json.dumps({"issue_number": result["number"], "issue_title": result["title"], "selected_at": 0.0, "selected_by_run": "test"}))
        data = json.loads(hint_path.read_text())
        assert data["issue_number"] == 42

    def test_no_issues_returns_none(self, tmp_path):
        sup, config = self._make_supervisor(tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="[]")
            result = sup._select_next_roadmap_issue(config)
        assert result is None
