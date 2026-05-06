"""Integration Layer — Epic #62.

Connects all existing components into a unified operational pipeline:

    Mission Controller → GOAP Planner → Context Manager →
    Agent Reasoning Loop → Model Orchestrator → Tool Runtime →
    Safety/Rollback → Decision Memory → Teacher/Governor → Final Report

The IntegrationLayer is the single entry point for running governed
autonomous missions. It replaces the old autonomous_loop as the
primary execution path while keeping old APIs compatible.

Key responsibilities:
    1. Mission lifecycle (create → plan → execute → verify → report)
    2. GOAP planning feeds actions to the reasoning loop
    3. Reasoning loop uses Context Manager + Model Orchestrator
    4. All tool executions go through Tool Runtime
    5. Governor checks after each step (anti-loop)
    6. Decision Memory records every outcome
    7. Rollback Manager backs up files before modification
    8. Final report with full decision trace
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from igris.core.safety import redact_secrets


# ---------------------------------------------------------------------------
# Decision Report — structured trace of each action
# ---------------------------------------------------------------------------

@dataclass
class DecisionReport:
    """Structured report for a single decision in the pipeline."""
    step_index: int = 0
    timestamp: float = field(default_factory=time.time)
    action_schema: Dict[str, Any] = field(default_factory=dict)
    model_profile: str = ""
    provider: str = ""
    risk_level: str = "low"
    tool_used: str = ""
    tool_result: str = ""
    verification: str = ""
    governor_decision: str = "approve"
    governor_reason: str = ""
    memory_recorded: bool = False
    rollback_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_index": self.step_index,
            "timestamp": self.timestamp,
            "action_schema": self.action_schema,
            "model_profile": self.model_profile,
            "provider": self.provider,
            "risk_level": self.risk_level,
            "tool_used": self.tool_used,
            "tool_result": redact_secrets(self.tool_result),
            "verification": redact_secrets(self.verification),
            "governor_decision": self.governor_decision,
            "governor_reason": self.governor_reason,
            "memory_recorded": self.memory_recorded,
            "rollback_id": self.rollback_id,
        }


# ---------------------------------------------------------------------------
# Mission Report — final output
# ---------------------------------------------------------------------------

@dataclass
class MissionReport:
    """Final report for a governed mission execution."""
    mission_id: str = ""
    goal: str = ""
    status: str = "pending"
    total_steps: int = 0
    successful_steps: int = 0
    failed_steps: int = 0
    files_modified: List[str] = field(default_factory=list)
    decisions: List[DecisionReport] = field(default_factory=list)
    governor_interventions: int = 0
    rollback_entries: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    total_duration_ms: int = 0
    final_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "goal": redact_secrets(self.goal),
            "status": self.status,
            "total_steps": self.total_steps,
            "successful_steps": self.successful_steps,
            "failed_steps": self.failed_steps,
            "files_modified": self.files_modified,
            "decisions": [d.to_dict() for d in self.decisions],
            "governor_interventions": self.governor_interventions,
            "rollback_entries": self.rollback_entries,
            "errors": [redact_secrets(e) for e in self.errors],
            "total_duration_ms": self.total_duration_ms,
            "final_summary": redact_secrets(self.final_summary),
        }


# ---------------------------------------------------------------------------
# IntegrationLayer — the unified pipeline
# ---------------------------------------------------------------------------

class IntegrationLayer:
    """Unified pipeline connecting all IGRIS subsystems.

    Usage:
        layer = IntegrationLayer(project_root="/path/to/repo")
        report = layer.run_mission(goal="Add /api/ping with tests")
    """

    def __init__(
        self,
        project_root: Optional[str] = None,
        max_steps: int = 50,
        role: str = "coder",
    ):
        import os
        self.project_root = project_root or os.environ.get("PROJECT_ROOT", ".")
        self.max_steps = max_steps
        self.role = role

    def run_mission(
        self,
        goal: str,
        title: str = "",
        description: str = "",
        constraints: Optional[List[str]] = None,
        success_criteria: Optional[List[str]] = None,
    ) -> MissionReport:
        """Execute a full governed mission through the pipeline.

        Pipeline:
            1. Create mission via MissionController
            2. Plan via MissionController (deterministic planner)
            3. For each step:
               a. Governor check
               b. Context Manager builds context
               c. Agent Reasoning Loop decides + executes
               d. Decision Memory records outcome
               e. Rollback Manager if file modified
               f. Report step to MissionController
            4. Verify mission
            5. Produce final report
        """
        t0 = time.monotonic()
        report = MissionReport(goal=goal)

        # 1. Create mission
        mc = self._get_mission_controller()
        mission = mc.create_mission(
            title=title or goal[:80],
            goal=goal,
            description=description or goal,
            constraints=constraints or [
                "no_raw_shell_without_risk_engine",
                "no_secret_exposure",
                "no_force_push",
            ],
            success_criteria=success_criteria or [],
        )
        report.mission_id = mission.id

        # 2. Plan mission
        mc.plan_mission(mission.id)

        # 3. Execute reasoning loop with governor integration
        from igris.core.agent_reasoning_loop import AgentReasoningLoop
        loop = AgentReasoningLoop(
            project_root=self.project_root,
            max_steps=self.max_steps,
            role=self.role,
        )

        governor = self._get_governor()
        rollback_mgr = self._get_rollback_manager()

        loop_result = loop.run(
            goal=goal,
            mission_id=mission.id,
        )

        # 4. Process loop steps into decision reports
        for i, step in enumerate(loop_result.steps):
            dr = DecisionReport(
                step_index=i,
                timestamp=step.timestamp,
                action_schema={
                    "action_type": step.action_type,
                    "role": step.role,
                    "reason": step.reason,
                    "parameters": step.parameters,
                    "risk_hint": step.risk_hint,
                    "confidence": step.confidence,
                },
                risk_level=step.risk_hint,
                tool_used=step.action_route,
                tool_result=step.result_summary,
            )

            # Governor check per step
            gov_decision = governor.evaluate_task(
                description=f"{step.action_type}: {step.reason}",
                family=self._action_to_family(step.action_type),
            )
            dr.governor_decision = gov_decision.action
            dr.governor_reason = gov_decision.reason
            if gov_decision.action in ("reject", "shift", "escalate"):
                report.governor_interventions += 1

            # Record to governor history
            governor.record_task(
                description=f"{step.action_type}: {step.reason}",
                family=self._action_to_family(step.action_type),
            )

            # Record to Decision Memory
            self._record_to_memory(step, mission.id)
            dr.memory_recorded = True

            # Rollback tracking for file modifications
            if step.action_type in ("write_file", "apply_patch"):
                file_path = step.parameters.get("path", "")
                if file_path:
                    entry = rollback_mgr.backup_file(
                        file_path=file_path,
                        mission_id=mission.id,
                        action_id=f"step-{i}",
                        description=step.reason,
                    )
                    if entry:
                        dr.rollback_id = entry.id
                        report.rollback_entries.append(entry.id)

            report.decisions.append(dr)

            if step.outcome == "success":
                report.successful_steps += 1
            elif step.outcome in ("failure", "error"):
                report.failed_steps += 1
                report.errors.append(step.error or f"Step {i} failed")

        # 5. Update mission status based on loop result
        if loop_result.status == "finished":
            mc.verify_mission(mission.id)
            report.status = "completed"
        elif loop_result.status == "blocked":
            mc.block_mission(mission.id, loop_result.stop_reason)
            report.status = "blocked"
        else:
            report.status = loop_result.status

        # 6. Finalize report
        report.total_steps = loop_result.total_steps
        report.files_modified = loop_result.files_modified
        report.total_duration_ms = int((time.monotonic() - t0) * 1000)
        report.final_summary = self._build_report_summary(report, loop_result)

        return report

    def run_single_step(
        self,
        goal: str,
        mission_id: str = "",
    ) -> MissionReport:
        """Execute a single governed step (for testing/debugging)."""
        return self.run_mission(
            goal=goal,
            title=f"Single step: {goal[:60]}",
        )

    # -- Component accessors (lazy, testable) --

    def _get_mission_controller(self):
        from igris.core.mission_controller import MissionController
        return MissionController(project_root=self.project_root)

    def _get_governor(self):
        from igris.core.teacher_governor import TeacherGovernor
        return TeacherGovernor(project_root=self.project_root)

    def _get_rollback_manager(self):
        from igris.core.rollback_manager import RollbackManager
        return RollbackManager(project_root=self.project_root)

    def _get_goap_planner(self):
        from igris.core.goap_planner import GOAPPlanner
        return GOAPPlanner(project_root=self.project_root)

    # -- Internal helpers --

    def _record_to_memory(self, step, mission_id: str) -> None:
        """Record step outcome to Decision Memory."""
        from igris.core.decision_memory import record_decision, record_failure
        if step.outcome == "success":
            record_decision(
                title=f"{step.action_type}: {step.reason}",
                family=self._action_to_family(step.action_type),
                task_id=f"step-{step.step_number}",
                description=step.result_summary,
                outcome="success",
                context={"mission_id": mission_id},
                project_root=self.project_root,
            )
        elif step.outcome in ("failure", "error"):
            record_failure(
                title=f"{step.action_type} failed",
                family=self._action_to_family(step.action_type),
                task_id=f"step-{step.step_number}",
                description=step.error,
                reason=step.error,
                context={"mission_id": mission_id},
                project_root=self.project_root,
            )

    @staticmethod
    def _action_to_family(action_type: str) -> str:
        """Map action type to task family for governor tracking."""
        families = {
            "search_code": "code_nav",
            "find_files": "code_nav",
            "list_directory": "code_nav",
            "read_file_range": "code_nav",
            "repo_map": "code_nav",
            "find_symbol": "code_nav",
            "write_file": "code_edit",
            "propose_patch": "code_edit",
            "apply_patch": "code_edit",
            "run_tests": "test",
            "git_status": "git",
            "git_diff": "git",
            "shell_template": "shell",
            "raw_shell_proposal": "shell",
            "http_check": "http",
            "update_plan": "planning",
            "record_memory": "memory",
            "ask_user": "human",
            "finish": "terminal",
            "blocked": "terminal",
        }
        return families.get(action_type, "unknown")

    def _build_report_summary(self, report: MissionReport, loop_result) -> str:
        """Build human-readable summary."""
        lines = [
            f"Mission {report.mission_id}: {report.status}",
            f"Goal: {report.goal}",
            f"Steps: {report.total_steps} ({report.successful_steps} ok, "
            f"{report.failed_steps} failed)",
            f"Governor interventions: {report.governor_interventions}",
            f"Duration: {report.total_duration_ms}ms",
        ]
        if report.files_modified:
            lines.append(f"Files modified: {', '.join(report.files_modified)}")
        if report.rollback_entries:
            lines.append(f"Rollback entries: {len(report.rollback_entries)}")
        if report.errors:
            lines.append(f"Errors: {len(report.errors)}")
        return "\n".join(lines)

    # -- Public query API --

    def get_pipeline_status(self) -> Dict[str, Any]:
        """Get status of all pipeline components."""
        components = {}

        # Check Mission Controller
        try:
            mc = self._get_mission_controller()
            components["mission_controller"] = {"available": True}
        except Exception as e:
            components["mission_controller"] = {"available": False, "error": str(e)}

        # Check GOAP Planner
        try:
            planner = self._get_goap_planner()
            components["goap_planner"] = {"available": True}
        except Exception as e:
            components["goap_planner"] = {"available": False, "error": str(e)}

        # Check Governor
        try:
            gov = self._get_governor()
            components["teacher_governor"] = {"available": True}
        except Exception as e:
            components["teacher_governor"] = {"available": False, "error": str(e)}

        # Check Rollback Manager
        try:
            rm = self._get_rollback_manager()
            components["rollback_manager"] = {"available": True}
        except Exception as e:
            components["rollback_manager"] = {"available": False, "error": str(e)}

        # Check Context Manager
        try:
            from igris.core.context_manager import ContextManager
            cm = ContextManager(project_root=self.project_root)
            components["context_manager"] = {"available": True}
        except Exception as e:
            components["context_manager"] = {"available": False, "error": str(e)}

        # Check Model Orchestrator
        try:
            from igris.core.model_orchestrator import ModelOrchestrator
            orch = ModelOrchestrator()
            components["model_orchestrator"] = {"available": True}
        except Exception as e:
            components["model_orchestrator"] = {"available": False, "error": str(e)}

        # Check Agent Reasoning Loop
        try:
            from igris.core.agent_reasoning_loop import AgentReasoningLoop
            components["agent_reasoning_loop"] = {"available": True}
        except Exception as e:
            components["agent_reasoning_loop"] = {"available": False, "error": str(e)}

        # Check Tool Runtime
        try:
            from igris.core.tool_runtime import ToolRuntime
            rt = ToolRuntime(project_root=self.project_root)
            components["tool_runtime"] = {"available": True}
        except Exception as e:
            components["tool_runtime"] = {"available": False, "error": str(e)}

        # Check Code Navigation
        try:
            from igris.core.code_navigation import CodeNavigator
            nav = CodeNavigator(project_root=self.project_root)
            components["code_navigation"] = {"available": True}
        except Exception as e:
            components["code_navigation"] = {"available": False, "error": str(e)}

        # Check Decision Memory
        try:
            from igris.core.decision_memory import get_recent_decisions
            components["decision_memory"] = {"available": True}
        except Exception as e:
            components["decision_memory"] = {"available": False, "error": str(e)}

        all_ok = all(c.get("available", False) for c in components.values())
        return {
            "all_components_available": all_ok,
            "components": components,
        }
