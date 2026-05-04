"""Read-only Git status helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List

from igris.models.config import CONFIG
from igris.models.report import GitStatusResponse


def _repo_root() -> Path:
    root = Path(CONFIG.project_root)
    if root.exists() and root.is_dir():
        return root
    return Path.cwd()


def _run_git(args: List[str], cwd: Path | None = None) -> str:
    cwd = cwd or _repo_root()
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def get_git_info() -> GitStatusResponse:
    root = _repo_root()

    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], root) or "unknown"
    remote = _run_git(["remote", "get-url", "origin"], root) or ""
    head = _run_git(["log", "-1", "--oneline"], root) or ""

    status = _run_git(["status", "--short"], root)
    changed = [line for line in status.splitlines() if line.strip()]
    dirty = bool(changed)

    return GitStatusResponse(
        branch=branch,
        remote=remote,
        dirty=dirty,
        changed=changed,
        head=head,
    )
