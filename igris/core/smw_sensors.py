from __future__ import annotations

import asyncio
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from igris.core.self_repair_supervisor import list_active_supervised_runs, list_supervised_runs


@dataclass
class SystemSnapshot:
    timestamp: float
    igris_pid: Optional[int]
    igris_port_in_use: bool
    port_conflict: bool
    active_runs: List[str]
    last_run_id: Optional[str]
    last_run_status: Optional[str]
    last_run_failure_class: Optional[str]
    last_run_started_at: Optional[float]
    seconds_since_last_run: Optional[float]
    dirty_files: List[str]
    tracked_dirty: bool
    untracked_files: List[str]
    current_branch: str
    recent_log_lines: List[str]
    skipped_issues: List[int]
    avg_repair_cycles: float
    escalation_rate: float
    failure_class_distribution: Dict[str, int]


def _safe_run(cmd: list[str], cwd: Optional[str] = None) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=10)
        return p.stdout if p.returncode == 0 else ""
    except Exception:
        return ""


async def take_snapshot(project_root: str) -> SystemSnapshot:
    loop = asyncio.get_running_loop()
    now = time.time()

    async def git_status() -> tuple[list[str], bool, list[str]]:
        out = await loop.run_in_executor(None, lambda: _safe_run(["git", "status", "--porcelain"], cwd=project_root))
        lines = [l for l in out.splitlines() if l.strip()]
        untracked = [l for l in lines if l.startswith("??")]
        tracked_dirty = any(not l.startswith("??") for l in lines)
        return lines, tracked_dirty, untracked

    async def port_state() -> tuple[Optional[int], bool, bool]:
        out = await loop.run_in_executor(None, lambda: _safe_run(["ss", "-tlnp"]))
        lines = [l for l in out.splitlines() if ":7778" in l]
        pids: list[int] = []
        for line in lines:
            if "pid=" in line:
                try:
                    pid = int(line.split("pid=")[1].split(",")[0].split(")")[0])
                    pids.append(pid)
                except Exception:
                    pass
        return (pids[0] if pids else None, bool(lines), len(set(pids)) > 1)

    async def branch() -> str:
        out = await loop.run_in_executor(None, lambda: _safe_run(["git", "branch", "--show-current"], cwd=project_root))
        return out.strip() or "unknown"

    async def runs_data() -> tuple[list[str], Optional[str], Optional[str], Optional[str], Optional[float], Optional[float], float, float, Dict[str, int]]:
        try:
            active = list_active_supervised_runs()
            all_runs = list_supervised_runs()
            active_ids = [r.run_id for r in active]
            last = all_runs[-1] if all_runs else None
            since = None if active_ids else (now - float(getattr(last, "started_at", now)) if last and getattr(last, "started_at", None) else None)
            recent = all_runs[-20:]
            if recent:
                avg_repair = sum(float(getattr(r, "repair_cycles_used", 0) or 0) for r in recent) / len(recent)
                escal = sum(1 for r in recent if float(getattr(r, "api_escalations_used", 0) or 0) > 0) / len(recent)
            else:
                avg_repair, escal = 0.0, 0.0
            dist: Dict[str, int] = {}
            for r in recent:
                fc = str(getattr(r, "failure_class", "") or "none")
                dist[fc] = dist.get(fc, 0) + 1
            return active_ids, getattr(last, "run_id", None), getattr(last, "status", None), getattr(last, "failure_class", None), getattr(last, "started_at", None), since, avg_repair, escal, dist
        except Exception:
            return [], None, None, None, None, None, 0.0, 0.0, {}

    async def logs() -> list[str]:
        try:
            logf = Path(project_root) / "logs" / "igris.log"
            if not logf.exists():
                return []
            lines = logf.read_text(encoding="utf-8", errors="replace").splitlines()
            filtered = [l for l in lines if "watchdog" in l.lower() and "HTTP" not in l][-20:]
            return filtered
        except Exception:
            return []

    async def skipped() -> list[int]:
        try:
            p = Path(project_root) / ".igris" / "watchdog_skipped_issues.json"
            if p.exists():
                raw = json.loads(p.read_text(encoding="utf-8"))
                return [int(x) for x in raw if isinstance(x, int) or str(x).isdigit()]
        except Exception:
            pass
        return []

    (dirty_files, tracked_dirty, untracked_files), (igris_pid, igris_port_in_use, port_conflict), current_branch, runs, recent_log_lines, skipped_issues = await asyncio.gather(
        git_status(), port_state(), branch(), runs_data(), logs(), skipped()
    )
    active_runs, last_run_id, last_run_status, last_run_failure_class, last_run_started_at, seconds_since_last_run, avg_repair_cycles, escalation_rate, failure_class_distribution = runs
    return SystemSnapshot(now, igris_pid, igris_port_in_use, port_conflict, active_runs, last_run_id, last_run_status, last_run_failure_class, last_run_started_at, seconds_since_last_run, dirty_files, tracked_dirty, untracked_files, current_branch, recent_log_lines, skipped_issues, avg_repair_cycles, escalation_rate, failure_class_distribution)
