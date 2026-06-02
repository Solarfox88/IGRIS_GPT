from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from igris.core.agent_reasoning_loop import AgentReasoningLoop, LoopResult

logger = logging.getLogger(__name__)


@dataclass
class ParallelTask:
    task_id: str
    goal: str
    max_steps: int = 20
    task_type: str = "code_reasoning"
    preferred_profile: Optional[str] = None
    initial_context: dict = field(default_factory=dict)
    # Epic #1075 — dependency graph support
    depends_on: List[str] = field(default_factory=list)  # task_ids this task waits for
    can_run_parallel: bool = True


@dataclass
class ParallelResult:
    task_id: str
    result: Optional[LoopResult]
    error: Optional[str] = None
    # Epic #1075 — result merge metadata
    merged_files: List[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""

    @property
    def success(self) -> bool:
        return self.result is not None and self.result.status == "finished"


class FileLock:
    """Epic #1075 — File-based lock to prevent concurrent writes to the same path.

    Uses fcntl.flock (Linux/macOS). Acquired with a context manager:

        with FileLock("/path/to/file.py"):
            # safe to write here

    Times out after *timeout_seconds* if the lock cannot be acquired.
    """

    def __init__(self, path: str, timeout_seconds: float = 30.0) -> None:
        self._path = path
        self._lock_path = f"{path}.igris.lock"
        self._timeout = timeout_seconds
        self._fd: Optional[int] = None

    def acquire(self) -> None:
        """Acquire exclusive lock, blocking until *timeout_seconds*."""
        self._fd = os.open(self._lock_path, os.O_CREAT | os.O_WRONLY)
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(self._fd)
                    self._fd = None
                    raise TimeoutError(
                        f"lock_timeout reason_code=parallel_file_lock path={self._path!r} "
                        f"timeout_seconds={self._timeout:g}"
                    )
                time.sleep(0.1)

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
            except Exception:
                pass
            finally:
                self._fd = None
                try:
                    os.unlink(self._lock_path)
                except FileNotFoundError:
                    pass

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, *args: Any) -> None:
        self.release()


def build_dependency_order(tasks: List[ParallelTask]) -> List[List[ParallelTask]]:
    """Epic #1075 — Topological sort: group tasks into execution waves.

    Each wave contains tasks whose dependencies are all satisfied by
    previous waves. Tasks with no dependencies are in wave 0.
    Tasks that cannot be ordered (cycle) are placed last.

    Returns a list of waves (list of task groups).
    """
    task_map: Dict[str, ParallelTask] = {t.task_id: t for t in tasks}
    completed: Set[str] = set()
    remaining = list(tasks)
    waves: List[List[ParallelTask]] = []
    max_iterations = len(tasks) + 1

    for _ in range(max_iterations):
        if not remaining:
            break
        wave = [
            t for t in remaining
            if all(dep in completed for dep in t.depends_on)
        ]
        if not wave:
            # Cycle or unsatisfiable deps — add remaining as final wave
            waves.append(remaining)
            break
        waves.append(wave)
        completed.update(t.task_id for t in wave)
        remaining = [t for t in remaining if t.task_id not in completed]

    return waves


def merge_results(results: List[ParallelResult]) -> Dict[str, Any]:
    """Epic #1075 — Merge parallel results into a summary dict.

    Returns:
        total: int
        succeeded: int
        failed: int
        skipped: int
        failed_task_ids: List[str]
        succeeded_task_ids: List[str]
        merged_files: List[str]  # union of all files modified
        all_success: bool
    """
    succeeded = [r for r in results if r.success and not r.skipped]
    failed = [r for r in results if not r.success and not r.skipped]
    skipped = [r for r in results if r.skipped]

    def _status_for(result: ParallelResult) -> str:
        if result.skipped:
            return "skipped"
        if result.success:
            return "succeeded"
        return "failed"

    all_merged_files: List[str] = []
    seen_files: Set[str] = set()
    for r in succeeded:
        for f in r.merged_files:
            if f not in seen_files:
                all_merged_files.append(f)
                seen_files.add(f)

    task_reports = sorted(
        [
            {
                "task_id": r.task_id,
                "status": _status_for(r),
                "success": bool(r.success),
                "skipped": bool(r.skipped),
                "skip_reason": r.skip_reason,
                "error": r.error,
                "merged_files": list(r.merged_files),
            }
            for r in results
        ],
        key=lambda item: item["task_id"],
    )

    return {
        "total": len(results),
        "succeeded": len(succeeded),
        "failed": len(failed),
        "skipped": len(skipped),
        "succeeded_task_ids": [r.task_id for r in succeeded],
        "failed_task_ids": [r.task_id for r in failed],
        "skipped_task_ids": [r.task_id for r in skipped],
        "merged_files": all_merged_files,
        "all_success": len(failed) == 0 and len(results) > 0,
        "partial_success": len(succeeded) > 0 and (len(failed) + len(skipped) > 0),
        "task_reports": task_reports,
    }


