"""Tests for PR 1 — DeliveryWorkflow hardening.

Covers:
1. FakeGitHubBackend — interface completeness and configurable state.
2. CommitSafetyGate — secret/artifact/extension blocking.
3. validate_diff_scope — scope violations and file-count limits.
4. DeliveryWorkflow._classify_failure_type — 12 CI failure types.
5. CIRepairLoop — repeated-failure stop, no-diff stop, repair packet.
6. DeliveryWorkflow.pre_merge_safety_check (mocked subprocess).
7. typing fix: DeliveryWorkflow.__init__ accepts Any for backend.

All tests are fully offline — no gh CLI or real git.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from igris.core.github_backend import (
    CommitResult,
    FakeGitHubBackend,
    PRCheckResult,
    PRInfo,
    SubprocessGitHubBackend,
)
from igris.core.commit_safety import (
    CommitSafetyGate,
    DiffScopeResult,
    validate_diff_scope,
)
from igris.core.delivery_workflow import DeliveryWorkflow
from igris.core.ci_repair_loop import CIRepairLoop, CIRepairResult, CIRepairAttempt


# ---------------------------------------------------------------------------
# FakeGitHubBackend
# ---------------------------------------------------------------------------

class TestFakeGitHubBackend:

    def _fake(self) -> FakeGitHubBackend:
        return FakeGitHubBackend()

    def test_list_pr_checks_green(self):
        f = self._fake()
        f.set_ci_status("green")
        r = f.list_pr_checks(42)
        assert r.status == "green"
        assert r.failed_jobs == []

    def test_list_pr_checks_red(self):
        f = self._fake()
        f.set_ci_status("red", failed_jobs=["pytest", "mypy"])
        r = f.list_pr_checks(1)
        assert r.status == "red"
        assert "pytest" in r.failed_jobs

    def test_fetch_failed_logs_returns_configured_text(self):
        f = self._fake()
        f.set_pr_logs("FAILED tests/foo.py::test_bar\nAssertionError: expected 1 got 2")
        logs = f.fetch_failed_logs(99)
        assert "FAILED tests/foo.py" in logs

    def test_fetch_failed_logs_respects_max_chars(self):
        f = self._fake()
        f.set_pr_logs("x" * 10000)
        logs = f.fetch_failed_logs(1, max_chars=100)
        assert len(logs) <= 100

    def test_commit_changes_recorded(self):
        f = self._fake()
        r = f.commit_changes("fix: something", files=["src/foo.py"])
        assert r.committed is True
        assert len(f.commits) == 1
        assert f.commits[0]["message"] == "fix: something"

    def test_commit_changes_fails_when_configured(self):
        f = self._fake()
        f.set_commit_fails(True)
        r = f.commit_changes("msg")
        assert r.committed is False
        assert "fake commit failure" in r.error

    def test_push_branch_recorded(self):
        f = self._fake()
        ok = f.push_branch()
        assert ok is True
        assert f.pushes == 1

    def test_push_branch_fails_when_configured(self):
        f = self._fake()
        f.set_push_fails(True)
        assert f.push_branch() is False

    def test_create_pr_increments_number(self):
        f = self._fake()
        n1 = f.create_pr("title 1", "body", "branch-1")
        n2 = f.create_pr("title 2", "body", "branch-2")
        assert n2 == n1 + 1
        assert len(f.created_prs) == 2

    def test_merge_pr_recorded(self):
        f = self._fake()
        ok = f.merge_pr(42)
        assert ok is True
        assert 42 in f.merges

    def test_merge_pr_fails_when_configured(self):
        f = self._fake()
        f.set_merge_fails(True)
        assert f.merge_pr(1) is False

    def test_fetch_changed_files(self):
        f = self._fake()
        f.set_changed_files(["src/foo.py", "tests/test_foo.py"])
        files = f.fetch_changed_files("my-branch")
        assert "src/foo.py" in files

    def test_get_pr_info_default(self):
        f = self._fake()
        info = f.get_pr_info(7)
        assert info is not None
        assert info.pr_number == 7
        assert info.is_draft is False

    def test_get_pr_info_configured(self):
        f = self._fake()
        f.set_pr_info(PRInfo(pr_number=99, is_draft=True, state="open"))
        info = f.get_pr_info(99)
        assert info.is_draft is True

    def test_delete_branch_recorded(self):
        f = self._fake()
        ok = f.delete_branch("my-branch")
        assert ok is True
        assert "my-branch" in f.branch_deletes


# ---------------------------------------------------------------------------
# CommitSafetyGate
# ---------------------------------------------------------------------------

class TestCommitSafetyGate:

    def _gate(self, tmp_path) -> CommitSafetyGate:
        return CommitSafetyGate(str(tmp_path))

    def test_clean_files_pass(self, tmp_path):
        gate = self._gate(tmp_path)
        report = gate.scan(["src/foo.py", "tests/test_foo.py", "README.md"])
        assert report.ok is True
        assert report.blocked_files == []

    def test_env_file_blocked(self, tmp_path):
        gate = self._gate(tmp_path)
        report = gate.scan([".env"])
        assert report.ok is False
        assert any(fr.path == ".env" for fr in report.blocked_files)

    def test_env_local_blocked(self, tmp_path):
        gate = self._gate(tmp_path)
        report = gate.scan([".env.local"])
        assert report.ok is False

    def test_pem_extension_blocked(self, tmp_path):
        gate = self._gate(tmp_path)
        report = gate.scan(["cert/server.pem"])
        assert report.ok is False

    def test_key_extension_blocked(self, tmp_path):
        gate = self._gate(tmp_path)
        report = gate.scan(["keys/id_rsa.key"])
        assert report.ok is False

    def test_venv_artifact_blocked(self, tmp_path):
        gate = self._gate(tmp_path)
        report = gate.scan([".venv/lib/python3.12/site-packages/foo.py"])
        assert report.ok is False

    def test_pytest_cache_blocked(self, tmp_path):
        gate = self._gate(tmp_path)
        report = gate.scan([".pytest_cache/v/cache/lastfailed"])
        assert report.ok is False

    def test_pycache_blocked(self, tmp_path):
        gate = self._gate(tmp_path)
        report = gate.scan(["igris/core/__pycache__/foo.cpython-312.pyc"])
        assert report.ok is False

    def test_credentials_json_blocked(self, tmp_path):
        gate = self._gate(tmp_path)
        report = gate.scan(["credentials.json"])
        assert report.ok is False

    def test_id_rsa_path_blocked(self, tmp_path):
        gate = self._gate(tmp_path)
        report = gate.scan(["~/.ssh/id_rsa"])
        assert report.ok is False

    def test_scope_violation_warning(self, tmp_path):
        gate = self._gate(tmp_path)
        report = gate.scan(["unrelated/module.py"], allowed_scopes=["igris/core/"])
        assert report.ok is True  # scope violations are warnings, not blocks
        assert len(report.scope_violations) > 0

    def test_scan_diff_content_detects_api_key(self, tmp_path):
        gate = self._gate(tmp_path)
        diff = "+api_key = sk-abc123def456ghi789jkl012mno345pqr678\n+other = normal"
        warnings = gate.scan_diff_content(diff)
        assert len(warnings) > 0

    def test_scan_diff_content_clean(self, tmp_path):
        gate = self._gate(tmp_path)
        diff = "+x = 42\n+print('hello')\n"
        warnings = gate.scan_diff_content(diff)
        assert warnings == []

    def test_multiple_blocked_files(self, tmp_path):
        gate = self._gate(tmp_path)
        report = gate.scan([".env", "src/good.py", "credentials.json"])
        assert report.ok is False
        blocked_paths = [fr.path for fr in report.blocked_files]
        assert ".env" in blocked_paths
        assert "credentials.json" in blocked_paths
        assert "src/good.py" not in blocked_paths


# ---------------------------------------------------------------------------
# validate_diff_scope
# ---------------------------------------------------------------------------

class TestValidateDiffScope:

    def test_no_scope_no_violation(self):
        result = validate_diff_scope(["src/foo.py", "tests/test_foo.py"], allowed_scopes=None)
        assert result.ok is True

    def test_in_scope_passes(self):
        result = validate_diff_scope(
            ["igris/core/foo.py"],
            allowed_scopes=["igris/core/"],
        )
        assert result.ok is True

    def test_out_of_scope_blocked(self):
        result = validate_diff_scope(
            ["unrelated/module.py"],
            allowed_scopes=["igris/core/"],
        )
        assert result.ok is False
        assert any("out-of-scope" in v for v in result.violations)

    def test_secret_file_blocked(self):
        result = validate_diff_scope([".env"], allowed_scopes=None)
        assert result.ok is False

    def test_too_many_files(self):
        files = [f"src/file_{i}.py" for i in range(100)]
        result = validate_diff_scope(files, allowed_scopes=None, max_files=50)
        assert result.ok is False
        assert any("too many" in v for v in result.violations)

    def test_ci_workflow_change_warns_without_ci_goal(self):
        result = validate_diff_scope(
            [".github/workflows/test.yml"],
            allowed_scopes=None,
            issue_goal="fix the login bug",
        )
        # Warning only, not hard violation
        assert any(".github" in w or "CI" in w for w in result.warnings)

    def test_ci_workflow_change_ok_with_ci_goal(self):
        result = validate_diff_scope(
            [".github/workflows/test.yml"],
            allowed_scopes=None,
            issue_goal="update CI workflow to use python 3.12",
        )
        assert not any("CI" in w and "without" in w for w in result.warnings)

    def test_file_count_in_result(self):
        result = validate_diff_scope(["a.py", "b.py"], allowed_scopes=None)
        assert result.file_count == 2

    def test_empty_files_ok(self):
        result = validate_diff_scope([], allowed_scopes=None)
        assert result.ok is True
        assert result.file_count == 0

    def test_summary_on_violation(self):
        result = validate_diff_scope([".env"], allowed_scopes=None)
        assert "VIOLATIONS" in result.summary or "blocked" in result.summary.lower()

    def test_summary_on_ok(self):
        result = validate_diff_scope(["src/foo.py"], allowed_scopes=None)
        assert "ok" in result.summary.lower()


# ---------------------------------------------------------------------------
# DeliveryWorkflow._classify_failure_type
# ---------------------------------------------------------------------------

class TestClassifyFailureType:

    def _classify(self, log: str) -> str:
        return DeliveryWorkflow._classify_failure_type(log)

    def test_import_error(self):
        assert self._classify("ImportError: cannot import name 'foo'") == "import_error"

    def test_module_not_found(self):
        # Contract: missing module/dependency is dependency_error (not import_error)
        assert self._classify("ModuleNotFoundError: No module named 'bar'") == "dependency_error"

    def test_syntax_error(self):
        assert self._classify("SyntaxError: invalid syntax at line 42") == "syntax_error"

    def test_indentation_error(self):
        assert self._classify("IndentationError: unexpected indent") == "syntax_error"

    def test_formatting_error(self):
        log = "ruff format would reformat igris/core/foo.py"
        assert self._classify(log) == "formatting_error"

    def test_lint_error(self):
        log = "ruff check error: E501 line too long"
        assert self._classify(log) == "lint_error"

    def test_dependency_error(self):
        log = "Could not install packages due to an OSError"
        assert self._classify(log) == "dependency_error"

    def test_timeout(self):
        log = "Time limit exceeded for job test-suite"
        assert self._classify(log) == "timeout"

    def test_test_failure(self):
        log = "FAILED tests/test_foo.py::test_bar\n2 failed, 8 passed"
        assert self._classify(log) == "test_failure"

    def test_assertion_failure(self):
        log = "AssertionError: expected foo but got bar (in unit context)"
        assert self._classify(log) in ("assertion_failure", "test_failure")

    def test_flaky_test_suspected(self):
        log = "ConnectionError: connection refused\nFAILED tests/test_network.py::test_ping"
        result = self._classify(log)
        assert result in ("flaky_test_suspected", "test_failure")

    def test_unknown_returns_unknown(self):
        assert self._classify("some random CI output without known patterns") == "unknown"

    def test_permission_error(self):
        log = "PermissionError: [Errno 13] Permission denied: '/etc/foo'"
        assert self._classify(log) == "permission_error"


# ---------------------------------------------------------------------------
# CIRepairLoop — repeated-failure stop
# ---------------------------------------------------------------------------

class TestCIRepairLoopHardening:

    def _fake_backend(self, success: bool = False) -> MagicMock:
        b = MagicMock()
        b.run_reasoning.return_value = {
            "status": "finished" if success else "failed",
            "final_summary": "test summary",
        }
        return b

    def test_repeated_failure_stop_same_type(self, tmp_path):
        """If the same failure type repeats twice with no progress, loop stops."""
        loop = CIRepairLoop(
            project_root=str(tmp_path),
            pr_number=1,
            original_goal="fix the code",
            max_attempts=5,
        )
        log_text = "FAILED tests/test_foo.py::test_bar\nAssertionError"

        backend = self._fake_backend(success=False)
        # Patch _fetch_ci_logs to always return test_failure log
        # Patch _push_fix_with_safety_gate to return True (no real git)
        # Patch _ci_is_green to return False
        with (
            patch.object(loop, "_fetch_ci_logs", return_value=log_text),
            patch.object(loop, "_push_fix_with_safety_gate", return_value=True),
            patch.object(loop, "_ci_is_green", return_value=False),
        ):
            result = loop.run(backend)

        assert result.resolved is False
        # Should have stopped early due to repeated failure
        skip_attempts = [a for a in result.attempts if a.strategy == "skip"]
        assert len(skip_attempts) >= 1

    def test_no_diff_stop(self, tmp_path):
        """If push returns False (no diff), loop stops without further attempts."""
        loop = CIRepairLoop(
            project_root=str(tmp_path),
            pr_number=2,
            original_goal="fix tests",
            max_attempts=3,
        )
        log_text = "FAILED tests/test_foo.py::test_bar"

        backend = self._fake_backend(success=True)
        with (
            patch.object(loop, "_fetch_ci_logs", return_value=log_text),
            patch.object(loop, "_push_fix_with_safety_gate", return_value=False),  # no diff
            patch.object(loop, "_ci_is_green", return_value=False),
        ):
            result = loop.run(backend)

        # Should have stopped after first attempt since push returned False
        assert result.resolved is False
        # Attempted at most once LLM repair before no-diff stop
        llm_attempts = [a for a in result.attempts if a.strategy == "llm_repair"]
        assert len(llm_attempts) <= 1

    def test_repair_packet_includes_constraints(self, tmp_path):
        """Repair packet sent to LLM includes constraints and context."""
        loop = CIRepairLoop(
            project_root=str(tmp_path),
            pr_number=3,
            original_goal="add /ping endpoint",
            max_attempts=1,
            allowed_files=["igris/web/routes.py"],
        )
        diagnosis = {
            "failure_type": "test_failure",
            "failing_tests": ["tests/test_ping.py::test_ping"],
            "log_excerpt": "AssertionError: 404",
        }
        with patch.object(loop, "_fetch_ci_logs", return_value=""):
            packet = loop._build_repair_packet(diagnosis)

        assert "failing_tests" in packet
        assert "constraints" in packet
        assert "allowed_files" in packet
        assert loop.allowed_files == packet["allowed_files"]
        assert len(packet["constraints"]) > 0

    def test_diagnosis_uses_extended_classifier(self, tmp_path):
        """_diagnose() now uses 12-type classifier."""
        loop = CIRepairLoop(
            project_root=str(tmp_path),
            pr_number=4,
            original_goal="fix lint",
        )
        log_text = "ruff format would reformat igris/core/foo.py"
        diagnosis = loop._diagnose(log_text)
        assert diagnosis["failure_type"] == "formatting_error"

    def test_lint_diagnosis(self, tmp_path):
        loop = CIRepairLoop(str(tmp_path), 5, "fix lint")
        diagnosis = loop._diagnose("ruff check error: E501 line too long")
        assert diagnosis["failure_type"] == "lint_error"

    def test_result_has_failure_summary_on_failure(self, tmp_path):
        loop = CIRepairLoop(str(tmp_path), 6, "fix tests", max_attempts=1)
        backend = self._fake_backend(success=False)
        with (
            patch.object(loop, "_fetch_ci_logs", return_value="FAILED tests/t.py"),
            patch.object(loop, "_push_fix_with_safety_gate", return_value=True),
            patch.object(loop, "_ci_is_green", return_value=False),
        ):
            result = loop.run(backend)
        assert isinstance(result.failure_summary, str)
        assert result.resolved is False

    def test_result_resolved_when_ci_green(self, tmp_path):
        loop = CIRepairLoop(str(tmp_path), 7, "fix tests", max_attempts=1)
        backend = self._fake_backend(success=True)
        with (
            patch.object(loop, "_fetch_ci_logs", return_value="FAILED tests/t.py"),
            patch.object(loop, "_push_fix_with_safety_gate", return_value=True),
            patch.object(loop, "_ci_is_green", return_value=True),
        ):
            result = loop.run(backend)
        assert result.resolved is True


# ---------------------------------------------------------------------------
# CommitSafetyGate — _push_fix_with_safety_gate integration
# ---------------------------------------------------------------------------

class TestPushFixWithSafetyGate:

    def test_no_diff_returns_false(self, tmp_path):
        """If no files are staged, push should not happen."""
        loop = CIRepairLoop(str(tmp_path), 1, "fix")
        with (
            patch("subprocess.run") as mock_run,
        ):
            # git add -u → ok; git diff --cached --name-only → empty
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),  # git add -u
                MagicMock(returncode=0, stdout="", stderr=""),  # git diff --cached
            ]
            result = loop._push_fix_with_safety_gate("test message")
        assert result is False

    def test_blocked_file_prevents_commit(self, tmp_path):
        """If safety gate blocks a file, commit must not happen."""
        loop = CIRepairLoop(str(tmp_path), 1, "fix")
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),      # git add -u
                MagicMock(returncode=0, stdout=".env\n", stderr=""),  # git diff --cached (blocked file)
                MagicMock(returncode=0, stdout="", stderr=""),      # git restore --staged (unstage)
            ]
            result = loop._push_fix_with_safety_gate("should not commit")
        # .env should be blocked → False
        assert result is False

    def test_clean_file_commits_and_pushes(self, tmp_path):
        """Clean files pass the gate, commit and push succeed."""
        loop = CIRepairLoop(str(tmp_path), 1, "fix")
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),               # git add -u
                MagicMock(returncode=0, stdout="src/foo.py\n", stderr=""),   # git diff --cached
                MagicMock(returncode=0, stdout="", stderr=""),               # git commit
                MagicMock(returncode=0, stdout="", stderr=""),               # git push
            ]
            result = loop._push_fix_with_safety_gate("fix: update foo")
        assert result is True


# ---------------------------------------------------------------------------
# DeliveryWorkflow — typing fix and pre_merge_safety_check
# ---------------------------------------------------------------------------

class TestDeliveryWorkflowPR1:

    def test_any_import_works(self, tmp_path):
        """Verify Any import bug is fixed — backend can be any type."""
        dw = DeliveryWorkflow(str(tmp_path), backend=MagicMock(), goal="test")
        assert dw._backend is not None
        assert dw._goal == "test"

    def test_backend_none_accepted(self, tmp_path):
        dw = DeliveryWorkflow(str(tmp_path))
        assert dw._backend is None

    def test_classify_failure_type_is_static(self):
        """_classify_failure_type is a static method accessible without instance."""
        result = DeliveryWorkflow._classify_failure_type("ImportError: no module")
        assert result == "import_error"

    def test_diagnose_ci_failure_structured_extended(self, tmp_path):
        """diagnose_ci_failure_structured now uses 12-type classifier."""
        dw = DeliveryWorkflow(str(tmp_path))
        log = "ruff format would reformat igris/core/foo.py"
        result = dw.diagnose_ci_failure_structured(log, ["format-check"])
        assert result["failure_type"] == "formatting_error"

    def test_pre_merge_safety_check_blocks_env_file(self, tmp_path):
        """pre_merge_safety_check blocks when diff contains .env."""
        dw = DeliveryWorkflow(str(tmp_path))
        with patch("subprocess.run") as mock_run:
            # PR view: not draft
            # PR checks: green
            # git diff: contains .env
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout='{"isDraft":false,"state":"OPEN"}', stderr=""),
                MagicMock(
                    returncode=0,
                    stdout='[{"name":"ci","status":"completed","conclusion":"success"}]',
                    stderr="",
                ),
                MagicMock(returncode=0, stdout=".env\nsrc/foo.py\n", stderr=""),
            ]
            ok, reason = dw.pre_merge_safety_check(42, "my-branch")
        assert ok is False
        assert "safety_gate" in reason or "blocked" in reason.lower()

    def test_pre_merge_safety_check_blocks_draft_pr(self, tmp_path):
        """pre_merge_safety_check blocks draft PRs."""
        dw = DeliveryWorkflow(str(tmp_path))
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"isDraft":true,"state":"OPEN"}',
                stderr="",
            )
            ok, reason = dw.pre_merge_safety_check(42, "my-branch")
        assert ok is False
        assert "draft" in reason

    def test_pre_merge_safety_check_blocks_failed_ci(self, tmp_path):
        """pre_merge_safety_check blocks when CI has failed jobs."""
        dw = DeliveryWorkflow(str(tmp_path))
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout='{"isDraft":false,"state":"OPEN"}', stderr=""),
                MagicMock(
                    returncode=0,
                    stdout='[{"name":"pytest","status":"completed","conclusion":"failure"}]',
                    stderr="",
                ),
            ]
            ok, reason = dw.pre_merge_safety_check(42, "my-branch")
        assert ok is False
        assert "ci_failed" in reason

    def test_pre_merge_safety_check_passes_clean(self, tmp_path):
        """pre_merge_safety_check passes when PR is clean and CI is green."""
        dw = DeliveryWorkflow(str(tmp_path))
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout='{"isDraft":false,"state":"OPEN"}', stderr=""),
                MagicMock(
                    returncode=0,
                    stdout='[{"name":"pytest","status":"completed","conclusion":"success"}]',
                    stderr="",
                ),
                MagicMock(returncode=0, stdout="igris/core/foo.py\n", stderr=""),
            ]
            ok, reason = dw.pre_merge_safety_check(42, "my-branch")
        assert ok is True
        assert reason == "ok"
