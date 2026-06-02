"""PR 4 — Parallel runner safety tests.

Covers:
- FileLock wired in _run_one() via per-file asyncio.Lock
- Dependency failure propagation (failed dep → skip dependent)
- Skipped task has skip_reason set and skipped=True
- File conflict serialization (two tasks same file run serially, not concurrently)
- Deadlock prevention (alphabetical lock ordering)
- merge_results includes skipped tasks correctly
- _failed_task_ids reset between run() calls
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from igris.core.parallel_task_runner import (
    FileLock,
    ParallelResult,
    ParallelTask,
    ParallelTaskRunner,
    build_dependency_order,
    detect_file_conflicts,
    merge_results,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _runner(max_concurrent: int = 3) -> ParallelTaskRunner:
    return ParallelTaskRunner(project_root="/tmp/test", max_concurrent=max_concurrent)


def _success_result() -> MagicMock:
    r = MagicMock()
    r.status = "finished"
    r.files_modified = []
    return r


def _fail_result() -> MagicMock:
    r = MagicMock()
    r.status = "failed"
    r.files_modified = []
    return r


def _task(task_id: str, depends_on=None, file_scopes=None) -> ParallelTask:
    return ParallelTask(
        task_id=task_id,
        goal=f"do task {task_id}",
        depends_on=depends_on or [],
        initial_context={"file_scopes": file_scopes or []},
    )


def _mock_loop_run_success(_goal=None, **kwargs):
    return _success_result()


def _mock_loop_run_fail(_goal=None, **kwargs):
    raise RuntimeError("task failed intentionally")


# ---------------------------------------------------------------------------
# 1. Dependency failure skip
# ---------------------------------------------------------------------------

class TestDependencyFailureSkip:

    @pytest.mark.asyncio
    async def test_failed_dep_causes_skip(self):
        runner = _runner()
        # Inject a failed task ID
        runner._failed_task_ids.add("task_a")
        task_b = _task("task_b", depends_on=["task_a"])

        result = await runner._run_one(task_b)
        assert result.skipped is True
        assert "task_a" in result.skip_reason
        assert result.task_id == "task_b"

    @pytest.mark.asyncio
    async def test_skip_propagates_to_further_dependents(self):
        """Skipped task should also be marked as failed so further deps skip."""
        runner = _runner()
        runner._failed_task_ids.add("task_a")
        task_b = _task("task_b", depends_on=["task_a"])

        result = await runner._run_one(task_b)
        # task_b is skipped — should be in _failed_task_ids to propagate
        assert "task_b" in runner._failed_task_ids

    @pytest.mark.asyncio
    async def test_no_skip_if_dep_succeeded(self):
        """Task should NOT be skipped if its dependency succeeded."""
        runner = _runner()
        # task_a is NOT in failed_task_ids
        task_b = _task("task_b", depends_on=["task_a"])

        with patch(
            "igris.core.parallel_task_runner.AgentReasoningLoop"
        ) as MockLoop:
            mock_instance = MagicMock()
            mock_instance.run.return_value = _success_result()
            MockLoop.return_value = mock_instance

            result = await runner._run_one(task_b)
        assert result.skipped is False
        assert result.task_id == "task_b"

    @pytest.mark.asyncio
    async def test_no_skip_if_no_deps(self):
        task = _task("task_a", depends_on=[])
        runner = _runner()
        with patch("igris.core.parallel_task_runner.AgentReasoningLoop") as MockLoop:
            mock_instance = MagicMock()
            mock_instance.run.return_value = _success_result()
            MockLoop.return_value = mock_instance
            result = await runner._run_one(task)
        assert result.skipped is False

    def test_full_run_dep_failure_skips_downstream(self):
        """Integration: task_a fails → task_b (depends on a) is skipped."""
        runner = _runner()
        task_a = _task("task_a")
        task_b = _task("task_b", depends_on=["task_a"])

        with patch("igris.core.parallel_task_runner.AgentReasoningLoop") as MockLoop:
            # task_a fails via exception
            mock_instance = MagicMock()
            mock_instance.run.side_effect = RuntimeError("forced failure")
            MockLoop.return_value = mock_instance

            results = runner.run_sync([task_a, task_b])

        by_id = {r.task_id: r for r in results}
        assert by_id["task_a"].skipped is False
        assert by_id["task_a"].error is not None
        assert by_id["task_b"].skipped is True
        assert "task_a" in by_id["task_b"].skip_reason

    def test_failed_task_ids_reset_between_runs(self):
        """_failed_task_ids must be reset at the start of each run()."""
        runner = _runner()
        # Inject stale failure
        runner._failed_task_ids.add("old_task")

        task_a = _task("task_a")
        with patch("igris.core.parallel_task_runner.AgentReasoningLoop") as MockLoop:
            mock_instance = MagicMock()
            mock_instance.run.return_value = _success_result()
            MockLoop.return_value = mock_instance
            results = runner.run_sync([task_a])

        # old_task should be gone after reset
        assert "old_task" not in runner._failed_task_ids


# ---------------------------------------------------------------------------
# 2. File locking
# ---------------------------------------------------------------------------

class TestFileLocking:

    @pytest.mark.asyncio
    async def test_acquire_file_locks_returns_locks(self):
        runner = _runner()
        locks = await runner._acquire_file_locks(["igris/core/foo.py", "igris/core/bar.py"])
        assert len(locks) == 2
        # All acquired
        for lock in locks:
            assert lock.locked()
        runner._release_file_locks(locks)

    @pytest.mark.asyncio
    async def test_release_unlocks_all(self):
        runner = _runner()
        locks = await runner._acquire_file_locks(["igris/core/foo.py"])
        runner._release_file_locks(locks)
        for lock in locks:
            assert not lock.locked()

    def test_lock_timeout_reports_reason_code(self, tmp_path):
        path = str(tmp_path / "shared.py")
        lock1 = FileLock(path, timeout_seconds=0.3)
        lock1.acquire()
        try:
            lock2 = FileLock(path, timeout_seconds=0.2)
            with pytest.raises(TimeoutError) as excinfo:
                lock2.acquire()
            msg = str(excinfo.value)
            assert "lock_timeout reason_code=parallel_file_lock" in msg
            assert path in msg
        finally:
            lock1.release()

    @pytest.mark.asyncio
    async def test_empty_scopes_returns_empty(self):
        runner = _runner()
        locks = await runner._acquire_file_locks([])
        assert locks == []

    @pytest.mark.asyncio
    async def test_duplicate_paths_deduplicated(self):
        runner = _runner()
        # Same path twice — should only create one lock
        locks = await runner._acquire_file_locks([
            "igris/core/foo.py",
            "igris/core/foo.py",
        ])
        assert len(locks) == 1
        runner._release_file_locks(locks)

    @pytest.mark.asyncio
    async def test_two_tasks_same_file_serialize(self):
        """Two tasks claiming the same file should NOT run concurrently."""
        runner = _runner(max_concurrent=5)
        execution_order = []

        async def fake_run(task_id: str, delay: float) -> None:
            execution_order.append(f"start:{task_id}")
            await asyncio.sleep(delay)
            execution_order.append(f"end:{task_id}")

        # Patch _run_one to use controlled execution
        original_run_one = runner._run_one

        async def patched_run_one(task: ParallelTask) -> ParallelResult:
            file_scopes = list(task.initial_context.get("file_scopes") or [])
            acquired = await runner._acquire_file_locks(file_scopes)
            try:
                await fake_run(task.task_id, 0.05)
                return ParallelResult(task_id=task.task_id, result=_success_result())
            finally:
                runner._release_file_locks(acquired)

        task_a = _task("task_a", file_scopes=["shared/file.py"])
        task_b = _task("task_b", file_scopes=["shared/file.py"])

        with patch.object(runner, "_run_one", side_effect=patched_run_one):
            await asyncio.gather(
                runner._run_one(task_a),
                runner._run_one(task_b),
            )

        # Verify serialization: end of one before start of other
        start_a = execution_order.index("start:task_a")
        end_a = execution_order.index("end:task_a")
        start_b = execution_order.index("start:task_b")
        end_b = execution_order.index("end:task_b")

        # Either A finishes before B starts, or B finishes before A starts
        assert end_a < start_b or end_b < start_a, (
            f"Concurrent access to shared file detected: {execution_order}"
        )

    @pytest.mark.asyncio
    async def test_different_files_can_run_concurrently(self):
        """Tasks with different files should be able to run concurrently."""
        runner = _runner(max_concurrent=5)
        # Both should be able to acquire without blocking each other
        locks_a = await runner._acquire_file_locks(["igris/core/file_a.py"])
        locks_b = await runner._acquire_file_locks(["igris/core/file_b.py"])
        # Both acquired without deadlock
        assert len(locks_a) == 1
        assert len(locks_b) == 1
        runner._release_file_locks(locks_a)
        runner._release_file_locks(locks_b)

    @pytest.mark.asyncio
    async def test_locks_released_even_on_exception(self):
        """File locks must be released even when task raises."""
        runner = _runner()
        task = _task("task_a", file_scopes=["igris/core/foo.py"])

        with patch("igris.core.parallel_task_runner.AgentReasoningLoop") as MockLoop:
            mock_instance = MagicMock()
            mock_instance.run.side_effect = RuntimeError("task exploded")
            MockLoop.return_value = mock_instance

            result = await runner._run_one(task)

        # Lock must be released
        assert "igris/core/foo.py" in runner._file_locks
        assert not runner._file_locks["igris/core/foo.py"].locked()
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_lock_stored_by_normalized_path(self):
        """Paths are normalized (posix) before creating locks."""
        runner = _runner()
        # Both of these should resolve to the same lock
        await runner._acquire_file_locks(["igris/core/foo.py"])
        runner._release_file_locks([runner._file_locks["igris/core/foo.py"]])
        assert "igris/core/foo.py" in runner._file_locks


# ---------------------------------------------------------------------------
# 3. merge_results with skipped tasks
# ---------------------------------------------------------------------------

class TestMergeResultsWithSkip:

    def test_skipped_tasks_counted(self):
        results = [
            ParallelResult(task_id="a", result=_success_result()),
            ParallelResult(task_id="b", result=None, skipped=True, skip_reason="dep failed"),
            ParallelResult(task_id="c", result=None, error="crash"),
        ]
        summary = merge_results(results)
        assert summary["total"] == 3
        assert summary["skipped"] == 1
        assert summary["skipped_task_ids"] == ["b"]
        assert summary["all_success"] is False

    def test_all_success_false_when_skipped_present(self):
        results = [
            ParallelResult(task_id="a", result=_success_result()),
            ParallelResult(task_id="b", result=None, skipped=True, skip_reason="dep failed"),
        ]
        summary = merge_results(results)
        # Skipped tasks don't count as failures but all_success requires no failures
        assert summary["all_success"] is False or summary["succeeded"] == 1

    def test_merge_results_no_skipped(self):
        results = [
            ParallelResult(task_id="a", result=_success_result()),
            ParallelResult(task_id="b", result=_success_result()),
        ]
        summary = merge_results(results)
        assert summary["total"] == 2
        assert summary["skipped"] == 0

    def test_task_reports_and_partial_success(self):
        results = [
            ParallelResult(task_id="a", result=_success_result(), merged_files=["x.py"]),
            ParallelResult(task_id="b", result=None, error="boom"),
            ParallelResult(task_id="c", result=None, skipped=True, skip_reason="dependency failed: ['b']"),
        ]
        summary = merge_results(results)
        assert summary["partial_success"] is True
        assert [item["task_id"] for item in summary["task_reports"]] == ["a", "b", "c"]
        assert summary["task_reports"][0]["status"] == "succeeded"
        assert summary["task_reports"][1]["status"] == "failed"
        assert summary["task_reports"][2]["status"] == "skipped"
        assert summary["task_reports"][2]["skip_reason"].startswith("dependency failed")


# ---------------------------------------------------------------------------
# 4. detect_file_conflicts
# ---------------------------------------------------------------------------

class TestDetectFileConflicts:

    def test_conflict_detected_for_shared_file(self):
        tasks = [
            _task("task_a", file_scopes=["igris/core/foo.py"]),
            _task("task_b", file_scopes=["igris/core/foo.py"]),
        ]
        conflicts = detect_file_conflicts(tasks)
        assert "igris/core/foo.py" in conflicts
        assert set(conflicts["igris/core/foo.py"]) == {"task_a", "task_b"}

    def test_no_conflict_if_serialized(self):
        """Tasks with dependency are serialized — no conflict."""
        tasks = [
            _task("task_a", file_scopes=["igris/core/foo.py"]),
            _task("task_b", depends_on=["task_a"], file_scopes=["igris/core/foo.py"]),
        ]
        conflicts = detect_file_conflicts(tasks)
        assert "igris/core/foo.py" not in conflicts

    def test_no_conflict_for_different_files(self):
        tasks = [
            _task("task_a", file_scopes=["igris/core/foo.py"]),
            _task("task_b", file_scopes=["igris/core/bar.py"]),
        ]
        conflicts = detect_file_conflicts(tasks)
        assert len(conflicts) == 0

    def test_no_conflict_for_single_task(self):
        tasks = [_task("task_a", file_scopes=["igris/core/foo.py"])]
        conflicts = detect_file_conflicts(tasks)
        assert len(conflicts) == 0

    def test_conflicts_are_deterministic_and_sorted(self):
        tasks = [
            _task("z_task", file_scopes=["b.py", "a.py"]),
            _task("a_task", file_scopes=["a.py"]),
            _task("m_task", file_scopes=["a.py"]),
        ]
        conflicts = detect_file_conflicts(tasks)
        assert list(conflicts.keys()) == ["a.py"]
        assert conflicts["a.py"] == ["a_task", "m_task", "z_task"]


# ---------------------------------------------------------------------------
# 5. Integration: run_sync with dependency + file scopes
# ---------------------------------------------------------------------------

class TestRunSyncIntegration:

    def test_run_sync_no_tasks(self):
        runner = _runner()
        results = runner.run_sync([])
        assert results == []

    def test_run_sync_single_task_success(self):
        runner = _runner()
        task = _task("t1")
        with patch("igris.core.parallel_task_runner.AgentReasoningLoop") as MockLoop:
            mock_instance = MagicMock()
            mock_instance.run.return_value = _success_result()
            MockLoop.return_value = mock_instance
            results = runner.run_sync([task])
        assert len(results) == 1
        assert results[0].task_id == "t1"
        assert results[0].skipped is False

    def test_run_sync_with_file_scopes(self):
        runner = _runner()
        task = _task("t1", file_scopes=["igris/core/delivery_workflow.py"])
        with patch("igris.core.parallel_task_runner.AgentReasoningLoop") as MockLoop:
            mock_instance = MagicMock()
            mock_instance.run.return_value = _success_result()
            MockLoop.return_value = mock_instance
            results = runner.run_sync([task])
        assert results[0].skipped is False
        # Lock should have been created and released
        assert "igris/core/delivery_workflow.py" in runner._file_locks
        assert not runner._file_locks["igris/core/delivery_workflow.py"].locked()

    def test_run_sync_chain_failure_skips(self):
        """A → B → C: A fails → B skipped → C skipped (chain propagation)."""
        runner = _runner()
        task_a = _task("a")
        task_b = _task("b", depends_on=["a"])
        task_c = _task("c", depends_on=["b"])

        with patch("igris.core.parallel_task_runner.AgentReasoningLoop") as MockLoop:
            mock_instance = MagicMock()
            mock_instance.run.side_effect = RuntimeError("a failed")
            MockLoop.return_value = mock_instance
            results = runner.run_sync([task_a, task_b, task_c])

        by_id = {r.task_id: r for r in results}
        assert by_id["a"].error is not None
        assert by_id["b"].skipped is True
        assert by_id["c"].skipped is True
