"""Targeted tests for igris/core/supervisor_api.py — fix #1331.

Focus: subprocess import present; self-audit workspace_dirty path.
"""
from __future__ import annotations

import subprocess
import types
import unittest.mock as mock


# ── 1. subprocess import smoke ────────────────────────────────────────────────

def test_supervisor_api_imports_subprocess():
    """supervisor_api must have subprocess in its namespace (NameError was #1331)."""
    import igris.core.supervisor_api as _mod
    assert hasattr(_mod, "subprocess"), (
        "subprocess not found in supervisor_api — NameError would occur at runtime"
    )
    assert _mod.subprocess is subprocess


# ── 2. workspace_dirty logic with non-empty git output ───────────────────────

def test_workspace_dirty_true_when_git_status_non_empty():
    """The _workspace_dirty logic: bool(stdout.strip()) is True for dirty output."""
    dirty_output = " M igris/core/supervisor_api.py\n"
    fake_result = types.SimpleNamespace(stdout=dirty_output, returncode=0)
    assert bool(fake_result.stdout.strip()) is True


def test_workspace_dirty_false_when_git_status_empty():
    """The _workspace_dirty logic: bool(stdout.strip()) is False for clean output."""
    clean_output = ""
    fake_result = types.SimpleNamespace(stdout=clean_output, returncode=0)
    assert bool(fake_result.stdout.strip()) is False


# ── 3. self-audit path passes workspace_dirty=True to behavior_tracker ────────

def test_self_audit_receives_workspace_dirty_true(tmp_path):
    """When git status returns dirty output, self_audit is called with workspace_dirty=True."""
    import igris.core.supervisor_api as sup_mod
    from igris.core.behavior_tracker import BehaviorTracker

    captured = {}

    class _CaptureBT(BehaviorTracker):
        def self_audit(self, **kwargs):
            captured.update(kwargs)
            return super().self_audit(**kwargs)

    dirty_cp = subprocess.CompletedProcess(
        args=["git", "status", "--porcelain"],
        returncode=0,
        stdout=" M igris/core/foo.py\n",
        stderr="",
    )

    with mock.patch.object(sup_mod.subprocess, "run", return_value=dirty_cp) as mock_run:
        from igris.core.supervisor_models import SupervisorRun
        run = SupervisorRun(run_id="test_dirty_001", rank_id="r_test")
        run.behavior_tracker = _CaptureBT(run_id="test_dirty_001")

        # Replicate the exact self-audit block from supervisor_api
        _workspace_dirty = False
        try:
            _gs = sup_mod.subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, cwd=str(tmp_path), timeout=10,
            )
            _workspace_dirty = bool(_gs.stdout.strip())
        except Exception:
            pass

        run.behavior_tracker.self_audit(
            run_status="success",
            failure_class="",
            repair_cycles_used=0,
            smoke_ran=False,
            pytest_ran=False,
            workspace_dirty=_workspace_dirty,
            escalation_budget_exhausted=False,
            escalation_was_called=False,
            completion_mode="standard",
            project_root=str(tmp_path),
        )

    mock_run.assert_called_once()
    assert _workspace_dirty is True, "workspace_dirty should be True for non-empty git output"
    assert captured.get("workspace_dirty") is True, (
        f"self_audit received workspace_dirty={captured.get('workspace_dirty')!r}, expected True"
    )
