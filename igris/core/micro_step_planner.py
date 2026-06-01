"""Deterministic MicroStepPlanner for reasoning progression (#1104)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Tuple


class MicroStep(str, Enum):
    DISCOVER = "discover"
    READ = "read"
    PLAN = "plan"
    MODIFY = "modify"
    TEST = "test"
    VERIFY = "verify"
    FINISH = "finish"


@dataclass
class MicroStepState:
    current_step: MicroStep
    goal_type: str
    discovered_files: List[str] = field(default_factory=list)
    read_files: List[str] = field(default_factory=list)
    modified_files: List[str] = field(default_factory=list)
    tests_run: List[str] = field(default_factory=list)
    verification_done: bool = False
    blocked_reason: str | None = None
    discovery_attempts: int = 0
    last_action_family: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["current_step"] = self.current_step.value
        return payload


@dataclass
class MicroStepDirective:
    expected_step: MicroStep
    allowed_action_families: List[str]
    discouraged_action_families: List[str]
    instruction: str
    should_redirect: bool = False
    redirect_reason: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "expected_step": self.expected_step.value,
            "allowed_action_families": list(self.allowed_action_families),
            "discouraged_action_families": list(self.discouraged_action_families),
            "instruction": self.instruction,
            "should_redirect": self.should_redirect,
            "redirect_reason": self.redirect_reason,
        }


DISCOVERY_ACTIONS = {"find_files", "search_code", "list_directory", "git_status"}
READ_ACTIONS = {"read_file", "read_file_range", "cat"}
MODIFY_ACTIONS = {
    "write_file",
    "append_file",
    "insert_after",
    "insert_before",
    "replace_range",
    "apply_patch",
    "propose_patch",
}
TEST_ACTIONS = {"run_tests", "pytest", "run_command"}
VERIFY_ACTIONS = {"git_diff", "git_status", "http_check"}
FINISH_ACTIONS = {"final_report", "finish", "complete", "blocked", "ask_user"}
PLAN_ACTIONS = {"update_plan", "record_memory"}

ACTION_FAMILY_MAP: Dict[str, str] = {}
for _a in DISCOVERY_ACTIONS:
    ACTION_FAMILY_MAP[_a] = "discovery"
for _a in READ_ACTIONS:
    ACTION_FAMILY_MAP[_a] = "read"
for _a in PLAN_ACTIONS:
    ACTION_FAMILY_MAP[_a] = "plan"
for _a in MODIFY_ACTIONS:
    ACTION_FAMILY_MAP[_a] = "modify"
for _a in TEST_ACTIONS:
    ACTION_FAMILY_MAP[_a] = "test"
for _a in VERIFY_ACTIONS:
    ACTION_FAMILY_MAP[_a] = "verify"
for _a in FINISH_ACTIONS:
    ACTION_FAMILY_MAP[_a] = "finish"


class MicroStepPlanner:
    """Small deterministic guide for step progression.

    Planner guides sequencing and suggests redirects, but does not hard-stop the loop.
    """

    def initialize(self, goal: str, context: Dict[str, Any]) -> MicroStepState:
        return MicroStepState(
            current_step=MicroStep.DISCOVER,
            goal_type=self._detect_goal_type(goal),
            discovered_files=list(context.get("discovered_files", []) or []),
            read_files=[],
            modified_files=[],
            tests_run=[],
            verification_done=False,
            blocked_reason=None,
        )

    def update_after_action(
        self,
        state: MicroStepState,
        action: Dict[str, Any],
        observation: Dict[str, Any],
    ) -> MicroStepState:
        action_type = str(action.get("action_type", "") or "")
        family = self._action_family(action_type)
        state.last_action_family = family
        success = bool(observation.get("success", False))

        if family == "discovery":
            state.discovery_attempts += 1
            files = observation.get("discovered_files") or observation.get("files") or []
            if isinstance(files, list):
                for fp in files:
                    if isinstance(fp, str) and fp and fp not in state.discovered_files:
                        state.discovered_files.append(fp)
            if state.discovered_files:
                state.current_step = MicroStep.READ
        elif family == "read":
            path = str(action.get("parameters", {}).get("path", "") or "")
            if path and path not in state.read_files:
                state.read_files.append(path)
            if state.read_files:
                state.current_step = MicroStep.PLAN if state.goal_type == "generic" else MicroStep.MODIFY
        elif family == "plan":
            state.current_step = MicroStep.MODIFY
        elif family == "modify":
            path = str(action.get("parameters", {}).get("path", "") or "")
            if path and path not in state.modified_files:
                state.modified_files.append(path)
            if state.modified_files:
                state.current_step = MicroStep.TEST if self._goal_requires_test(state.goal_type) else MicroStep.VERIFY
        elif family == "test":
            state.tests_run.append(action_type or "run_tests")
            state.current_step = MicroStep.VERIFY
        elif family == "verify":
            if action_type in {"git_diff", "git_status", "run_tests", "http_check"} and success:
                state.verification_done = True
                state.current_step = MicroStep.FINISH
        elif family == "finish":
            state.current_step = MicroStep.FINISH
            if action_type == "blocked":
                state.blocked_reason = str(action.get("parameters", {}).get("reason", "") or "blocked")

        return state

    def next_directive(self, state: MicroStepState, context: Dict[str, Any]) -> MicroStepDirective:
        expected = state.current_step
        if expected == MicroStep.DISCOVER:
            return MicroStepDirective(
                expected_step=expected,
                allowed_action_families=["discovery", "read"],
                discouraged_action_families=["modify", "test", "finish"],
                instruction="Discover target files, then read the most relevant one.",
            )
        if expected == MicroStep.READ:
            return MicroStepDirective(
                expected_step=expected,
                allowed_action_families=["read", "discovery"],
                discouraged_action_families=["test", "finish"],
                instruction="Read discovered targets. Do not repeat discovery if targets already exist.",
            )
        if expected == MicroStep.PLAN:
            return MicroStepDirective(
                expected_step=expected,
                allowed_action_families=["plan", "modify", "read"],
                discouraged_action_families=["discovery", "finish"],
                instruction="Create a concise plan for edits, then move to modify.",
            )
        if expected == MicroStep.MODIFY:
            return MicroStepDirective(
                expected_step=expected,
                allowed_action_families=["modify", "read"],
                discouraged_action_families=["discovery", "finish"],
                instruction="Apply the smallest safe edits aligned to acceptance criteria.",
            )
        if expected == MicroStep.TEST:
            return MicroStepDirective(
                expected_step=expected,
                allowed_action_families=["test", "verify", "modify"],
                discouraged_action_families=["discovery", "finish"],
                instruction="Run tests relevant to modified files before verification.",
            )
        if expected == MicroStep.VERIFY:
            return MicroStepDirective(
                expected_step=expected,
                allowed_action_families=["verify", "test", "finish"],
                discouraged_action_families=["discovery"],
                instruction="Verify diff/status and readiness for completion.",
            )
        return MicroStepDirective(
            expected_step=MicroStep.FINISH,
            allowed_action_families=["finish", "verify"],
            discouraged_action_families=["discovery", "modify"],
            instruction="Finish with summary once verification is complete.",
        )

    def should_redirect_action(self, state: MicroStepState, proposed_action: Dict[str, Any]) -> Tuple[bool, str]:
        action_type = str(proposed_action.get("action_type", "") or "")
        family = self._action_family(action_type)
        if family == "discovery" and state.current_step in {
            MicroStep.READ,
            MicroStep.PLAN,
            MicroStep.MODIFY,
            MicroStep.TEST,
            MicroStep.VERIFY,
        }:
            if state.discovered_files and not self._allow_rediscovery(state, proposed_action):
                return True, "Do not repeat discovery; read the discovered target files."
        return False, ""

    def to_context(self, state: MicroStepState, directive: MicroStepDirective) -> Dict[str, Any]:
        return {
            "micro_step_current": state.current_step.value,
            "micro_step_goal_type": state.goal_type,
            "micro_step_allowed_action_families": list(directive.allowed_action_families),
            "micro_step_discouraged_action_families": list(directive.discouraged_action_families),
            "micro_step_instruction": directive.instruction[:240],
            "micro_step_redirect_reason": (directive.redirect_reason or "")[:240],
        }

    @staticmethod
    def _detect_goal_type(goal: str) -> str:
        text = str(goal or "").lower()
        if any(m in text for m in ["/api/", "endpoint", "route", "fastapi"]):
            return "endpoint_api"
        if any(m in text for m in ["fix", "bug", "failing test", "traceback", "error"]):
            return "bugfix"
        if any(m in text for m in ["add test", "pytest", "coverage"]):
            return "add_test"
        if any(m in text for m in ["docs", "readme", ".md", "config", ".yml", ".yaml"]):
            return "doc_config"
        return "generic"

    @staticmethod
    def _goal_requires_test(goal_type: str) -> bool:
        return goal_type not in {"doc_config"}

    @staticmethod
    def _action_family(action_type: str) -> str:
        return ACTION_FAMILY_MAP.get(action_type, "generic")

    @staticmethod
    def _allow_rediscovery(state: MicroStepState, proposed_action: Dict[str, Any]) -> bool:
        if not state.discovered_files:
            return True
        text = str(proposed_action.get("reason", "") or "").lower()
        text += " " + str(proposed_action.get("parameters", {}).get("pattern", "") or "").lower()
        # Controlled rediscovery if previous discovery was empty/wrong-file context.
        if "wrong file" in text or "wrong_file" in text:
            return True
        if "no file" in text or "not found" in text:
            return True
        return False
