from __future__ import annotations

import asyncio
import threading
import time

from igris.core.agent_reasoning_loop import LoopResult
from igris.core.parallel_task_runner import ParallelTask, ParallelTaskRunner
from igris.core.self_repair_supervisor import SelfRepairSupervisor


def test_run_empty_returns_empty(tmp_path):
    runner = ParallelTaskRunner(str(tmp_path))
    assert runner.run_sync([]) == []


def test_run_single_task_success(tmp_path, monkeypatch):
    def fake_run(self, goal, initial_context):
        return LoopResult(goal=goal, status="finished")

    monkeypatch.setattr("igris.core.agent_reasoning_loop.AgentReasoningLoop.run", fake_run)
    runner = ParallelTaskRunner(str(tmp_path))
    results = runner.run_sync([ParallelTask(task_id="t1", goal="g1")])
    assert len(results) == 1
    assert results[0].task_id == "t1"
    assert results[0].success is True


def test_run_multiple_tasks_concurrent(tmp_path, monkeypatch):
    def fake_run(self, goal, initial_context):
        return LoopResult(goal=goal, status="finished")

    monkeypatch.setattr("igris.core.agent_reasoning_loop.AgentReasoningLoop.run", fake_run)
    runner = ParallelTaskRunner(str(tmp_path), max_concurrent=3)
    tasks = [ParallelTask(task_id=f"t{i}", goal=f"g{i}") for i in range(3)]
    results = runner.run_sync(tasks)
    assert {r.task_id for r in results} == {"t0", "t1", "t2"}


def test_run_one_failure_does_not_block_others(tmp_path, monkeypatch):
    def fake_run(self, goal, initial_context):
        if goal == "bad":
            raise RuntimeError("boom")
        return LoopResult(goal=goal, status="finished")

    monkeypatch.setattr("igris.core.agent_reasoning_loop.AgentReasoningLoop.run", fake_run)
    runner = ParallelTaskRunner(str(tmp_path), max_concurrent=3)
    tasks = [
        ParallelTask(task_id="t1", goal="ok1"),
        ParallelTask(task_id="t2", goal="bad"),
        ParallelTask(task_id="t3", goal="ok2"),
    ]
    results = runner.run_sync(tasks)
    by_id = {r.task_id: r for r in results}
    assert by_id["t1"].success is True
    assert by_id["t3"].success is True
    assert by_id["t2"].result is None
    assert by_id["t2"].error


def test_max_concurrent_respected(tmp_path, monkeypatch):
    active = 0
    peak = 0
    lock = threading.Lock()

    def fake_run(self, goal, initial_context):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return LoopResult(goal=goal, status="finished")

    monkeypatch.setattr("igris.core.agent_reasoning_loop.AgentReasoningLoop.run", fake_run)
    runner = ParallelTaskRunner(str(tmp_path), max_concurrent=2)
    tasks = [ParallelTask(task_id=f"t{i}", goal=f"g{i}") for i in range(5)]
    runner.run_sync(tasks)
    assert peak <= 2


def test_run_sync_wrapper(tmp_path, monkeypatch):
    def fake_run(self, goal, initial_context):
        return LoopResult(goal=goal, status="finished")

    monkeypatch.setattr("igris.core.agent_reasoning_loop.AgentReasoningLoop.run", fake_run)
    runner = ParallelTaskRunner(str(tmp_path), max_concurrent=2)
    tasks = [ParallelTask(task_id="t1", goal="g1"), ParallelTask(task_id="t2", goal="g2")]
    sync_results = runner.run_sync(tasks)
    async_results = asyncio.run(runner.run(tasks))
    assert [r.task_id for r in sync_results] == [r.task_id for r in async_results]
    assert [r.success for r in sync_results] == [r.success for r in async_results]


def test_decomposed_parallel_in_supervisor(tmp_path, monkeypatch):
    called = {}

    class DummyRunner:
        def __init__(self, project_root, max_concurrent=3):
            called["init"] = (project_root, max_concurrent)

        def run_sync(self, tasks):
            called["tasks"] = tasks
            return [type("R", (), {"result": LoopResult(status="finished"), "error": None})()]

    monkeypatch.setattr("igris.core.parallel_task_runner.ParallelTaskRunner", DummyRunner)
    supervisor = SelfRepairSupervisor(str(tmp_path))
    results = supervisor._run_decomposed_parallel(["sub goal"], base_max_steps=7, preferred_profile="p1")

    assert called["init"][0] == str(tmp_path)
    assert called["init"][1] == 3
    assert len(called["tasks"]) == 1
    assert called["tasks"][0].goal == "sub goal"
    assert called["tasks"][0].max_steps == 7
    assert called["tasks"][0].preferred_profile == "p1"
    assert results[0]["status"] == "finished"