def detect_file_conflicts(tasks: List[ParallelTask]) -> Dict[str, List[str]]:
    """Epic #1075 — Detect which files would be touched by multiple parallel tasks.

    Inspects the `file_scopes` key in each task's initial_context (a list of
    file paths the task is expected to modify). Returns a dict mapping each
    conflicting file path to the list of task_ids that claim it.

    Only reports files claimed by 2+ tasks. Tasks that are already serialised
    via depends_on are excluded from conflict reporting (they won't run at the
    same time).

    Usage:
        conflicts = detect_file_conflicts(tasks)
        if conflicts:
            # adjust task scopes or add dependencies
    """
    # Build a map of file → task_ids that claim it
    file_to_tasks: Dict[str, List[str]] = {}
    for task in tasks:
        scopes: List[str] = task.initial_context.get("file_scopes", [])
        for path in scopes:
            norm = str(Path(path).as_posix())
            file_to_tasks.setdefault(norm, []).append(task.task_id)

    # Filter to files claimed by 2+ tasks (ignoring serialised pairs)
    serialised_pairs: Set[tuple] = set()
    for task in tasks:
        for dep_id in task.depends_on:
            serialised_pairs.add((dep_id, task.task_id))
            serialised_pairs.add((task.task_id, dep_id))

    conflicts: Dict[str, List[str]] = {}
    for path, task_ids in sorted(file_to_tasks.items()):
        if len(task_ids) < 2:
            continue
        # Check if all pairs of tasks are serialised (then no real conflict)
        conflict_pairs = [
            (a, b)
            for i, a in enumerate(task_ids)
            for b in task_ids[i+1:]
            if (a, b) not in serialised_pairs
        ]
        if conflict_pairs:
            conflicts[path] = sorted(set(task_ids))

    return conflicts


