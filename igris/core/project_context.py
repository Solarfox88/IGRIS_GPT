"""
Project context builder for IGRIS_GPT.

This module provides functions to assemble a lightweight snapshot of
the current project state.  The snapshot can be used by the chat
engine, teacher logic or exposed via an API endpoint to inform
decisions.  It includes information such as the project root, a
truncated file listing, git status, task summary and safety
indicators.  Expensive operations (like reading large files) should
be avoided to keep the snapshot generation cheap.

"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from igris.layers.git_layer.git_status import get_git_info
from igris.core.task_engine import TaskEngine
from igris.core import anti_loop
from igris.models.config import CONFIG


def build_project_snapshot(root: Optional[Path] = None, task_engine: Optional[TaskEngine] = None) -> Dict[str, object]:
    """Assemble a dictionary summarizing the current project context.

    The snapshot includes:
    - root: The absolute path to the project root.
    - file_count: approximate number of files under the root (limited to 1000).
    - top_files: a list of up to 10 top‑level files/directories.
    - git: summary of git status (branch, remote, dirty, changed count, head).
    - tasks: counts of pending/completed/blocked tasks.
    - saturated_families: list of saturated families as determined by anti‑loop.
    - recent_task_families: counts of task families for last 10 tasks.

    :param root: Optional root directory; defaults to CONFIG.project_root.
    :param task_engine: Optional task engine; a new one is created if not provided.
    :returns: A snapshot dictionary.
    """
    root = root or CONFIG.project_root
    ctx: Dict[str, object] = {}
    ctx["root"] = str(root.resolve())
    # Count files (not directories) up to a limit
    file_count = 0
    top_entries: List[str] = []
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            # Only count files; skip .git and caches
            if ".git" in dirnames:
                dirnames.remove(".git")
            if ".igris" in dirnames:
                dirnames.remove(".igris")
            file_count += len(filenames)
            # Collect top level entries only
            rel = os.path.relpath(dirpath, root)
            if rel == ".":
                top_entries = sorted(dirnames + filenames)[:10]
            if file_count > 1000:
                break
    except Exception:
        pass
    ctx["file_count"] = file_count
    ctx["top_entries"] = top_entries
    # Git info
    info = get_git_info()
    ctx["git"] = {
        "branch": info.branch,
        "remote": info.remote,
        "dirty": info.dirty,
        "changed_count": len(info.changed),
        "head": info.head,
    }
    # Tasks summary
    engine = task_engine or TaskEngine()
    pending = sum(1 for t in engine.tasks if t.status.name == "pending")
    completed = sum(1 for t in engine.tasks if t.status.name == "completed")
    blocked = sum(1 for t in engine.tasks if t.status.name == "blocked")
    ctx["tasks"] = {"pending": pending, "completed": completed, "blocked": blocked}
    # Anti‑loop metrics
    counts = anti_loop.compute_family_counts([t.description for t in engine.tasks])
    saturated = anti_loop.saturated_families(counts)
    ctx["saturated_families"] = saturated
    # recent family counts (last 10 tasks)
    last_tasks = engine.tasks[-10:]
    last_counts = anti_loop.compute_family_counts([t.description for t in last_tasks])
    ctx["recent_task_families"] = last_counts
    return ctx