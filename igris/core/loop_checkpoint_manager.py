"""Loop state checkpointing and crash recovery (#1321).

Provides checkpoint persistence for the agent reasoning loop:
- Checkpoint JSON written to .igris/checkpoints/ at each step
- Recovery on restart: detects checkpoint, offers resume
- Graceful shutdown handler (SIGTERM/SIGINT)
- Watchdog timeout for long-running steps

Usage:
    from igris.core.loop_checkpoint_manager import LoopCheckpointManager

    ckpt = LoopCheckpointManager(project_root, mission_id="m123")
    ckpt.save(step_num, state_dict)
    # ... on restart ...
    saved = ckpt.load()
    if saved:
        resume_from = saved["step_num"]
"""
from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

_log = logging.getLogger(__name__)

# Default watchdog timeout in seconds (configurable via env)
_DEFAULT_WATCHDOG_TIMEOUT = int(os.environ.get("IGRIS_LOOP_WATCHDOG_TIMEOUT", "300"))


class LoopCheckpointManager:
    """Manages loop state checkpoints for crash recovery.

    Checkpoints are written as JSON files in ``.igris/checkpoints/``.
    Each checkpoint contains the step number, world state, and metadata.
    """

    def __init__(
        self,
        project_root: str,
        mission_id: str = "",
        checkpoint_dir: Optional[str] = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.mission_id = mission_id
        if checkpoint_dir:
            self.checkpoint_dir = Path(checkpoint_dir)
        else:
            self.checkpoint_dir = self.project_root / ".igris" / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _checkpoint_path(self) -> Path:
        """Return the checkpoint file path for this mission."""
        safe_id = self.mission_id or "default"
        return self.checkpoint_dir / f"loop_{safe_id}.json"

    def save(self, step_num: int, state: Dict[str, Any]) -> Path:
        """Save a checkpoint of the loop state.

        Args:
            step_num: Current step number (1-based)
            state: Serializable state dict (world_state, errors, etc.)

        Returns:
            Path to the checkpoint file
        """
        checkpoint = {
            "mission_id": self.mission_id,
            "step_num": step_num,
            "state": state,
            "timestamp": time.time(),
        }
        path = self._checkpoint_path()
        with self._lock:
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(checkpoint, indent=2, default=str),
                encoding="utf-8",
            )
            tmp_path.replace(path)  # Atomic write
        _log.debug(
            "loop_checkpoint[%s]: saved checkpoint at step %d",
            self.mission_id,
            step_num,
        )
        return path

    def load(self) -> Optional[Dict[str, Any]]:
        """Load a checkpoint if one exists.

        Returns:
            Checkpoint dict with step_num, state, timestamp, or None
        """
        path = self._checkpoint_path()
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            _log.info(
                "loop_checkpoint[%s]: loaded checkpoint from step %d",
                self.mission_id,
                data.get("step_num", 0),
            )
            return data
        except (json.JSONDecodeError, OSError) as exc:
            _log.warning(
                "loop_checkpoint[%s]: failed to load checkpoint: %s",
                self.mission_id,
                exc,
            )
            return None

    def clear(self) -> None:
        """Remove the checkpoint file (called after successful completion)."""
        path = self._checkpoint_path()
        with self._lock:
            if path.exists():
                path.unlink()
                _log.debug(
                    "loop_checkpoint[%s]: cleared checkpoint",
                    self.mission_id,
                )

    def list_checkpoints(self) -> list[Dict[str, Any]]:
        """List all checkpoints in the checkpoint directory."""
        checkpoints = []
        for p in sorted(self.checkpoint_dir.glob("loop_*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                checkpoints.append({
                    "file": str(p),
                    "mission_id": data.get("mission_id", ""),
                    "step_num": data.get("step_num", 0),
                    "timestamp": data.get("timestamp", 0),
                })
            except (json.JSONDecodeError, OSError):
                continue
        return checkpoints


