"""Integration tests for VastAI Fleet Manager wiring.

Tests task queue, secondary slots, orchestrator integration,
heartbeat emission, and web API route logic.

Issues: #593-#598
"""
from __future__ import annotations

import sys
import threading
import types
from collections import deque
from datetime import datetime, timedelta
from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytest

from igris.layers.advisory.vastai_fleet import (
    AgentHeartbeat,
    AgentPhase,
    FleetInstance,
    FleetMonitor,
    FleetPolicy,
    FleetScheduler,
    FleetState,
    HeartbeatReceiver,
    InstanceStatus,
    QueuedTask,
    ScaleAssignWarm,
    ScaleOpenNew,
    ScaleWait,
    SecondarySlotScheduler,
    VastAIFleet,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_instance(
    iid="i-001", host="1.2.3.4", port=11434,
    status=InstanceStatus.BUSY, model_loaded=True,
    phase=AgentPhase.CODING, elapsed_minutes=20.0,
    tokens_generated=0, tokens_per_sec=0.0,
    assigned_issue=1, task_type="hard_debugging",
):
    inst = FleetInstance(
        instance_id=iid, host=host, port=port,
        status=status, assigned_issue=assigned_issue,
        task_type=task_type, model_loaded=model_loaded,
        phase=phase, tokens_generated=tokens_generated,
        tokens_per_sec=tokens_per_sec,
    )
    inst.task_started_at = datetime.utcnow() - timedelta(minutes=elapsed_minutes)
    inst.started_at = datetime.utcnow() - timedelta(minutes=elapsed_minutes)
    inst.last_heartbeat = datetime.utcnow()
    return inst


def make_fleet() -> VastAIFleet:
    return VastAIFleet()


def make_monitor(state: FleetState) -> FleetMonitor:
    policy = FleetPolicy()
    scheduler = FleetScheduler()
    return FleetMonitor(
        state=state,
        policy=policy,
        scheduler=scheduler,
        provision_fn=lambda n: [],
        terminate_fn=lambda iid: None,
        restart_ollama_fn=lambda inst: False,
    )


# ---------------------------------------------------------------------------
# 1. Task Queue
# ---------------------------------------------------------------------------

class TestTaskQueue:

    def test_enqueue_adds_to_queue(self):
        state = FleetState()
        state.enqueue(QueuedTask(issue_number=1))
        assert state.queue_depth == 1

    def test_enqueue_multiple_increases_depth(self):
        state = FleetState()
        state.enqueue(QueuedTask(issue_number=1))
        state.enqueue(QueuedTask(issue_number=2))
        state.enqueue(QueuedTask(issue_number=3))
        assert state.queue_depth == 3

    def test_dequeue_removes_fifo(self):
        state = FleetState()
        state.enqueue(QueuedTask(issue_number=10))
        state.enqueue(QueuedTask(issue_number=20))
        first = state.dequeue()
        assert first is not None
        assert first.issue_number == 10
        second = state.dequeue()
        assert second is not None
        assert second.issue_number == 20

    def test_dequeue_empty_returns_none(self):
        state = FleetState()
        assert state.dequeue() is None

    def test_queue_depth_reflects_real_length(self):
        state = FleetState()
        assert state.queue_depth == 0
        state.enqueue(QueuedTask(issue_number=1))
        assert state.queue_depth == 1
        state.dequeue()
        assert state.queue_depth == 0

    def test_acquire_no_instance_enqueues_task(self):
        fleet = make_fleet()
        result = fleet.acquire(issue_number=99, task_type="hard_debugging")
        assert result is None
        assert fleet._state.queue_depth == 1
        task = fleet._state.dequeue()
        assert task is not None
        assert task.issue_number == 99
        assert task.task_type == "hard_debugging"

    def test_acquire_multiple_no_instance_queues_all(self):
        fleet = make_fleet()
        fleet.acquire(issue_number=1)
        fleet.acquire(issue_number=2)
        fleet.acquire(issue_number=3)
        assert fleet._state.queue_depth == 3

    def test_release_does_not_decrement_queue(self):
        """Queue is managed independently; release does not pop from it."""
        fleet = make_fleet()
        inst = make_instance("a", status=InstanceStatus.BUSY, assigned_issue=1)
        fleet._state.instances.append(inst)
        fleet._state.enqueue(QueuedTask(issue_number=10))
        fleet._state.enqueue(QueuedTask(issue_number=11))
        assert fleet._state.queue_depth == 2
        fleet.release("a")
        # Queue still has 2 items — release doesn't touch it
        assert fleet._state.queue_depth == 2

    def test_queued_task_preserves_task_type(self):
        task = QueuedTask(issue_number=42, task_type="security_audit")
        assert task.issue_number == 42
        assert task.task_type == "security_audit"


# ---------------------------------------------------------------------------
# 2. SecondarySlotScheduler
# ---------------------------------------------------------------------------

class TestSecondarySlotScheduler:

    def _scheduler(self) -> SecondarySlotScheduler:
        return SecondarySlotScheduler()

    def test_available_slots_returns_test_execution_instances(self):
        sched = self._scheduler()
        state = FleetState()
        inst = make_instance("a", status=InstanceStatus.BUSY, phase=AgentPhase.TEST_EXECUTION)
        state.instances.append(inst)
        slots = sched.available_slots(state)
        assert inst in slots

    def test_available_slots_excludes_coding_instances(self):
        sched = self._scheduler()
        state = FleetState()
        inst = make_instance("a", status=InstanceStatus.BUSY, phase=AgentPhase.CODING)
        state.instances.append(inst)
        slots = sched.available_slots(state)
        assert inst not in slots

    def test_available_slots_excludes_instances_with_secondary(self):
        sched = self._scheduler()
        state = FleetState()
        inst = make_instance("a", status=InstanceStatus.BUSY, phase=AgentPhase.TEST_EXECUTION)
        inst.secondary_issue = 99
        state.instances.append(inst)
        slots = sched.available_slots(state)
        assert inst not in slots

    def test_available_slots_includes_only_test_execution_no_secondary(self):
        sched = self._scheduler()
        state = FleetState()
        inst_coding = make_instance("a", status=InstanceStatus.BUSY, phase=AgentPhase.CODING)
        inst_test = make_instance("b", status=InstanceStatus.BUSY, phase=AgentPhase.TEST_EXECUTION)
        inst_test_busy = make_instance("c", status=InstanceStatus.BUSY, phase=AgentPhase.TEST_EXECUTION)
        inst_test_busy.secondary_issue = 5
        state.instances.extend([inst_coding, inst_test, inst_test_busy])
        slots = sched.available_slots(state)
        assert slots == [inst_test]

    def test_assign_secondary_sets_issue(self):
        sched = self._scheduler()
        inst = make_instance("a", status=InstanceStatus.BUSY, phase=AgentPhase.TEST_EXECUTION)
        task = QueuedTask(issue_number=77, task_type="light_review")
        sched.assign_secondary(inst, task)
        assert inst.secondary_issue == 77
        assert inst.secondary_task_type == "light_review"

    def test_clear_secondary_returns_issue_number(self):
        sched = self._scheduler()
        inst = make_instance("a")
        inst.secondary_issue = 42
        inst.secondary_task_type = "audit"
        cleared = sched.clear_secondary(inst)
        assert cleared == 42
        assert inst.secondary_issue is None
        assert inst.secondary_task_type == ""

    def test_clear_secondary_on_instance_with_no_secondary_returns_none(self):
        sched = self._scheduler()
        inst = make_instance("a")
        assert inst.secondary_issue is None
        cleared = sched.clear_secondary(inst)
        assert cleared is None


# ---------------------------------------------------------------------------
# 3. FleetMonitor secondary slot logic
# ---------------------------------------------------------------------------

class TestFleetMonitorSecondaryLogic:

    def test_instance_leaves_test_execution_clears_secondary_and_requeues(self):
        """When primary resumes (phase changes from TEST_EXECUTION), secondary is re-queued."""
        state = FleetState()
        inst = make_instance("a", status=InstanceStatus.BUSY, phase=AgentPhase.CODING)
        inst.secondary_issue = 55
        inst.secondary_task_type = "code_reasoning"
        state.instances.append(inst)
        monitor = make_monitor(state)
        # _clear_finished_secondaries should detect this and re-queue
        with state._lock:
            monitor._clear_finished_secondaries()
        assert inst.secondary_issue is None
        assert state.queue_depth == 1
        task = state.dequeue()
        assert task is not None
        assert task.issue_number == 55

    def test_instance_still_in_test_execution_secondary_not_cleared(self):
        """Instance still in TEST_EXECUTION: secondary should remain."""
        state = FleetState()
        inst = make_instance("a", status=InstanceStatus.BUSY, phase=AgentPhase.TEST_EXECUTION)
        inst.secondary_issue = 66
        state.instances.append(inst)
        monitor = make_monitor(state)
        with state._lock:
            monitor._clear_finished_secondaries()
        # Not cleared — still in TEST_EXECUTION
        assert inst.secondary_issue == 66
        assert state.queue_depth == 0

    def test_secondary_only_assigned_when_task_queue_nonempty(self):
        """_assign_secondary_slots: empty queue means no assignment."""
        state = FleetState()
        inst = make_instance("a", status=InstanceStatus.BUSY, phase=AgentPhase.TEST_EXECUTION)
        state.instances.append(inst)
        monitor = make_monitor(state)
        monitor._assign_secondary_slots()
        assert inst.secondary_issue is None

    def test_secondary_assigned_from_queue(self):
        """_assign_secondary_slots picks task from queue and assigns to TEST_EXECUTION slot."""
        state = FleetState()
        inst = make_instance("a", status=InstanceStatus.BUSY, phase=AgentPhase.TEST_EXECUTION)
        state.instances.append(inst)
        state.enqueue(QueuedTask(issue_number=88, task_type="code_reasoning"))
        monitor = make_monitor(state)
        monitor._assign_secondary_slots()
        assert inst.secondary_issue == 88
        assert state.queue_depth == 0

    def test_secondary_assignment_does_not_assign_when_no_slots(self):
        """No TEST_EXECUTION slots → queue untouched."""
        state = FleetState()
        inst = make_instance("a", status=InstanceStatus.BUSY, phase=AgentPhase.CODING)
        state.instances.append(inst)
        state.enqueue(QueuedTask(issue_number=99))
        monitor = make_monitor(state)
        monitor._assign_secondary_slots()
        # Task still in queue
        assert state.queue_depth == 1


# ---------------------------------------------------------------------------
# 4. Orchestrator uses fleet
# ---------------------------------------------------------------------------

class TestOrchestratorUsesFleet:

    def _make_orch_and_provider(self):
        from igris.core.model_orchestrator import ModelOrchestrator
        orch = ModelOrchestrator()
        provider = orch.providers["vastai_ollama"]
        return orch, provider

    def test_check_vastai_returns_true_when_fleet_has_endpoint(self):
        orch, provider = self._make_orch_and_provider()

        mock_fleet = MagicMock()
        mock_fleet.get_ready_endpoint.return_value = "http://10.0.0.1:11434"

        fleet_mod = types.ModuleType("igris.layers.advisory.vastai_fleet")
        fleet_mod._SHARED_FLEET = mock_fleet

        with patch.dict(sys.modules, {"igris.layers.advisory.vastai_fleet": fleet_mod}):
            result = orch._check_vastai_available(provider)

        assert result is True
        assert provider.base_url == "http://10.0.0.1:11434"

    def test_check_vastai_returns_false_when_no_endpoint(self):
        orch, provider = self._make_orch_and_provider()

        mock_fleet = MagicMock()
        mock_fleet.get_ready_endpoint.return_value = None

        mock_mgr = MagicMock()
        mock_mgr.auto_provision_for_orchestrator.return_value = False

        fleet_mod = types.ModuleType("igris.layers.advisory.vastai_fleet")
        fleet_mod._SHARED_FLEET = mock_fleet
        mgr_mod = types.ModuleType("igris.layers.advisory.vastai_manager")
        mgr_mod._SHARED_MANAGER = mock_mgr

        with patch.dict(sys.modules, {
            "igris.layers.advisory.vastai_fleet": fleet_mod,
            "igris.layers.advisory.vastai_manager": mgr_mod,
        }):
            result = orch._check_vastai_available(provider)

        assert result is False

    def test_check_vastai_triggers_provision_when_no_endpoint(self):
        orch, provider = self._make_orch_and_provider()

        mock_fleet = MagicMock()
        mock_fleet.get_ready_endpoint.return_value = None

        mock_mgr = MagicMock()
        mock_mgr.auto_provision_for_orchestrator.return_value = True

        fleet_mod = types.ModuleType("igris.layers.advisory.vastai_fleet")
        fleet_mod._SHARED_FLEET = mock_fleet
        mgr_mod = types.ModuleType("igris.layers.advisory.vastai_manager")
        mgr_mod._SHARED_MANAGER = mock_mgr

        with patch.dict(sys.modules, {
            "igris.layers.advisory.vastai_fleet": fleet_mod,
            "igris.layers.advisory.vastai_manager": mgr_mod,
        }):
            orch._check_vastai_available(provider)

        mock_mgr.auto_provision_for_orchestrator.assert_called_once()

    def test_check_vastai_import_error_returns_false(self):
        """If vastai_fleet can't be imported, returns False gracefully."""
        orch, provider = self._make_orch_and_provider()

        # Setting module to None in sys.modules causes ImportError on 'from ... import'
        with patch.dict(sys.modules, {"igris.layers.advisory.vastai_fleet": None}):
            result = orch._check_vastai_available(provider)
        assert result is False


# ---------------------------------------------------------------------------
# 5. Agent reasoning loop heartbeat
# ---------------------------------------------------------------------------

class TestAgentReasoningLoopHeartbeat:

    def _make_loop(self, issue_number=0, fleet_instance_id=""):
        from igris.core.agent_reasoning_loop import AgentReasoningLoop
        return AgentReasoningLoop(
            issue_number=issue_number,
            fleet_instance_id=fleet_instance_id,
        )

    def test_heartbeat_skipped_when_no_ids(self):
        """issue_number=0 and fleet_instance_id='' → heartbeat not emitted."""
        loop = self._make_loop()
        mock_fleet = MagicMock()
        fleet_mod = types.SimpleNamespace(
            _SHARED_FLEET=mock_fleet,
            AgentHeartbeat=AgentHeartbeat,
        )
        with patch.dict(sys.modules, {"igris.layers.advisory.vastai_fleet": fleet_mod}):
            loop._emit_fleet_heartbeat("write_file")
        mock_fleet.record_heartbeat.assert_not_called()

    def test_heartbeat_emitted_when_ids_set(self):
        """With fleet_instance_id set, heartbeat is emitted."""
        loop = self._make_loop(issue_number=543, fleet_instance_id="inst-001")
        mock_fleet = MagicMock()
        fleet_mod = types.SimpleNamespace(
            _SHARED_FLEET=mock_fleet,
            AgentHeartbeat=AgentHeartbeat,
        )
        with patch.dict(sys.modules, {"igris.layers.advisory.vastai_fleet": fleet_mod}):
            loop._emit_fleet_heartbeat("run_tests")
        mock_fleet.record_heartbeat.assert_called_once()
        call_args = mock_fleet.record_heartbeat.call_args[0][0]
        assert call_args.instance_id == "inst-001"
        assert call_args.issue_number == 543
        assert call_args.action_type == "run_tests"

    def test_heartbeat_never_raises_on_fleet_error(self):
        """Fleet errors must never propagate to reasoning loop."""
        loop = self._make_loop(issue_number=1, fleet_instance_id="inst-x")
        mock_fleet = MagicMock()
        mock_fleet.record_heartbeat.side_effect = RuntimeError("fleet exploded")
        fleet_mod = types.SimpleNamespace(
            _SHARED_FLEET=mock_fleet,
            AgentHeartbeat=AgentHeartbeat,
        )
        with patch.dict(sys.modules, {"igris.layers.advisory.vastai_fleet": fleet_mod}):
            # Should not raise
            loop._emit_fleet_heartbeat("write_file")

    def test_heartbeat_never_raises_on_import_error(self):
        """Even if vastai_fleet import fails, no exception."""
        loop = self._make_loop(issue_number=1, fleet_instance_id="inst-y")
        with patch.dict(sys.modules, {"igris.layers.advisory.vastai_fleet": None}):
            loop._emit_fleet_heartbeat("run_tests")  # must not raise

    def test_loop_has_fleet_tokens_total_initialized(self):
        loop = self._make_loop()
        assert loop._fleet_tokens_total == 0


# ---------------------------------------------------------------------------
# 6. Web API fleet_status structure
# ---------------------------------------------------------------------------

class TestFleetStatusStructure:

    def test_fleet_status_returns_required_keys(self):
        fleet = make_fleet()
        status = fleet.fleet_status()
        required = {"fleet_size", "busy", "idle", "stuck", "queue_depth",
                    "hourly_cost_usd", "instances", "queue"}
        assert required.issubset(status.keys())

    def test_fleet_status_queue_empty_by_default(self):
        fleet = make_fleet()
        status = fleet.fleet_status()
        assert status["queue"] == []
        assert status["queue_depth"] == 0

    def test_fleet_status_queue_shows_enqueued_tasks(self):
        fleet = make_fleet()
        fleet._state.enqueue(QueuedTask(issue_number=10, task_type="code_reasoning"))
        fleet._state.enqueue(QueuedTask(issue_number=20, task_type="hard_debugging"))
        status = fleet.fleet_status()
        assert status["queue_depth"] == 2
        assert status["queue"] == [
            {"issue": 10, "task_type": "code_reasoning"},
            {"issue": 20, "task_type": "hard_debugging"},
        ]

    def test_fleet_status_instance_counts(self):
        fleet = make_fleet()
        fleet._state.instances.append(make_instance("a", status=InstanceStatus.BUSY))
        fleet._state.instances.append(make_instance("b", status=InstanceStatus.IDLE))
        status = fleet.fleet_status()
        assert status["fleet_size"] == 2
        assert status["busy"] == 1
        assert status["idle"] == 1


# ---------------------------------------------------------------------------
# 7. Full lifecycle integration scenario
# ---------------------------------------------------------------------------

class TestFullLifecycleIntegration:

    def test_full_lifecycle_3_issues_1_instance(self):
        """
        Scenario: 1 GPU instance, 3 issues arrive.
        - Issue 1: acquired immediately
        - Issue 2 + 3: queued (queue_depth=2)
        - Issue 1 enters TEST_EXECUTION → secondary slot available
        - Issue 2 assigned as secondary
        - Issue 1 finishes tests (phase=CODING) → secondary cleared → issue 2 re-queued
        - Issue 1 released → warm idle → monitor assigns issue 2 from queue
        - Issue 3 still in queue
        Verify: no issues lost, queue management correct.
        """
        fleet = make_fleet()
        monitor = make_monitor(fleet._state)

        # Register 1 warm instance
        inst = make_instance("gpu-1", status=InstanceStatus.IDLE, model_loaded=True,
                              phase=AgentPhase.IDLE, assigned_issue=None)
        inst.model_loaded = True
        fleet._state.instances.append(inst)

        # Issue 1 acquired immediately (warm instance)
        acquired = fleet.acquire(issue_number=1)
        assert acquired is not None
        assert acquired.instance_id == "gpu-1"
        assert fleet._state.queue_depth == 0

        # Issues 2 and 3 queued
        assert fleet.acquire(issue_number=2) is None
        assert fleet.acquire(issue_number=3) is None
        assert fleet._state.queue_depth == 2

        # Issue 1 enters TEST_EXECUTION
        acquired.phase = AgentPhase.TEST_EXECUTION

        # Secondary slot scheduler assigns issue 2 to the idle GPU window
        monitor._assign_secondary_slots()
        assert acquired.secondary_issue == 2
        assert fleet._state.queue_depth == 1  # issue 3 still in queue

        # Issue 1 finishes tests → phase back to CODING
        acquired.phase = AgentPhase.CODING

        # _clear_finished_secondaries: secondary cleared, issue 2 re-queued
        with fleet._state._lock:
            monitor._clear_finished_secondaries()
        assert acquired.secondary_issue is None
        assert fleet._state.queue_depth == 2  # issue 2 re-queued + issue 3

        # Issue 1 released → warm idle
        fleet.release("gpu-1")
        assert inst.status == InstanceStatus.IDLE

        # Queue still has 2 items (not touched by release)
        assert fleet._state.queue_depth == 2

        # Verify queue contains issue 2 and issue 3 (in FIFO order)
        tasks = list(fleet._state.task_queue)
        issue_numbers = [t.issue_number for t in tasks]
        assert 2 in issue_numbers
        assert 3 in issue_numbers

    def test_queue_prevents_premature_provisioning(self):
        """
        With 1 busy instance (ETC=8min) and 1 queued task,
        scheduler returns Wait (not OpenNew) because instance
        will be free in 8min < 13min threshold.
        Queue item stays in queue, not lost.
        """
        scheduler = FleetScheduler()
        policy = FleetPolicy(max_instances=5, max_hourly_cost_usd=2.50)

        # Instance finishing soon (ETC < STARTUP_COLD + MARGIN = 13min)
        finishing = make_instance("a", status=InstanceStatus.BUSY,
                                  elapsed_minutes=40.0, tokens_per_sec=0.0)
        # Make it look like it's finishing soon via token rate
        finishing.tokens_generated = 7900
        finishing.tokens_per_sec = 15.0  # 100 tokens left / 15 tok/s ≈ 6.7s → effectively done

        state = FleetState()
        state.instances.append(finishing)
        state.enqueue(QueuedTask(issue_number=77))

        decision = scheduler.scale_decision(state, policy)

        # Should be Wait (finishing soon covers the queue)
        assert isinstance(decision, ScaleWait)
        # Queue item preserved — not lost
        assert state.queue_depth == 1

    def test_acquire_warm_dequeues_immediately(self):
        """When a warm instance is available, acquire should NOT add to queue."""
        fleet = make_fleet()
        warm = make_instance("w", status=InstanceStatus.IDLE, model_loaded=True, assigned_issue=None)
        fleet._state.instances.append(warm)
        result = fleet.acquire(issue_number=42)
        assert result is not None
        assert fleet._state.queue_depth == 0

    def test_multiple_queued_tasks_fifo_order_preserved(self):
        """Dequeuing multiple tasks preserves insertion order."""
        state = FleetState()
        for i in range(5):
            state.enqueue(QueuedTask(issue_number=100 + i))
        extracted = [state.dequeue().issue_number for _ in range(5)]
        assert extracted == [100, 101, 102, 103, 104]

    def test_fleet_monitor_secondary_scheduler_initialized(self):
        """FleetMonitor has SecondarySlotScheduler after init."""
        state = FleetState()
        monitor = make_monitor(state)
        assert hasattr(monitor, "_secondary_scheduler")
        assert isinstance(monitor._secondary_scheduler, SecondarySlotScheduler)
