"""
Tests for SelfModificationGate wired into supervisor patch path — issue #523.

Verifies:
- _preapply_quality_gate calls SelfModificationGate
- Gate blocks writes to core files (mock decision)
- Non-core file patches are not blocked by the gate
- Regression: existing quality gate logic still works
"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_supervisor(project_root: str):
    """Minimal supervisor instantiation for unit tests."""
    from igris.core.self_repair_supervisor import SelfRepairSupervisor as RankSupervisor
    backend = MagicMock()
    backend.run_command.return_value = MagicMock(success=True, stdout="", stderr="", returncode=0)
    backend.restore_dangerous_diff.return_value = MagicMock(success=True)
    return RankSupervisor(
        project_root=project_root,
        backend=backend,
    )


class TestPreapplyQualityGateGateIntegration:
    """_preapply_quality_gate must invoke SelfModificationGate."""

    def test_gate_called_with_diff(self, tmp_path):
        """SelfModificationGate.check() is called from _preapply_quality_gate."""
        supervisor = _make_supervisor(str(tmp_path))
        mock_gate_result = MagicMock()
        mock_gate_result.approved = True
        mock_gate_result.touched_core = []
        mock_gate_result.reason = "no core files touched"

        with patch(
            "igris.core.self_modification_gate.SelfModificationGate.check",
            return_value=mock_gate_result,
        ) as mock_check:
            ok, reasons = supervisor._preapply_quality_gate(
                goal="fix tests", diff_text="--- a/tests/test_foo.py\n+++ b/tests/test_foo.py\n+# fix", files_modified=["tests/test_foo.py"]
            )
        mock_check.assert_called_once()
        assert ok is True

    def test_gate_blocks_core_file_patch(self, tmp_path):
        """When gate returns approved=False, gate_blocked reason is appended."""
        supervisor = _make_supervisor(str(tmp_path))
        mock_gate_result = MagicMock()
        mock_gate_result.approved = False
        mock_gate_result.touched_core = ["igris/web/server.py"]
        mock_gate_result.reason = "targeted tests failed for core module"

        with patch(
            "igris.core.self_modification_gate.SelfModificationGate.check",
            return_value=mock_gate_result,
        ):
            ok, reasons = supervisor._preapply_quality_gate(
                goal="fix server",
                diff_text="--- a/igris/web/server.py\n+++ b/igris/web/server.py\n+# change",
                files_modified=["igris/web/server.py"],
            )
        assert ok is False
        assert any("self_modification_gate_blocked" in r for r in reasons)

    def test_non_core_file_not_blocked_by_gate(self, tmp_path):
        """Non-core patches that pass quality checks should succeed."""
        supervisor = _make_supervisor(str(tmp_path))
        mock_gate_result = MagicMock()
        mock_gate_result.approved = True
        mock_gate_result.touched_core = []
        mock_gate_result.reason = "no core files touched"

        with patch(
            "igris.core.self_modification_gate.SelfModificationGate.check",
            return_value=mock_gate_result,
        ):
            ok, reasons = supervisor._preapply_quality_gate(
                goal="fix something",
                diff_text="--- a/igris/utils/helpers.py\n+++ b/igris/utils/helpers.py\n+# helper",
                files_modified=["igris/utils/helpers.py"],
            )
        assert ok is True
        assert reasons == []

    def test_gate_unavailable_does_not_crash(self, tmp_path):
        """If SelfModificationGate import fails, gate is skipped (non-blocking)."""
        supervisor = _make_supervisor(str(tmp_path))

        with patch(
            "igris.core.self_modification_gate.SelfModificationGate",
            side_effect=ImportError("not available"),
        ):
            # Should not raise
            ok, reasons = supervisor._preapply_quality_gate(
                goal="fix something",
                diff_text="--- a/igris/utils/helpers.py\n+a line",
                files_modified=["igris/utils/helpers.py"],
            )
        # Gate failure is non-blocking — ok should still be determined by other checks
        assert isinstance(ok, bool)


class TestRegressionQualityGate:
    """Existing quality gate logic must still work after our change."""

    def test_goal_mentions_tests_but_no_test_file(self, tmp_path):
        """Regression: goal_mentions_tests_but_no_test_file_touched still fires."""
        supervisor = _make_supervisor(str(tmp_path))
        mock_gate_result = MagicMock()
        mock_gate_result.approved = True
        mock_gate_result.touched_core = []
        mock_gate_result.reason = "no core files touched"

        with patch(
            "igris.core.self_modification_gate.SelfModificationGate.check",
            return_value=mock_gate_result,
        ):
            ok, reasons = supervisor._preapply_quality_gate(
                goal="fix pytest tests",
                diff_text="--- a/igris/core/foo.py\n+++ b/igris/core/foo.py\n+# no test file",
                files_modified=["igris/core/foo.py"],
            )
        assert ok is False
        assert any("goal_mentions_tests" in r for r in reasons)

    def test_stub_pattern_blocked(self, tmp_path):
        """Regression: stub_pattern_detected_in_diff still fires."""
        supervisor = _make_supervisor(str(tmp_path))
        mock_gate_result = MagicMock()
        mock_gate_result.approved = True
        mock_gate_result.touched_core = []
        mock_gate_result.reason = "no core files touched"

        with patch(
            "igris.core.self_modification_gate.SelfModificationGate.check",
            return_value=mock_gate_result,
        ):
            ok, reasons = supervisor._preapply_quality_gate(
                goal="add feature",
                diff_text="--- a/igris/core/foo.py\n+++ b/igris/core/foo.py\n+    pass\n# placeholder",
                files_modified=["igris/core/foo.py"],
            )
        assert ok is False
        assert any("stub_pattern" in r for r in reasons)

    def test_is_now_instance_method(self, tmp_path):
        """_preapply_quality_gate must be callable on the instance."""
        supervisor = _make_supervisor(str(tmp_path))
        assert hasattr(supervisor, "_preapply_quality_gate")
        assert callable(supervisor._preapply_quality_gate)


def _blocking_import(blocked_module):
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == blocked_module or name.startswith(blocked_module):
            raise ImportError(f"Simulated import failure: {name}")
        return real_import(name, *args, **kwargs)

    return mock_import


class TestFailClosedForCoreFiles:
    """_preapply_quality_gate must be fail-closed for core files when gate is unavailable."""

    def test_core_file_gate_import_failure_is_blocked(self, tmp_path, monkeypatch):
        """Core file + gate import failure → blocked (fail-closed)."""
        supervisor = _make_supervisor(str(tmp_path))
        with patch(
            "igris.core.self_modification_gate.SelfModificationGate",
            side_effect=ImportError("Simulated import failure"),
        ):
            ok, reasons = supervisor._preapply_quality_gate(
                goal="fix core",
                diff_text="--- a/igris/core/agent_reasoning_loop.py\n+fix",
                files_modified=["igris/core/agent_reasoning_loop.py"],
            )
        assert not ok
        assert any(
            "blocked" in r.lower() or "fail-closed" in r.lower() or "unavailable_core" in r
            for r in reasons
        )

    def test_non_core_file_gate_import_failure_is_degraded(self, tmp_path, monkeypatch):
        """Non-core file + gate import failure → non-blocking (degraded-safe)."""
        supervisor = _make_supervisor(str(tmp_path))
        with patch(
            "igris.core.self_modification_gate.SelfModificationGate",
            side_effect=ImportError("Simulated import failure"),
        ):
            ok, reasons = supervisor._preapply_quality_gate(
                goal="fix output",
                diff_text="--- a/reports/output.txt\n+fix",
                files_modified=["reports/output.txt"],
            )
        assert ok
        assert not any("unavailable_core" in r for r in reasons)

    def test_core_file_gate_ok_blocks_on_gate_denial(self, tmp_path):
        """Core file + gate ok + gate returns approved=False → blocked."""
        supervisor = _make_supervisor(str(tmp_path))
        mock_gate_result = MagicMock()
        mock_gate_result.approved = False
        mock_gate_result.touched_core = ["igris/core/agent_reasoning_loop.py"]
        mock_gate_result.reason = "test failure"

        with patch(
            "igris.core.self_modification_gate.SelfModificationGate.check",
            return_value=mock_gate_result,
        ):
            ok, reasons = supervisor._preapply_quality_gate(
                goal="fix core",
                diff_text="--- a/igris/core/agent_reasoning_loop.py\n+fix",
                files_modified=["igris/core/agent_reasoning_loop.py"],
            )
        assert not ok
        assert any("self_modification_gate_blocked" in r for r in reasons)

    def test_per_file_gate_core_import_failure_blocked(self, tmp_path):
        """_preapply_quality_gate_file: core file + ImportError → blocked."""
        supervisor = _make_supervisor(str(tmp_path))
        with patch(
            "igris.core.self_modification_gate.SelfModificationGate",
            side_effect=ImportError("not available"),
        ):
            allowed, reason = supervisor._preapply_quality_gate_file(
                "igris/core/agent_reasoning_loop.py", "patch"
            )
        assert not allowed
        assert "fail-closed" in reason.lower() or "blocked" in reason.lower()

    def test_per_file_gate_non_core_import_failure_degraded(self, tmp_path):
        """_preapply_quality_gate_file: non-core file + ImportError → degraded-safe."""
        supervisor = _make_supervisor(str(tmp_path))
        with patch(
            "igris.core.self_modification_gate.SelfModificationGate",
            side_effect=ImportError("not available"),
        ):
            allowed, reason = supervisor._preapply_quality_gate_file(
                "reports/output.txt", "patch"
            )
        assert allowed
        assert "degraded" in reason.lower() or "non_core" in reason.lower()
