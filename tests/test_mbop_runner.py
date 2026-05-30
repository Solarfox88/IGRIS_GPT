"""
Tests for igris/core/mbop_runner.py

Issue: #936 — MBOP wiring into supervisor execution loop.
Covers: Phase 1 intake parsing, Phase 9 quality gate, Phase 10 satisfaction gate,
        Phase 11 post-task eval, Phase 12 next-step propagation.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from igris.core.mbop_runner import (
    MBOPIntakeResult,
    MBOPQualityGateResult,
    MBOPSatisfactionGateResult,
    _extract_acceptance_criteria,
    _extract_section,
    mbop_phase10_satisfaction_gate,
    mbop_phase11_post_task_eval,
    mbop_phase12_next_step,
    mbop_phase9_quality_gate,
    mbop_post_run,
    mbop_pre_run,
)


# ---------------------------------------------------------------------------
# Phase 1 — Intake extraction helpers
# ---------------------------------------------------------------------------

SAMPLE_ISSUE_BODY = textwrap.dedent("""\
    ## MBOP Intake

    ### What
    Add LongTermMemory module with rolling summary and domain index.

    ### Where
    igris/core/long_term_memory.py, tests/test_long_term_memory.py

    ### Why
    Memory graph loses context between runs. Persistent storage needed.

    ### Constraints
    - Must not change runtime loop behavior
    - VastAI excluded from chains
    - No #942 recovery proposals

    ### Output Expected
    - [ ] AC-1: LongTermMemory class exists and can store/retrieve entries
    - [ ] AC-2: Rolling summary generated after 10+ entries
    - [ ] AC-3: Domain index maintained correctly
    - [x] AC-4: Tests pass (12+ assertions)

    ### Unknowns
    - Storage format: JSON vs SQLite → decided: JSON for simplicity