class ParallelTaskRunner:
    """Runs multiple AgentReasoningLoop instances concurrently.

    Epic #1075 additions:
    - FileLock prevents concurrent writes to the same file
    - Dependency graph: tasks run in topological order via build_dependency_order()
    - merge_results() aggregates outputs into a summary
    - detect_file_conflicts() pre-run conflict detection

    PR 4 hardening:
    - _run_one() now acquires per-file asyncio.Lock for every path in
      task.initial_context["file_scopes"] BEFORE acquiring the semaphore.
      Locks are sorted by path to prevent deadlock.
    - Dependency failure propagation: if any task in depends_on failed,
      the dependent task is skipped with skip_reason set.
    - _failed_task_ids tracks all non-success tasks for dependency skip.
    """

    def __init__(self, project_root: str, max_concurrent: int = 3) -> None:
        self.project_root = project_root
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._completed_results: Dict[str, ParallelResult] = {}
        # PR 4: track failed task IDs for dependency failure skip
        self._failed_task_ids: Set[str] = set()
        # PR 4: per-file asyncio.Locks for conflict serialization
        self._file_locks: Dict[str, asyncio.Lock] = {}
        self._file_locks_mutex: Optional[asyncio.Lock] = None  # lazily initialized

    def _get_file_locks_mutex(self) -> asyncio.Lock:
        """Lazily initialize file locks mutex (requires running event loop)."""
        if self._file_locks_mutex is None:
            self._file_locks_mutex = asyncio.Lock()
        return self._file_locks_mutex

    async def _acquire_file_locks(
        self,
        file_scopes: List[str],
    ) -> List[asyncio.Lock]:
        """Acquire per-file asyncio.Locks for all paths in file_scopes.

        PR 4: locks are sorted alphabetically to prevent deadlock when
        multiple tasks try to lock the same set of files in different orders.

        Returns the list of acquired locks (caller must release them).
        """
        if not file_scopes:
            return []

        # Normalize and deduplicate paths
        norm_paths = sorted(set(str(Path(p).as_posix()) for p in file_scopes))

        # Create locks for new paths
        mutex = self._get_file_locks_mutex()
        async with mutex:
            for path in norm_paths:
                if path not in self._file_locks:
                    self._file_locks[path] = asyncio.Lock()

        # Acquire all locks (sorted order — deadlock-free)
        acquired: List[asyncio.Lock] = []
        for path in norm_paths:
            lock = self._file_locks[path]
            await lock.acquire()
            acquired.append(lock)
        return acquired

    @staticmethod
    def _release_file_locks(acquired: List[asyncio.Lock]) -> None:
        """Release all acquired file locks."""
        for lock in acquired:
            if lock.locked():
                lock.release()

    async def _run_one(self, task: ParallelTask) -> ParallelResult:
        """Run a single task with file locking and dependency failure skip.

        PR 4 hardening:
        1. Check dependency failure: if any dependency failed, skip this task.
        2. Acquire per-file asyncio.Locks for task.initial_context["file_scopes"].
        3. Acquire semaphore (bounded concurrency).
        4. Execute task.
        5. Release file locks.
        6. Track failures in _failed_task_ids.
        """
        # PR 4 — Dependency failure skip
        failed_deps = [dep for dep in task.depends_on if dep in self._failed_task_ids]
        if failed_deps:
            skip_reason = f"dependency failed: {failed_deps}"
            logger.warning("skipping task %s: %s", task.task_id, skip_reason)
            pr = ParallelResult(
                task_id=task.task_id,
                result=None,
                skipped=True,
                skip_reason=skip_reason,
            )
            # Propagate skip as failure so downstream deps are also skipped
            self._failed_task_ids.add(task.task_id)
            return pr

        # PR 4 — Acquire per-file locks (sorted, deadlock-free)
        file_scopes: List[str] = list(task.initial_context.get("file_scopes") or [])
        acquired_locks: List[asyncio.Lock] = await self._acquire_file_locks(file_scopes)

        try:
            async with self._semaphore:
                try:
                    loop = AgentReasoningLoop(
                        project_root=self.project_root,
                        max_steps=task.max_steps,
                        task_type=task.task_type,
                        preferred_profile=task.preferred_profile,
                    )
                    result = await asyncio.to_thread(
                        loop.run,
                        goal=task.goal,
                        initial_context=task.initial_context,
                    )
                    pr = ParallelResult(task_id=task.task_id, result=result)
                    # Collect modified files for merge
                    if hasattr(result, "files_modified"):
                        pr.merged_files = list(result.files_modified or [])
                    # PR 4 — track failure for dependency propagation
                    if not pr.success:
                        self._failed_task_ids.add(task.task_id)
                    return pr
                except Exception as exc:
                    logger.error("parallel task %s failed: %s", task.task_id, exc)
                    self._failed_task_ids.add(task.task_id)
                    return ParallelResult(task_id=task.task_id, result=None, error=str(exc))
        finally:
            # PR 4 — Always release file locks
            self._release_file_locks(acquired_locks)

    async def run(self, tasks: List[ParallelTask]) -> List[ParallelResult]:
        """Run tasks respecting dependency order (Epic #1075).

        PR 4: resets _failed_task_ids at start of each run() invocation.
        """
        if not tasks:
            return []

        # PR 4 — reset failure tracking for this run
        self._failed_task_ids = set()

        # Check if any task has dependencies — if not, run all in parallel
        has_deps = any(t.depends_on for t in tasks)
        if not has_deps:
            coros = [self._run_one(t) for t in tasks]
            return list(await asyncio.gather(*coros))

        # Run in waves (topological order)
        waves = build_dependency_order(tasks)
        all_results: List[ParallelResult] = []
        completed_ids: Set[str] = set()

        for wave in waves:
            wave_coros = [self._run_one(t) for t in wave]
            wave_results = list(await asyncio.gather(*wave_coros))
            all_results.extend(wave_results)
            for r in wave_results:
                self._completed_results[r.task_id] = r
                if r.success:
                    completed_ids.add(r.task_id)

        return all_results

    def run_sync(self, tasks: List[ParallelTask]) -> List[ParallelResult]:
        return asyncio.run(self.run(tasks))
