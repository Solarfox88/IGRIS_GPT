"""Tests for igris/core/code_health_monitor.py (issue #521)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from igris.core.code_health_monitor import (
    CodeHealthMonitor,
    HealthFinding,
    _detect_coverage_drops,
    _detect_coverage_gaps,
    _detect_complexity_growth,
    _issue_already_open,
    _load_coverage_history,
    _save_coverage_history,
    _load_loc_history,
    _save_loc_history,
    _parse_coverage_json,
    _COVERAGE_THRESHOLD,
    _COVERAGE_DROP_THRESHOLD,
    _LOC_THRESHOLD,
    _LOC_GROWTH_PCT,
)


# ---------------------------------------------------------------------------
# Coverage helpers
# ---------------------------------------------------------------------------

class TestParseCoverageJson:
    def test_extracts_pct_per_file(self):
        data = {
            "files": {
                "igris/core/foo.py": {"summary": {"percent_covered": 72.5}},
                "igris/core/bar.py": {"summary": {"percent_covered": 30.0}},
            }
        }
        result = _parse_coverage_json(data)
        assert result["igris/core/foo.py"] == pytest.approx(72.5)
        assert result["igris/core/bar.py"] == pytest.approx(30.0)

    def test_empty_files_returns_empty(self):
        assert _parse_coverage_json({"files": {}}) == {}

    def test_missing_files_key_returns_empty(self):
        assert _parse_coverage_json({}) == {}


class TestCoverageHistory:
    def test_save_and_load(self, tmp_path):
        data = {"igris/core/foo.py": 80.0}
        _save_coverage_history(str(tmp_path), data)
        loaded = _load_coverage_history(str(tmp_path))
        assert loaded == data

    def test_load_missing_returns_empty(self, tmp_path):
        assert _load_coverage_history(str(tmp_path)) == {}

    def test_load_corrupt_returns_empty(self, tmp_path):
        (tmp_path / ".igris").mkdir()
        (tmp_path / ".igris" / "coverage_history.json").write_text("CORRUPT")
        assert _load_coverage_history(str(tmp_path)) == {}


class TestDetectCoverageDrops:
    def test_drop_above_threshold_produces_finding(self):
        current = {"igris/core/foo.py": 60.0}
        history = {"igris/core/foo.py": 70.0}
        findings = _detect_coverage_drops(current, history)
        assert len(findings) == 1
        assert findings[0].category == "coverage_drop"
        assert "foo.py" in findings[0].module_path

    def test_drop_below_threshold_no_finding(self):
        current = {"igris/core/foo.py": 68.0}
        history = {"igris/core/foo.py": 70.0}
        findings = _detect_coverage_drops(current, history)
        assert findings == []

    def test_no_history_no_finding(self):
        current = {"igris/core/foo.py": 60.0}
        findings = _detect_coverage_drops(current, {})
        assert findings == []

    def test_large_drop_is_high_severity(self):
        current = {"igris/core/foo.py": 40.0}
        history = {"igris/core/foo.py": 80.0}
        findings = _detect_coverage_drops(current, history)
        assert findings[0].severity == "high"

    def test_moderate_drop_is_medium_severity(self):
        current = {"igris/core/foo.py": 60.0}
        history = {"igris/core/foo.py": 70.0}
        findings = _detect_coverage_drops(current, history)
        assert findings[0].severity == "medium"


class TestDetectCoverageGaps:
    def test_below_threshold_produces_finding(self):
        current = {"igris/core/foo.py": _COVERAGE_THRESHOLD - 1}
        findings = _detect_coverage_gaps(current)
        assert len(findings) == 1
        assert findings[0].category == "coverage_gap"

    def test_above_threshold_no_finding(self):
        current = {"igris/core/foo.py": _COVERAGE_THRESHOLD + 1}
        findings = _detect_coverage_gaps(current)
        assert findings == []

    def test_exactly_at_threshold_no_finding(self):
        current = {"igris/core/foo.py": _COVERAGE_THRESHOLD}
        findings = _detect_coverage_gaps(current)
        assert findings == []

    def test_multiple_gaps(self):
        current = {
            "igris/core/a.py": 10.0,
            "igris/core/b.py": 80.0,
            "igris/core/c.py": 20.0,
        }
        findings = _detect_coverage_gaps(current)
        assert len(findings) == 2


# ---------------------------------------------------------------------------
# Complexity
# ---------------------------------------------------------------------------

class TestDetectComplexityGrowth:
    def test_file_crossing_loc_threshold_produces_finding(self, tmp_path):
        igris_dir = tmp_path / "igris" / "core"
        igris_dir.mkdir(parents=True)
        big_file = igris_dir / "big.py"
        big_file.write_text("\n".join(["x = 1"] * (_LOC_THRESHOLD + 10)))

        findings, new_loc = _detect_complexity_growth(str(tmp_path))
        assert any(f.category == "complexity_growth" and "big.py" in f.module_path for f in findings)

    def test_small_file_no_finding(self, tmp_path):
        igris_dir = tmp_path / "igris" / "core"
        igris_dir.mkdir(parents=True)
        small = igris_dir / "small.py"
        small.write_text("x = 1\n" * 50)
        findings, _ = _detect_complexity_growth(str(tmp_path))
        assert findings == []

    def test_growth_above_pct_produces_finding(self, tmp_path):
        igris_dir = tmp_path / "igris" / "core"
        igris_dir.mkdir(parents=True)
        growing = igris_dir / "growing.py"
        # 200 lines now, was 100 → 100% growth
        growing.write_text("\n".join(["x = 1"] * 200))
        _save_loc_history(str(tmp_path), {str(growing.relative_to(tmp_path)): 100})
        findings, _ = _detect_complexity_growth(str(tmp_path))
        assert any(f.category == "complexity_growth" for f in findings)

    def test_loc_history_persisted(self, tmp_path):
        igris_dir = tmp_path / "igris" / "core"
        igris_dir.mkdir(parents=True)
        (igris_dir / "f.py").write_text("x = 1\n" * 10)
        _, new_loc = _detect_complexity_growth(str(tmp_path))
        _save_loc_history(str(tmp_path), new_loc)
        loaded = _load_loc_history(str(tmp_path))
        assert any("f.py" in k for k in loaded)


# ---------------------------------------------------------------------------
# Anti-spam
# ---------------------------------------------------------------------------

class TestIssueAlreadyOpen:
    def test_matching_title_blocks(self):
        open_issues = [{"title": "health(coverage): low coverage 20% on foo.py", "number": 1}]
        assert _issue_already_open(open_issues, "coverage_gap", "igris/core/foo.py") is True

    def test_different_module_not_blocked(self):
        open_issues = [{"title": "health(coverage): low coverage 20% on bar.py", "number": 1}]
        assert _issue_already_open(open_issues, "coverage_gap", "igris/core/foo.py") is False

    def test_empty_list_not_blocked(self):
        assert _issue_already_open([], "coverage_drop", "igris/core/foo.py") is False

    def test_different_category_not_blocked(self):
        open_issues = [{"title": "health(todo): stale TODO in foo.py", "number": 1}]
        assert _issue_already_open(open_issues, "coverage_gap", "igris/core/foo.py") is False


# ---------------------------------------------------------------------------
# Integration: CodeHealthMonitor.run() dry_run
# ---------------------------------------------------------------------------

class TestCodeHealthMonitorDryRun:
    def test_dry_run_produces_no_gh_calls(self, tmp_path):
        igris_dir = tmp_path / "igris" / "core"
        igris_dir.mkdir(parents=True)
        (igris_dir / "gap.py").write_text("x = 1\n")  # tiny file, will have coverage gap if data exists

        # Inject low-coverage data
        cov_data = {
            "files": {
                str((igris_dir / "gap.py").relative_to(tmp_path)): {
                    "summary": {"percent_covered": 10.0}
                }
            }
        }
        (tmp_path / "coverage.json").write_text(json.dumps(cov_data))

        monitor = CodeHealthMonitor(str(tmp_path), dry_run=True)
        with patch("igris.core.code_health_monitor._load_open_proactive_issues", return_value=[]):
            report = monitor.run(run_coverage=False)

        assert len(report.issues_opened) == 0   # dry_run → no gh calls
        assert len(report.findings) > 0          # but findings are collected

    def test_run_returns_report(self, tmp_path):
        (tmp_path / "igris").mkdir()
        monitor = CodeHealthMonitor(str(tmp_path), dry_run=True)
        with patch("igris.core.code_health_monitor._load_open_proactive_issues", return_value=[]):
            report = monitor.run(run_coverage=False)
        assert hasattr(report, "findings")
        assert hasattr(report, "issues_opened")
        assert hasattr(report, "ran_at")

    def test_antispam_skips_duplicate(self, tmp_path):
        cov_data = {
            "files": {
                "igris/core/foo.py": {"summary": {"percent_covered": 5.0}}
            }
        }
        (tmp_path / "coverage.json").write_text(json.dumps(cov_data))
        open_issues = [{"title": "health(coverage): low coverage 5% on foo.py", "number": 99}]
        monitor = CodeHealthMonitor(str(tmp_path), dry_run=True)
        with patch("igris.core.code_health_monitor._load_open_proactive_issues", return_value=open_issues):
            report = monitor.run(run_coverage=False)
        assert report.issues_skipped >= 1
