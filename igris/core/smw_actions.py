from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List


@dataclass
class ActionResult:
    action_name: str
    success: bool
    output: str
    duration_seconds: float


async def git_clean_root(project_root: str) -> ActionResult:
    t = time.time()
    p = subprocess.run(["git", "clean", "-fd", "."], cwd=project_root, capture_output=True, text=True)
    return ActionResult("git_clean_root", p.returncode == 0, p.stdout + p.stderr, time.time() - t)


async def git_restore_all(project_root: str) -> ActionResult:
    t = time.time()
    p = subprocess.run(["git", "restore", "--worktree", "--staged", "."], cwd=project_root, capture_output=True, text=True)
    return ActionResult("git_restore_all", p.returncode == 0, p.stdout + p.stderr, time.time() - t)


async def wait_and_recheck(seconds: int) -> ActionResult:
    t = time.time()
    await asyncio.sleep(seconds)
    return ActionResult("wait_and_recheck", True, f"waited {seconds}s", time.time() - t)


async def kill_stale_process(port: int = 7778) -> ActionResult:
    t = time.time()
    out = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True)
    killed = []
    for line in out.stdout.splitlines():
        if f":{port}" in line and "python" in line and "pid=" in line:
            pid = int(line.split("pid=")[1].split(",")[0].split(")")[0])
            if pid != os.getpid():
                os.kill(pid, signal.SIGTERM)
                killed.append(pid)
    return ActionResult("kill_stale_process", True, f"killed={killed}" if killed else "no stale process", time.time() - t)


async def open_diagnostic_issue(project_root: str, pattern_name: str, evidence: str, actions_tried: List[str]) -> ActionResult:
    t = time.time()
    title = f"diag(smw): incident {pattern_name}"
    body = f"Pattern: {pattern_name}\n\nEvidence:\n{evidence}\n\nActions tried: {', '.join(actions_tried)}"
    p = subprocess.run(["gh", "issue", "create", "--title", title, "--body", body, "--label", "smw,diagnostic"], cwd=project_root, capture_output=True, text=True)
    return ActionResult("open_diagnostic_issue", p.returncode == 0, p.stdout + p.stderr + pattern_name, time.time() - t)


async def check_issue_list(project_root: str) -> ActionResult:
    t = time.time()
    p = subprocess.run(["gh", "issue", "list", "--state", "open", "--limit", "20"], cwd=project_root, capture_output=True, text=True)
    return ActionResult("check_issue_list", p.returncode == 0, p.stdout + p.stderr, time.time() - t)


async def restart_igris_service(project_root: str) -> ActionResult:
    t = time.time()
    p = subprocess.run(["systemctl", "restart", "igris"], capture_output=True, text=True)
    if p.returncode != 0:
        return ActionResult("restart_igris_service", False, p.stdout + p.stderr, time.time() - t)
    return ActionResult("restart_igris_service", True, "service restarted", time.time() - t)


async def create_fix_pr(project_root: str, file_path: str, old_content: str, new_content: str, pr_title: str, pr_body: str) -> ActionResult:
    return ActionResult("create_fix_pr", False, "not implemented", 0.0)


async def wait_port_free(port: int = 7778, timeout: int = 30) -> ActionResult:
    t = time.time()
    end = t + timeout
    while time.time() < end:
        out = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True)
        if not any(f":{port}" in ln for ln in out.stdout.splitlines()):
            return ActionResult("wait_port_free", True, "port free", time.time() - t)
        await asyncio.sleep(2)
    return ActionResult("wait_port_free", False, "timeout", time.time() - t)


async def restart_watchdog_cycle(project_root: str) -> ActionResult:
    """Trigger a fresh watchdog cycle by writing the restart-requested sentinel."""
    t = time.time()
    try:
        import pathlib
        sentinel = pathlib.Path(project_root) / ".igris" / "watchdog_restart_requested"
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.touch()
        return ActionResult("restart_watchdog_cycle", True, "watchdog restart sentinel written", time.time() - t)
    except OSError as e:
        return ActionResult("restart_watchdog_cycle", False, str(e), time.time() - t)

async def execute_action(action_name: str, tier: int, dry_run: bool = True, **kwargs: Any) -> ActionResult:
    actions: Dict[str, Callable[..., Any]] = {
        "git_clean_root": git_clean_root,
        "git_restore_all": git_restore_all,
        "wait_and_recheck": wait_and_recheck,
        "kill_stale_process": kill_stale_process,
        "open_diagnostic_issue": open_diagnostic_issue,
        "check_issue_list": check_issue_list,
        "restart_igris_service": restart_igris_service,
        "wait_port_free": wait_port_free,
        "restart_watchdog_cycle": restart_watchdog_cycle,
    }
    if action_name not in actions:
        return ActionResult(action_name, False, "unknown action", 0.0)
    if tier >= 2 and dry_run:
        return ActionResult(action_name, True, "dry_run", 0.0)
    fn = actions[action_name]
    return await fn(**{k: v for k, v in kwargs.items() if k in fn.__code__.co_varnames})
