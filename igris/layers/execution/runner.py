"""Safe command runner for IGRIS_GPT."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

from igris.layers.execution.safe_commands import ALLOWED_COMMANDS
from igris.models.config import CONFIG


class CommandError(Exception):
    """Raised when a requested safe command cannot be executed."""

def _project_root() -> Path:
    root = Path(CONFIG.project_root)
    if root.exists() and root.is_dir():
        return root
    return Path.cwd()


def _run_command(command: List[str], cwd: Path, timeout: int = 30) -> Dict[str, object]:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": 124,
            "stdout": exc.stdout or "",
            "stderr": "Command timed out",
        }
    except Exception as exc:
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": str(exc),
        }


def _windows_command_for(command_id: str, command: List[str]) -> List[str]:
    if command_id == "list_files":
        return ["cmd", "/c", "dir", "/b"]
    if command_id == "git_status_short":
        return ["git", "status", "--short"]
    if command_id == "git_log_recent":
        return ["git", "log", "--oneline", "-10"]
    if command_id == "run_tests":
        return [sys.executable, "-m", "pytest", "-q"]
    return command


def run_safe_command(command_id: str) -> Dict[str, object]:
    """Run an allowlisted command by ID.

    This is intentionally not a free shell. Only commands listed in
    safe_commands.ALLOWED_COMMANDS can be executed.
    """
    if command_id not in ALLOWED_COMMANDS:
        return {
            "returncode": 126,
            "stdout": "",
            "stderr": f"Command not allowed: {command_id}",
        }

    command = list(ALLOWED_COMMANDS[command_id])
    if platform.system().lower().startswith("win"):
        command = _windows_command_for(command_id, command)

    return _run_command(command, cwd=_project_root(), timeout=30)


def run_tests() -> Dict[str, object]:
    """Run the project test suite with pytest."""
    return _run_command([sys.executable, "-m", "pytest", "-q"], cwd=Path.cwd(), timeout=120)