""")


class TestExtractSection:
    def test_extracts_what_section(self):
        text = _extract_section(SAMPLE_ISSUE_BODY, ["### What"])
        assert "LongTermMemory" in text

    def test_extracts_where_section(self):
        text = _extract_section(SAMPLE_ISSUE_BODY, ["### Where"])
        assert "long_term_memory" in text

    def test_returns_empty_for_missing_section(self):
        text = _extract_section(SAMPLE_ISSUE_BODY, ["### NonExistent"])
        assert text == ""

    def test_stops_at_next_header(self):
        text = _extract_section(SAMPLE_ISSUE_BODY, ["### What"])
        # Should not include content from ### Where
        assert "igris/core/long_term_memory" not in text


class TestExtractAcceptanceCriteria:
    def test_extracts_all_acs(self):
        criteria = _extract_acceptance_criteria(SAMPLE_ISSUE_BODY)
        assert len(criteria) == 4

    def test_extracts_unchecked_acs(self):
        criteria = _extract_acceptance_criteria(SAMPLE_ISSUE_BODY)
        assert any("LongTermMemory class exists" in c for c in criteria)

    def test_extracts_checked_acs(self):
        criteria = _extract_acceptance_criteria(SAMPLE_ISSUE_BODY)
        assert any("Tests pass" in c for c in criteria)

    def test_no_acs_returns_empty(self):
        criteria = _extract_acceptance_criteria("No checkboxes here.")
        assert criteria == []


# ---------------------------------------------------------------------------
# Phase 1 — mbop_pre_run (with mocked gh CLI)
# ---------------------------------------------------------------------------

class TestMbopPreRun:
    def test_pre_run_no_issue_number(self, tmp_path):
        result = mbop_pre_run(issue_number=0, project_root=str(tmp_path))
        assert result.issue_number == 0
        assert not result.extraction_ok

    def test_pre_run_calls_run_add(self, tmp_path):
        mock_gh_output = '{"title": "Test issue", "body": "' + SAMPLE_ISSUE_BODY.replace('"', '\\"').replace("\n", "\\n") + '", "labels": []}'
        mock_add = MagicMock()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=mock_gh_output,
                stderr="",
            )
            result = mbop_pre_run(
                issue_number=951,
                project_root=str(tmp_path),
                run_add_fn=mock_add,
            )

        assert result.issue_number == 951
        assert result.extraction_ok
        assert result.what  # Should have extracted something
        # run.add should have been called with mbop_phase1_intake
        mock_add.assert_called()
        call_args = mock_add.call_args_list[0]
        assert call_args[0][0] == "mbop_phase1_intake"

    def test_pre_run_gh_failure_returns_empty(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
            result = mbop_pre_run(issue_number=999, project_root=str(tmp_path))
        # Should not raise, extraction_ok should be False
        assert not result.extraction_ok

    def test_pre_run_is_best_effort(self, tmp_path):
        """gh CLI exception should not propagate."""
        with patch("subprocess.run", side_effect=FileNotFoundError("gh not found")):
            result = mbop_pre_run(issue_number=951, project_root=str(tmp_path))
        assert isinstance(result, MBOPIntakeResult)


# ---------------------------------------------------------------------------
# Phase 9 — Quality Gate
# ---------------------------------------------------------------------------

class TestMbopPhase9QualityGate:
    def test_no_files_passes(self, tmp_path):
        result = mbop_phase9_quality_gate(str(tmp_path), [])
        assert result.passed
        assert not result.pytest_ran

    def test_stub_pattern_detected(self, tmp_path):
        py_file = tmp_path / "igris" / "core" / "fake.py"
        py_file.parent.mkdir(parents=True)
        py_file.write_text("def foo():\n    # TODO implement this\n    pass\n")
        result = mbop_phase9_quality_gate(str(tmp_path), ["igris/core/fake.py"])
        assert not result.passed
        assert len(result.stub_patterns_found) > 0

    def test_clean_file_passes_stub_check(self, tmp_path):
        py_file = tmp_path / "igris" / "core" / "clean.py"
        py_file.parent.mkdir(parents=True)
        py_file.write_text("def foo():\n    return 42\n")
        # No test files → pytest not run → passes
        result = mbop_phase9_quality_gate(str(tmp_path), ["igris/core/clean.py"])
        assert result.passed
        assert not result.pytest_ran

    def test_pytest_runs_on_test_files(self, tmp_path):
        test_file = tmp_path / "tests" / "test_fake.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("def test_always_pass():\n    assert True\n")
        result = mbop_phase9_quality_gate(str(tmp_path), ["tests/test_fake.py"])
        assert result.pytest_ran

    def test_pytest_failure_detected(self, tmp_path):
        test_file = tmp_path / "tests" / "test_fail.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("def test_always_fail():\n    assert False\n")
        result = mbop_phase9_quality_gate(str(tmp_path), ["tests/test_fail.py"])
        assert result.pytest_ran
        assert not result.pytest_passed
        assert not result.passed

    def test_pytest_exception_is_best_effort(self, tmp_path):
        """pytest crash should not propagate as exception."""
        with patch("subprocess.run", side_effect=OSError("no python")):
            result = mbop_phase9_quality_gate(str(tmp_path), ["tests/test_x.py"])
        # Should have error but not raise
        assert isinstance(result, MBOPQualityGateResult)


# ---------------------------------------------------------------------------
# Phase 10 — Satisfaction Gate
# ---------------------------------------------------------------------------

class TestMbopPhase10SatisfactionGate:
    def _make_intake(self, criteria):
        intake = MBOPIntakeResult(issue_number=951)
        intake.acceptance_criteria = criteria
        intake.extraction_ok = True
        return intake

    def test_no_criteria_vacuously_passes(self):
        intake = self._make_intake([])
        result = mbop_phase10_satisfaction_gate(intake, "", "")
        assert result.passed

    def test_ac_found_in_diff(self):
        intake = self._make_intake(["LongTermMemory class exists and can store entries"])
        diff = "+class LongTermMemory:\n+    def store(self, entry):\n+        pass\n"
        result = mbop_phase10_satisfaction_gate(intake, diff, "")
        assert result.passed
        assert len(result.criteria_covered) >= 1

    def test_ac_not_in_diff_fails(self):
        intake = self._make_intake(["completely unrelated requirement zxcvbnm"])
        result = mbop_phase10_satisfaction_gate(intake, "minimal diff", "")
        assert not result.passed
        assert len(result.criteria_missing) == 1

    def test_partial_coverage_passes_at_50_percent(self):
        intake = self._make_intake([
            "LongTermMemory store entries",  # will match
            "completely absent unrelated xqzjk",  # won't match
        ])
        diff = "+class LongTermMemory:\n+    def store(self): pass\n"
        result = mbop_phase10_satisfaction_gate(intake, diff, "")
        # 1/2 = 50% → passes
        assert result.passed


# ---------------------------------------------------------------------------
# Phase 11 — Post-Task Eval
# ---------------------------------------------------------------------------

class TestMbopPhase11PostTaskEval:
    def test_generates_summary(self):
        intake = MBOPIntakeResult(issue_number=951, operating_mode="full")
        quality = MBOPQualityGateResult(passed=True)
        satisfaction = MBOPSatisfactionGateResult(passed=True)
        result = mbop_phase11_post_task_eval(intake, quality, satisfaction, 120.0)
        assert "951" in result.summary
        assert "QG:PASS" in result.summary
        assert "SG:PASS" in result.summary

    def test_lessons_include_stub_warning(self):
        intake = MBOPIntakeResult(issue_number=1)
        quality = MBOPQualityGateResult(passed=False, stub_patterns_found=["fake.py:# todo"])
        satisfaction = MBOPSatisfactionGateResult(passed=True)
        result = mbop_phase11_post_task_eval(intake, quality, satisfaction, 60.0)
        assert any("stub" in l.lower() or "Stub" in l for l in result.lessons)

    def test_lessons_include_failed_tests(self):
        intake = MBOPIntakeResult(issue_number=1)
        quality = MBOPQualityGateResult(passed=False, pytest_ran=True, pytest_passed=False)
        satisfaction = MBOPSatisfactionGateResult(passed=True)
        result = mbop_phase11_post_task_eval(intake, quality, satisfaction, 30.0)
        assert any("test" in l.lower() or "Test" in l for l in result.lessons)


# ---------------------------------------------------------------------------
# Phase 12 — Next-Step Propagation
# ---------------------------------------------------------------------------

class TestMbopPhase12NextStep:
    def test_no_suggestions_for_completed(self, tmp_path):
        intake = MBOPIntakeResult(issue_number=951)
        suggestions = mbop_phase12_next_step(intake, str(tmp_path), "completed")
        assert suggestions == []

    def test_suggestions_for_decomposition(self, tmp_path):
        intake = MBOPIntakeResult(issue_number=951, what="Build GitHub gateway")
        suggestions = mbop_phase12_next_step(
            intake, str(tmp_path), "decomposition_required"
        )
        assert len(suggestions) >= 2
        assert any("GitHub gateway" in s for s in suggestions)


# ---------------------------------------------------------------------------
# mbop_post_run — integration-style test with mock run
# ---------------------------------------------------------------------------

class TestMbopPostRun:
    def _make_run(self, status="completed"):
        run = MagicMock()
        run.status = status
        run.failure_class = ""
        run.outcome = "Completed"
        run.add = MagicMock()
        return run

    def test_post_run_does_not_raise(self, tmp_path):
        run = self._make_run()
        intake = MBOPIntakeResult(issue_number=951)
        # Should complete without exception
        mbop_post_run(run, intake, str(tmp_path), time.time())

    def test_post_run_calls_all_phases(self, tmp_path):
        run = self._make_run()
        intake = MBOPIntakeResult(issue_number=951)
        mbop_post_run(run, intake, str(tmp_path), time.time())
        # Should have logged quality gate, satisfaction gate, post-task eval
        call_names = [c[0][0] for c in run.add.call_args_list]
        assert "mbop_phase9_quality_gate" in call_names
        assert "mbop_phase10_satisfaction_gate" in call_names
        assert "mbop_phase11_post_task_eval" in call_names

    def test_enforce_quality_gate_blocks_run(self, tmp_path):
        """With enforce_quality_gate=True and a TODO stub, run should be blocked."""
        py_file = tmp_path / "tests" / "test_stub.py"
        py_file.parent.mkdir(parents=True)
        py_file.write_text("def test_x():\n    # TODO real impl\n    assert True\n")

        run = self._make_run(status="completed")
        intake = MBOPIntakeResult(issue_number=951)

        with patch("igris.core.mbop_runner._get_modified_files", return_value=["tests/test_stub.py"]):
            with patch("igris.core.mbop_runner._get_diff_text", return_value=""):
                with patch("igris.core.mbop_runner._get_last_commit_message", return_value=""):
                    mbop_post_run(run, intake, str(tmp_path), time.time(), enforce_quality_gate=True)

        # Run should be downgraded to blocked
        assert run.status == "blocked"
        assert run.failure_class == "mbop_quality_gate_failed"

    def test_enforce_off_leaves_run_completed(self, tmp_path):
        """With enforce_quality_gate=False (default), stubs don't block run."""
        py_file = tmp_path / "tests" / "test_stub.py"
        py_file.parent.mkdir(parents=True)
        py_file.write_text("def test_x():\n    # TODO real impl\n    assert True\n")

        run = self._make_run(status="completed")
        intake = MBOPIntakeResult(issue_number=951)

        with patch("igris.core.mbop_runner._get_modified_files", return_value=["tests/test_stub.py"]):
            with patch("igris.core.mbop_runner._get_diff_text", return_value=""):
                with patch("igris.core.mbop_runner._get_last_commit_message", return_value=""):
                    mbop_post_run(run, intake, str(tmp_path), time.time(), enforce_quality_gate=False)

        # Run should remain completed despite stubs (advisory-only)
        assert run.status == "completed"

    def test_post_run_never_raises_on_crash(self, tmp_path):
        """Even if all internals crash, post_run must not propagate."""
        run = MagicMock()
        run.status = "completed"
        run.failure_class = ""
        run.add = MagicMock(side_effect=RuntimeError("db full"))
        intake = MBOPIntakeResult(issue_number=951)
        # Must not raise
        mbop_post_run(run, intake, str(tmp_path), time.time())
