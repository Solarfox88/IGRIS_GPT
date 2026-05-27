from __future__ import annotations

import re
import subprocess
from typing import Dict, Iterable, Optional, Set

from igris.agent.mission.mission_schema import Mission, MissionExecutionResult


_UNSAFE_COMMAND_PATTERNS = (
    r"\brm\s+-rf\b",
    r"\bdd\s+if=",
    r"\bmkfs\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r":\(\)\s*\{",
    r">\s*/dev/sd",
)


def _is_unsafe_command(cmd: str) -> Optional[str]:
    normalized = cmd.strip().lower()
    for pattern in _UNSAFE_COMMAND_PATTERNS:
        if re.search(pattern, normalized):
            return pattern
    return None


def _result(
    action_id: str,
    command: str,
    *,
    success: bool,
    evidence: str,
    stderr: str = "",
    stdout: str = "",
    returncode: Optional[int] = None,
) -> MissionExecutionResult:
    return MissionExecutionResult(
        action_id=action_id,
        command=command,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        success=success,
        evidence=evidence,
    )


def execute_mission_actions(
    mission: Mission,
    command_map: Dict[str, str],
    *,
    dry_run: bool = True,
    max_seconds: int = 30,
    previous_commands: Optional[Iterable[str]] = None,
    differentiator: str = "",
) -> Mission:
    """Execute mapped commands and persist execution evidence in mission."""
    seen: Set[str] = set(previous_commands or [])
    results: list[MissionExecutionResult] = []
    for action in mission.actions:
        cmd = command_map.get(action.id, "").strip()
        if not cmd:
            results.append(
                _result(
                    action.id,
                    "",
                    success=False,
                    evidence="missing-command",
                    stderr="missing command mapping",
                )
            )
            continue

        unsafe_pattern = _is_unsafe_command(cmd)
        if unsafe_pattern:
            results.append(
                _result(
                    action.id,
                    cmd,
                    success=False,
                    evidence="blocked-unsafe-command",
                    stderr=f"blocked unsafe command by policy pattern '{unsafe_pattern}'",
                    returncode=None,
                )
            )
            continue

        if cmd in seen and not differentiator:
            results.append(
                _result(
                    action.id,
                    cmd,
                    success=False,
                    evidence="blocked-blind-retry",
                    stderr="blocked blind retry: missing differentiator",
                    returncode=None,
                )
            )
            continue

        seen.add(cmd)
        if dry_run:
            results.append(
                _result(
                    action.id,
                    cmd,
                    success=True,
                    evidence=(
                        "dry-run-differentiated"
                        if differentiator
                        else "dry-run"
                    ),
                    stdout="dry-run execution simulated",
                    stderr="",
                    returncode=0,
                )
            )
            continue

        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=max_seconds,
            check=False,
        )
        results.append(
            _result(
                action.id,
                cmd,
                success=(proc.returncode == 0),
                evidence=(
                    "process-executed-differentiated"
                    if differentiator
                    else "process-executed"
                ),
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                returncode=proc.returncode,
            )
        )
    mission.execution_results = results
    return mission

