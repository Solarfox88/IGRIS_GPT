"""Tests for loop checkpointing and graceful shutdown (#1321)."""
import json
import os
import time
from pathlib import Path

import pytest

from igris.core.loop_checkpoint_manager import (
    LoopCheckpointManager,
    GracefulShutdownHandler,
    StepWatchdog,
)


class TestLoopCheckpointManager:
    """Unit tests for LoopCheckpointManager."""

    def test_save_and_load_checkpoint(self, tmp_path: Path) -> None:
        """Saving a checkpoint then loading it should return the same data."""
        mgr = LoopCheckpointManager(str(tmp_path), mission_id="m1")
        state = {"world_state": {"key": "value"}, "errors": []}
        mgr.save(step_num=5, state=state)

        loaded = mgr.load()
        assert loaded is not None
        assert loaded["step_num"] == 5
        assert loaded["state"]["world_state"]["key"] == "value"
        assert loaded["mission_id"] == "m1"

    def test_load_returns_none_when_no_checkpoint(self, tmp_path: Path) -> None:
        """Loading when no checkpoint exists should return None."""
        mgr = LoopCheckpointManager(str(tmp_path), mission_id="m2")
        assert mgr.load() is None

    def test_clear_removes_checkpoint(self, tmp_path: Path) -> None:
        """clear() should remove the checkpoint file."""
        mgr = LoopCheckpointManager(str(tmp_path), mission_id="m3")
        mgr.save(step_num=1, state={"x": 1})
        assert mgr.load() is not None
        mgr.clear()
        assert mgr.load() is None

    def test_checkpoint_is_atomic(self, tmp_path: Path) -> None:
        """Checkpoint should be written atomically (no .tmp file left)."""
        mgr = LoopCheckpointManager(str(tmp_path), mission_id="m4")
        mgr.save(step_num=1, state={})
        # No .tmp file should exist
        assert not (mgr.checkpoint_dir / "loop_m4.json.tmp").exists()
        # The actual checkpoint should exist
        assert (mgr.checkpoint_dir / "loop_m4.json").exists()

    def test_list_checkpoints(self, tmp_path: Path) -> None:
        """list_checkpoints should return all checkpoints."""
        mgr1 = LoopCheckpointManager(str(tmp_path), mission_id="a")
        mgr1.save(step_num=1, state={})
        mgr2 = LoopCheckpointManager(str(tmp_path), mission_id="b")
        mgr2.save(step_num=2, state={})

        # List from the same directory
        lister = LoopCheckpointManager(str(tmp_path), mission_id="lister")
        checkpoints = lister.list_checkpoints()
        assert len(checkpoints) == 2
        mission_ids = [c["mission_id"] for c in checkpoints]
        assert "a" in mission_ids
        assert "b" in mission_ids

    def test_corrupted_checkpoint_returns_none(self, tmp_path: Path) -> None:
        """A corrupted checkpoint file should return None, not raise."""
        mgr = LoopCheckpointManager(str(tmp_path), mission_id="corrupt")
        path = mgr._checkpoint_path()
        path.write_text("not valid json{{{", encoding="utf-8")
        assert mgr.load() is None

    def test_checkpoint_preserves_complex_state(self, tmp_path: Path) -> None:
        """Checkpoint should handle nested dicts and lists."""
        mgr = LoopCheckpointManager(str(tmp_path), mission_id="complex")
        state = {
            "world_state": {
                "nested": {"deep": [1, 2, 3]},
                "list": ["a", "b", "c"],
            },
            "steps_without_write": 5,
            "files_modified": ["file1.py", "file2.py"],
        }
        mgr.save(step_num=10, state=state)
        loaded = mgr.load()
        assert loaded is not None
        assert loaded["state"]["world_state"]["nested"]["deep"] == [1, 2, 3]
        assert loaded["state"]["files_modified"] == ["file1.py", "file2.py"]

    def test_checkpoint_dir_created_automatically(self, tmp_path: Path) -> None:
        """The checkpoint directory should be created if it doesn't exist."""
        root = tmp_path / "subdir" / "deeper"
        mgr = LoopCheckpointManager(str(root), mission_id="m5")
        assert mgr.checkpoint_dir.exists()
        mgr.save(step_num=1, state={})
        assert mgr.load() is not None


class TestGracefulShutdownHandler:
    """Unit tests for GracefulShutdownHandler."""

    def test_should_shutdown_initially_false(self) -> None:
        """should_shutdown should be False initially."""
        handler = GracefulShutdownHandler()
        assert handler.should_shutdown is False

    def test_reset_clears_shutdown_flag(self) -> None:
        """reset() should clear the shutdown flag."""
        handler = GracefulShutdownHandler()
        handler._should_shutdown.set()
        assert handler.should_shutdown is True
        handler.reset()
        assert handler.should_shutdown is False

    def test_install_and_uninstall(self) -> None:
        """install() and uninstall() should not raise."""
        handler = GracefulShutdownHandler()
        handler.install()
        handler.uninstall()
        # Should not raise

    def test_on_shutdown_callback_called(self) -> None:
        """The on_shutdown callback should be called when signal is received."""
        called = []
        handler = GracefulShutdownHandler(on_shutdown=lambda: called.append(True))
        handler._should_shutdown.set()
        # Simulate the signal handler
        handler._handle_signal(15, None)
        assert called == [True]
        assert handler.should_shutdown is True


class TestStepWatchdog:
    """Unit tests for StepWatchdog."""

    def test_watchdog_does_not_fire_within_timeout(self) -> None:
        """Watchdog should not report timeout if step completes in time."""
        watchdog = StepWatchdog(timeout=10)
        watchdog.start(step_num=1)
        time.sleep(0.01)
        elapsed = watchdog.stop()
        assert watchdog.timed_out is False
        assert elapsed > 0

    def test_watchdog_fires_after_timeout(self) -> None:
        """Watchdog should report timeout if step takes too long."""
        watchdog = StepWatchdog(timeout=1)  # 1 second for test
        watchdog.start(step_num=1)
        time.sleep(1.2)
        assert watchdog.timed_out is True
        watchdog.stop()

    def test_watchdog_stop_returns_elapsed(self) -> None:
        """stop() should return the elapsed time."""
        watchdog = StepWatchdog(timeout=100)
        watchdog.start(step_num=1)
        time.sleep(0.05)
        elapsed = watchdog.stop()
        assert elapsed >= 0.04  # Allow some tolerance

    def test_watchdog_can_be_reused(self) -> None:
        """Watchdog should be reusable for multiple steps."""
        watchdog = StepWatchdog(timeout=100)
        watchdog.start(step_num=1)
        watchdog.stop()
        watchdog.start(step_num=2)
        assert watchdog.timed_out is False
        watchdog.stop()

    def test_watchdog_zero_timeout_disables_timer(self) -> None:
        """A timeout of 0 should disable the watchdog timer."""
        watchdog = StepWatchdog(timeout=0)
        watchdog.start(step_num=1)
        time.sleep(0.01)
        assert watchdog.timed_out is False
        watchdog.stop()