class GracefulShutdownHandler:
    """Handles SIGTERM/SIGINT for graceful shutdown.

    Registers signal handlers that set a shutdown flag.
    The reasoning loop checks this flag between steps and
    exits gracefully (completing the current step, persisting state).

    Usage:
        handler = GracefulShutdownHandler()
        handler.install()
        # ... in loop:
        if handler.should_shutdown:
            break
    """

    def __init__(self, on_shutdown: Optional[Callable[[], None]] = None) -> None:
        self._should_shutdown = threading.Event()
        self._on_shutdown = on_shutdown
        self._installed = False
        self._original_handlers: Dict[int, Any] = {}

    @property
    def should_shutdown(self) -> bool:
        """True if a shutdown signal has been received."""
        return self._should_shutdown.is_set()

    def install(self) -> None:
        """Install signal handlers for SIGTERM and SIGINT.

        Only works in the main thread. If called from a non-main thread
        (e.g. in tests), this is a no-op.
        """
        if self._installed:
            return
        # signal.signal() only works in the main thread
        if threading.current_thread() is not threading.main_thread():
            _log.debug("graceful_shutdown: skipped signal handler install (non-main thread)")
            return
        for sig in (signal.SIGTERM, signal.SIGINT):
            self._original_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, self._handle_signal)
        self._installed = True
        _log.info("graceful_shutdown: signal handlers installed")

    def uninstall(self) -> None:
        """Restore original signal handlers."""
        if not self._installed:
            return
        for sig, handler in self._original_handlers.items():
            signal.signal(sig, handler)
        self._installed = False
        _log.debug("graceful_shutdown: signal handlers restored")

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Signal handler — sets the shutdown flag."""
        _log.info(
            "graceful_shutdown: received signal %d, requesting shutdown",
            signum,
        )
        self._should_shutdown.set()
        if self._on_shutdown:
            try:
                self._on_shutdown()
            except Exception:
                _log.error("graceful_shutdown: on_shutdown callback failed", exc_info=True)

    def reset(self) -> None:
        """Reset the shutdown flag (for testing)."""
        self._should_shutdown.clear()


class StepWatchdog:
    """Watchdog timer for long-running loop steps.

    If a step takes longer than the configured timeout, the watchdog
    fires and records diagnostic information.

    Usage:
        watchdog = StepWatchdog(timeout=300)
        watchdog.start(step_num=5)
        try:
            # ... execute step ...
        finally:
            elapsed = watchdog.stop()
            if watchdog.timed_out:
                _log.warning("step %d timed out after %.1fs", 5, elapsed)
    """

    def __init__(self, timeout: int = _DEFAULT_WATCHDOG_TIMEOUT) -> None:
        self.timeout = timeout
        self._start_time: Optional[float] = None
        self._timed_out = False
        self._timer: Optional[threading.Timer] = None
        self._step_num: int = 0

    @property
    def timed_out(self) -> bool:
        """True if the last step exceeded the timeout."""
        return self._timed_out

    def start(self, step_num: int = 0) -> None:
        """Start the watchdog for a new step."""
        self._step_num = step_num
        self._start_time = time.monotonic()
        self._timed_out = False
        if self._timer:
            self._timer.cancel()
        if self.timeout > 0:
            self._timer = threading.Timer(self.timeout, self._on_timeout)
            self._timer.daemon = True
            self._timer.start()

    def stop(self) -> float:
        """Stop the watchdog and return elapsed time in seconds."""
        if self._timer:
            self._timer.cancel()
            self._timer = None
        elapsed = 0.0
        if self._start_time is not None:
            elapsed = time.monotonic() - self._start_time
            self._start_time = None
        return elapsed

    def _on_timeout(self) -> None:
        """Called when the watchdog timer fires."""
        self._timed_out = True
        _log.error(
            "step_watchdog: step %d exceeded timeout of %ds",
            self._step_num,
            self.timeout,
        )
