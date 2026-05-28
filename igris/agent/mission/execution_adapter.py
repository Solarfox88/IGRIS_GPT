from __future__ import annotations

import re
import subprocess
from typing import Dict, Iterable, Optional, Set, Tuple, List

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
    evidence_depth: str = "missing_evidence",
    evidence_tags: Optional[List[str]] = None,
) -> MissionExecutionResult:
    return MissionExecutionResult(
        action_id=action_id,
        command=command,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        success=success,
        evidence=evidence,
        evidence_depth=evidence_depth,
        evidence_tags=list(evidence_tags or []),
    )


def _classify_evidence(
    *,
    command: str,
    evidence: str,
    success: bool,
    stdout: str,
    stderr: str,
    returncode: Optional[int],
) -> Tuple[str, List[str]]:
    tags: List[str] = []
    cmd = (command or "").strip()
    low = cmd.lower()
    out = (stdout or "") + "\n" + (stderr or "")

    if "missing-command" in evidence:
        return "missing_evidence", ["missing_evidence"]
    if "blocked-" in evidence:
        return "missing_evidence", ["missing_evidence"]
    if evidence.startswith("dry-run"):
        tags.extend(["command_executed", "dry_run_evidence"])
        return "shallow_evidence", tags

    if cmd:
        tags.append("command_executed")

    if any(tok in low for tok in ("pytest", "unittest", "nosetests")):
        tags.append("test_executed")
        if success and returncode == 0:
            tags.append("test_passed")

    if re.search(r"(>>|>|tee\s+)", low) or any(tok in low for tok in ("touch ", "mv ", "cp ")):
        tags.extend(["artifact_changed", "file_updated"])

    if any(tok in low for tok in ("report", ".md", ".json")) and re.search(r"(>>|>|tee\s+)", low):
        tags.append("report_updated")

    if "?? " in out or "\nM " in out or out.startswith("M "):
        if "artifact_changed" not in tags:
            tags.append("artifact_changed")
        if "file_updated" not in tags:
            tags.append("file_updated")

    if not success:
        if not tags:
            tags.append("missing_evidence")
            return "missing_evidence", tags
        return "shallow_evidence", tags

    sufficient_markers = {"test_passed", "artifact_changed", "report_updated"}
    if any(marker in tags for marker in sufficient_markers):
        return "sufficient_evidence", tags
    if tags:
        return "shallow_evidence", tags
    return "missing_evidence", ["missing_evidence"]


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
            evidence = "missing-command"
            depth, tags = _classify_evidence(
                command="",
                evidence=evidence,
                success=False,
                stdout="",
                stderr="missing command mapping",
                returncode=None,
            )
            results.append(
                _result(
                    action.id,
                    "",
                    success=False,
                    evidence=evidence,
                    stderr="missing command mapping",
                    evidence_depth=depth,
                    evidence_tags=tags,
                )
            )
            continue

        unsafe_pattern = _is_unsafe_command(cmd)
        if unsafe_pattern:
            evidence = "blocked-unsafe-command"
            stderr = f"blocked unsafe command by policy pattern '{unsafe_pattern}'"
            depth, tags = _classify_evidence(
                command=cmd,
                evidence=evidence,
                success=False,
                stdout="",
                stderr=stderr,
                returncode=None,
            )
            results.append(
                _result(
                    action.id,
                    cmd,
                    success=False,
                    evidence=evidence,
                    stderr=stderr,
                    returncode=None,
                    evidence_depth=depth,
                    evidence_tags=tags,
                )
            )
            continue

        if cmd in seen and not differentiator:
            evidence = "blocked-blind-retry"
            stderr = "blocked blind retry: missing differentiator"
            depth, tags = _classify_evidence(
                command=cmd,
                evidence=evidence,
                success=False,
                stdout="",
                stderr=stderr,
                returncode=None,
            )
            results.append(
                _result(
                    action.id,
                    cmd,
                    success=False,
                    evidence=evidence,
                    stderr=stderr,
                    returncode=None,
                    evidence_depth=depth,
                    evidence_tags=tags,
                )
            )
            continue

        seen.add(cmd)
        if dry_run:
            evidence = "dry-run-differentiated" if differentiator else "dry-run"
            stdout = "dry-run execution simulated"
            depth, tags = _classify_evidence(
                command=cmd,
                evidence=evidence,
                success=True,
                stdout=stdout,
                stderr="",
                returncode=0,
            )
            results.append(
                _result(
                    action.id,
                    cmd,
                    success=True,
                    evidence=evidence,
                    stdout=stdout,
                    stderr="",
                    returncode=0,
                    evidence_depth=depth,
                    evidence_tags=tags,
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
        evidence = "process-executed-differentiated" if differentiator else "process-executed"
        depth, tags = _classify_evidence(
            command=cmd,
            evidence=evidence,
            success=(proc.returncode == 0),
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            returncode=proc.returncode,
        )
        results.append(
            _result(
                action.id,
                cmd,
                success=(proc.returncode == 0),
                evidence=evidence,
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                returncode=proc.returncode,
                evidence_depth=depth,
                evidence_tags=tags,
            )
        )
    mission.execution_results = results
    return mission
