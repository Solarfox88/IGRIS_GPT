"""Autonomous self-repair supervisor for controlled rank missions.

The supervisor coordinates an IGRIS rank attempt and bounded infrastructure
repair cycles. It does not expose free-form shell execution: the default
backend runs fixed argv commands only, and tests can inject a fake backend.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import shlex
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple

from igris.core.safety import redact_secrets
from igris.core.failure_memory import FailureMemory, FailureRisk
from igris.core.acceptance_gate import check_acceptance_evidence
from igris.core.supervisor_run_store import SupervisorRunStore
from igris.core.supervisor_lifecycle import (
    is_terminal_status as _lifecycle_is_terminal_status,
    configure_run_tracking as _lifecycle_configure_run_tracking,
    transition_run_status as _lifecycle_transition_run_status,
)
from igris.core.supervisor_repair_cycle import (
    collect_repair_diagnostics as _collect_repair_diagnostics_helper,
    update_same_failure_tracking as _update_same_failure_tracking_helper,
)

# AssignmentRouter — lazy import to avoid circular deps at module load
_assignment_router_available = False
try:
    from igris.core.assignment_router import AssignmentRequest, AssignmentDecision, AssignmentRouter
    from igris.core.assignment_outcomes import compute_task_signature, save_assignment_outcome
    _assignment_router_available = True
except ImportError:
    pass

# MissionBrain Advisory — lazy import, monitoring-only, never blocks run (#914)
_selected_advisory_available = False
try:
    from igris.agent.mission.selected_advisory import (
        enrich_cycle_selected as _enrich_cycle_selected,
        make_selected_monitoring_config as _make_selected_monitoring_config,
    )
    _selected_advisory_available = True
except ImportError:
    pass


REPAIRABLE_FAILURES = {
    "pytest_failure",
    "reasoning_loop_blocked",
    "max_steps",
    "ask_user",
    "missing_tests",
    "missing_ui_visibility",
    "wrong_file_edit",
    "infrastructure_bug",
    "invalid_bootstrap",
    "syntax_error",
    "semantic_incomplete",
    "test_runner_timeout",
}

FAILURE_ERROR_CODES = {
    "pytest_failure": "E001",
    "missing_tests": "E002",
    "syntax_error": "E003",
    "wrong_file_edit": "E004",
    "reasoning_loop_blocked": "E005",
    "max_steps": "E006",
    "ask_user": "E007",
    "infrastructure_bug": "E008",
    "invalid_bootstrap": "E009",
    "semantic_incomplete": "E010",
    "test_runner_timeout": "E011",
    "decomposition_required": "E012",
    "capability_ceiling_reached": "E013",
    "execution_budget_exceeded": "E014",
    "workspace_dirty": "E015",
    "destructive_diff": "E016",
    "missing_ui_visibility": "E017",
}

# Signals that accumulate across repair cycles to indicate model capability limits.
# Decomposition is triggered when any single signal reaches CAPABILITY_LIMIT_THRESHOLD,
# OR when the combined total of all signals reaches it (mixed-failure capability wall).
CAPABILITY_LIMIT_SIGNALS = frozenset({"reasoning_timeout", "pytest_hang", "no_diff_repair"})
CAPABILITY_LIMIT_THRESHOLD = 2

# Pre-flight mission planning: a lightweight read-only reasoning pass that
# estimates complexity and recommends decomposition BEFORE any code is written.
PLANNING_MAX_STEPS = 20
PLANNING_TIMEOUT_SECONDS = 60

# Required fields in a valid IGRIS decomposition response.
DECOMPOSITION_REQUIRED_FIELDS = (
    "why_too_large",
    "sub_missions",
    "first_sub_mission",
    "human_approval_required",
)

RETRYABLE_REPAIR_FAILURES = {
    "reasoning_loop_blocked",
    "missing_ui_visibility",
    "missing_tests",
    "wrong_file_edit",
    "max_steps",
    "syntax_error",
    "pytest_failure",
}

UNSAFE_STATUS_PREFIXES = (
    "?? .env",
    "?? .venv",
    "?? .pytest_cache",
    "?? __pycache__",
    "?? .igris",
)

WRITE_ACTION_TYPES = frozenset({
    "write_file",
    "insert_after",
    "insert_before",
    "replace_range",
    "append_file",
    "apply_patch",
})

AUDIT_STATUSES = {
    "audit-new",
    "audit-reviewed",
    "audit-fixed",
    "audit-deferred",
    "audit-false-positive",
}

# ---------------------------------------------------------------------------
# Epic #1074 — Run-phase constants and state-machine enum
# ---------------------------------------------------------------------------

# Default timeouts (seconds) for various supervisor phases.
DEFAULT_REPAIR_TIMEOUT_SECONDS = 300
DEFAULT_BASELINE_TIMEOUT_SECONDS = 300
DEFAULT_SMOKE_TIMEOUT_SECONDS = 60
DEFAULT_PREFLIGHT_TIMEOUT_SECONDS = 60
DEFAULT_PROVIDER_PING_TIMEOUT_SECONDS = 10

# Maximum repair cycles per run (overridden by config.max_repair_cycles).
DEFAULT_MAX_REPAIR_CYCLES = 2

# Prefix for branch names created by the supervisor.
SUPERVISOR_BRANCH_PREFIX = "rank-"

# No-diff limit: how many consecutive reasoning attempts produce no diff before
# we record a 'no_diff_repair' capability signal.
NO_DIFF_SIGNAL_THRESHOLD = 3


class RunPhase:
    """Named constants for supervisor run phases.

    These match the 'phase' field in SupervisorEvent and are used for
    structured event emission, state transitions, and log filtering.

    Phases follow the linear flow:
      created → preflight → baseline_tests → reasoning →
      diff_review → targeted_tests → full_tests → repair →
      api_escalation → decomposition → delivery → terminal

    Non-linear: 'repair' can re-enter 'reasoning'; 'decomposition' can
    branch to sub-issue creation and child autorun.
    """

    # Pre-run setup
    CREATED = "created"
    PREFLIGHT = "preflight"
    BASELINE_TESTS = "baseline_tests"

    # Main reasoning loop
    PLANNING = "planning"
    REASONING = "reasoning"

    # Post-reasoning validation
    DIFF_REVIEW = "diff_review"
    TARGETED_TESTS = "targeted_tests"
    FULL_TESTS = "full_tests"
    SMOKE = "smoke"
    SEMANTIC_GATE = "semantic_gate"

    # Recovery
    REPAIR = "repair"
    REPAIR_REASONING = "repair_reasoning"
    API_ESCALATION = "api_escalation"

    # Decomposition
    DECOMPOSITION_REQUEST = "decomposition_request"
    SUBISSUE_CREATION = "subissue_creation"
    SUBMISSION_AUTORUN = "submission_autorun"

    # Delivery
    DELIVERY = "delivery"
    PR_CREATION = "pr_creation"
    MERGE = "merge"

    # Terminal
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"

    # Meta
    WATCHDOG = "watchdog"
    BUDGET = "execution_budget"


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _safe_redact(value: Any) -> str:
    return redact_secrets(_safe_text(value))


def _failure_error_code(failure_class: str) -> str:
    return FAILURE_ERROR_CODES.get(str(failure_class or "").strip(), "E999")


# ---------------------------------------------------------------------------
# Epic #1074 — Standalone failure classifier (modularization step)
# ---------------------------------------------------------------------------

def classify_failure_from_output(
    stdout: str,
    stderr: str,
    returncode: int,
    *,
    timed_out: bool = False,
) -> str:
    """Classify a test/command output into a REPAIRABLE_FAILURES failure class.

    This is a deterministic, pure-function classifier extracted from the
    repair cycle so it can be tested and reused independently.

    Priority order (highest wins):
      1. timed_out                  → test_runner_timeout
      2. SyntaxError / IndentationError in output → syntax_error
      3. ImportError / ModuleNotFoundError        → infrastructure_bug
      4. returncode != 0 with FAILED in output   → pytest_failure
      5. returncode != 0, output empty or generic → reasoning_loop_blocked
      6. returncode == 0                         → "" (no failure)

    Returns a failure_class string from REPAIRABLE_FAILURES or "".
    """
    if timed_out:
        return "test_runner_timeout"

    combined = (stdout or "") + (stderr or "")

    if "SyntaxError" in combined or "IndentationError" in combined:
        return "syntax_error"

    if "ImportError" in combined or "ModuleNotFoundError" in combined:
        return "infrastructure_bug"

    if returncode != 0:
        if "FAILED" in combined or "AssertionError" in combined or "ERROR" in combined:
            return "pytest_failure"
        if "wrong file" in combined.lower() or "unexpected edit" in combined.lower():
            return "wrong_file_edit"
        return "reasoning_loop_blocked"

    return ""


def classify_failure_severity(failure_class: str) -> str:
    """Return severity tier for a failure class.

    Used to select repair strategy intensity:
      - critical: immediate escalation to strong model
      - high: repair with extended timeout
      - medium: standard repair cycle
      - low: soft retry (no cost escalation)
    """
    _CRITICAL = {"syntax_error", "infrastructure_bug", "invalid_bootstrap"}
    _HIGH = {"pytest_failure", "wrong_file_edit", "semantic_incomplete"}
    _MEDIUM = {"missing_tests", "missing_ui_visibility", "reasoning_loop_blocked"}
    _LOW = {"max_steps", "ask_user", "test_runner_timeout"}

    fc = str(failure_class or "").strip()
    if fc in _CRITICAL:
        return "critical"
    if fc in _HIGH:
        return "high"
    if fc in _MEDIUM:
        return "medium"
    if fc in _LOW:
        return "low"
    return "unknown"


def _command_detail(result: "CommandResult") -> str:
    parts = []
    if result.output:
        parts.append(_safe_text(result.output).rstrip())
    if result.error:
        parts.append(_safe_text(result.error).rstrip())
    return "\n".join(part for part in parts if part)


def _infer_targeted_tests(goal: str, explicit_targets: List[str]) -> List[str]:
    targets = list(explicit_targets)
    seen = set(targets)
    for match in re.findall(r"tests/test_[A-Za-z0-9_]+\.py", goal):
        if match not in seen:
            targets.append(match)
            seen.add(match)
    return targets


def _infer_dry_run(data: Dict[str, Any]) -> bool:
    if "dry_run" in data:
        return bool(data.get("dry_run"))
    return not (
        bool(data.get("allow_github_pr", False))
        or bool(data.get("allow_merge_if_green", False))
    )


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return default


def _parse_issue_number(explicit: Any, goal: str = "") -> int:
    """Extract issue number from explicit value or goal string (e.g. '#614').

    Returns 0 if not found or invalid.
    """
    try:
        if explicit:
            n = int(explicit)
            if n > 0:
                return n
    except (TypeError, ValueError):
        pass
    # Fallback: parse first #NNN from goal string
    m = re.search(r"#(\d+)", goal)
    if m:
        try:
            return int(m.group(1))
        except (TypeError, ValueError):
            pass
    return 0


@dataclass
class CommandResult:
    success: bool = False
    output: str = ""
    error: str = ""
    returncode: int = 0
    # Telemetry fields set by call_api_helper for helper A/B test tracking
    helper_model: str = ""
    helper_ab_active: bool = False
    helper_ab_alt_model: str = ""
    # Shadow mode fields (Epic #445)
    helper_ab_shadow_mode: bool = False
    helper_primary_score: float = 0.0
    helper_alt_score: float = 0.0
    helper_primary_cost_usd: float = 0.0
    helper_alt_cost_usd: float = 0.0
    helper_primary_latency_ms: int = 0
    helper_alt_latency_ms: int = 0
    helper_switch_recommendation: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "output": _safe_redact(self.output),
            "error": _safe_redact(self.error),
            "returncode": self.returncode,
        }


@dataclass
class RankSupervisorConfig:
    goal: str
    rank_id: str = "rank"
    max_rank_attempts: int = 2  # Issue #710: default ≥ 2; env-overridable via IGRIS_MAX_RANK_ATTEMPTS
    max_repair_cycles: int = 2
    allow_github_pr: bool = False
    allow_merge_if_green: bool = False
    service_restart_command: str = ""
    required_smoke_endpoints: List[str] = field(default_factory=list)
    targeted_tests: List[str] = field(default_factory=list)
    dry_run: bool = True
    defer_service_restart: bool = False
    # Idle timeout: kill the pytest subprocess only when it produces *no output*
    # for this many seconds.  A healthy (but slow) suite keeps printing dots, so
    # the timer resets on every line; only a hung/stuck process is killed.
    # 300s (5 min) accommodates individual slow integration tests that may take
    # 2-3 min without printing, while still catching genuinely hung processes.
    test_timeout_seconds: int = int(os.getenv("IGRIS_TEST_RUNNER_TIMEOUT_SECONDS", "300"))
    # Absolute ceiling: kill unconditionally after this many seconds regardless
    # of output activity (safety net against infinite-loop tests).
    test_hard_cap_seconds: int = 3600
    reasoning_timeout_seconds: int = 300
    allow_api_escalation: bool = False
    max_api_escalations_per_run: int = 0
    max_api_budget_usd: float = 0.0
    max_tokens_per_escalation: int = 600
    api_helper_model: str = "gpt-5.4-mini"
    enable_mission_planning: bool = False
    allow_auto_subissues: bool = _as_bool(os.getenv("IGRIS_ALLOW_AUTO_SUBISSUES_DEFAULT"), True)
    enable_semantic_gate: bool = True
    allow_roadmap_autoselect: bool = False
    api_helper_mode: str = ""
    # Depth counter incremented each time a child run is spawned via auto-chain.
    # Guards against infinite cascade: parent→child→grandchild→... stops at depth 2.
    autochain_depth: int = 0
    no_diff_steps_max: int = 20
    # Cross-run history: populated by the watchdog from _issue_failures so the
    # assignment router knows how many prior attempts have been made for this
    # issue.  Enables hard_debugging escalation (→ gpu_reasoning → VastAI) on
    # repeated failures instead of always starting from code_reasoning.
    prior_attempts: int = 0
    # Aggregated capability_signals from the last failed run for this issue.
    # Merged with the current run's signals before the initial AssignmentRequest
    # so that accumulated no_diff_repair / reasoning_timeout counts survive
    # across watchdog cycles.
    prior_capability_signals: Dict[str, int] = field(default_factory=dict)
    # Issue #730 — force re-validation of baseline cache even on SHA hit
    force_revalidate_baseline: bool = False
    # Issue #615 — issue number for pre-run dependency validation (0 = not set)
    issue_number: int = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RankSupervisorConfig":
        return cls(
            goal=str(data.get("goal", "")),
            rank_id=str(data.get("rank_id", "rank")),
            max_rank_attempts=max(1, int(data.get(
                "max_rank_attempts",
                int(os.getenv("IGRIS_MAX_RANK_ATTEMPTS", str(cls.max_rank_attempts))),
            ))),
            max_repair_cycles=max(0, int(data.get("max_repair_cycles", cls.max_repair_cycles))),
            allow_github_pr=_as_bool(data.get("allow_github_pr"), False),
            allow_merge_if_green=_as_bool(data.get("allow_merge_if_green"), False),
            service_restart_command=str(data.get("service_restart_command", "")),
            required_smoke_endpoints=list(data.get("required_smoke_endpoints", [])),
            targeted_tests=_infer_targeted_tests(
                str(data.get("goal", "")),
                list(data.get("targeted_tests", [])),
            ),
            dry_run=_infer_dry_run(data),
            defer_service_restart=_as_bool(data.get("defer_service_restart"), False),
            test_timeout_seconds=max(30, int(data.get("test_timeout_seconds", 300))),
            test_hard_cap_seconds=max(60, int(data.get("test_hard_cap_seconds", 3600))),
            reasoning_timeout_seconds=max(30, int(
                data.get("reasoning_timeout_seconds")
                or os.environ.get("IGRIS_REASONING_TIMEOUT_SECONDS")
                or 300
            )),
            allow_api_escalation=_as_bool(data.get("allow_api_escalation"), False),
            max_api_escalations_per_run=max(0, int(data.get("max_api_escalations_per_run", 0))),
            max_api_budget_usd=max(0.0, float(data.get("max_api_budget_usd", 0.0))),
            max_tokens_per_escalation=max(64, int(data.get("max_tokens_per_escalation", 600))),
            api_helper_model=str(data.get("api_helper_model", "gpt-5.4-mini")),
            enable_mission_planning=_as_bool(data.get("enable_mission_planning"), False),
            allow_auto_subissues=_as_bool(
                data.get("allow_auto_subissues"),
                _as_bool(os.getenv("IGRIS_ALLOW_AUTO_SUBISSUES_DEFAULT"), True),
            ),
            enable_semantic_gate=_as_bool(data.get("enable_semantic_gate"), True),
            allow_roadmap_autoselect=_as_bool(data.get("allow_roadmap_autoselect"), False),
            api_helper_mode=str(data.get("api_helper_mode", "")),
            autochain_depth=max(0, int(data.get("autochain_depth", 0) or data.get("_autochain_depth", 0))),
            no_diff_steps_max=max(1, int(data.get("no_diff_steps_max", 20))),
            prior_attempts=max(0, int(data.get("prior_attempts", 0))),
            prior_capability_signals=dict(data.get("prior_capability_signals") or {}),
            # Issue #730 — force baseline re-validation even on SHA hit
            force_revalidate_baseline=_as_bool(data.get("force_revalidate_baseline"), False),
            # Issue #615 — issue number for dependency pre-check
            issue_number=_parse_issue_number(data.get("issue_number", 0), str(data.get("goal", ""))),
        )


@dataclass
class MissionStage:
    stage_id: str
    goal: str
    required: bool
    allowed_file_families: List[str]
    acceptance_criteria: List[str]
    validation: List[str]
    rollback_policy: str
    preserved_progress_policy: str
    failure_classification: List[str]
    repair_strategy: str
    report_entry: str


@dataclass
class MissionPlan:
    mode: str
    stages: List[MissionStage]


@dataclass
class SupervisorEvent:
    phase: str
    status: str
    detail: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    audit_status: str = "audit-new"
    audit_reviewed_by: str = ""
    audit_reviewed_at: str = ""
    audit_review_id: str = ""
    audit_scope_hash: str = ""
    audit_next_review_after: str = ""
    audit_resolution_pr: str = ""
    audit_notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase,
            "status": self.status,
            "detail": _safe_redact(self.detail),
            "data": {k: _safe_redact(v) for k, v in self.data.items()},
            "timestamp": self.timestamp,
            "audit_status": self.audit_status,
            "audit_reviewed_by": self.audit_reviewed_by,
            "audit_reviewed_at": self.audit_reviewed_at,
            "audit_review_id": self.audit_review_id,
            "audit_scope_hash": self.audit_scope_hash,
            "audit_next_review_after": self.audit_next_review_after,
            "audit_resolution_pr": self.audit_resolution_pr,
            "audit_notes": _safe_redact(self.audit_notes),
        }


@dataclass
class SupervisorRun:
    run_id: str
    rank_id: str
    status: str = "running"
    outcome: str = ""
    failure_class: str = ""
    branch: str = ""
    repair_cycles_used: int = 0
    max_repair_cycles: int = 0
    api_escalations_used: int = 0
    api_escalations_failed_unconfigured: int = 0
    api_budget_used_usd: float = 0.0
    max_api_escalations_per_run: int = 0
    max_api_budget_usd: float = 0.0
    events: List[SupervisorEvent] = field(default_factory=list)
    report: Dict[str, Any] = field(default_factory=dict)
    audit_resolver: Any = None
    update_hook: Any = None
    cancel_requested: bool = False
    cancel_reason: str = ""
    # Capability-limit tracking: maps signal name → count across all attempts/repairs.
    capability_signals: Dict[str, int] = field(default_factory=dict)
    # Decomposition produced by IGRIS when capability_limit is detected.
    decomposition: Optional[Dict[str, Any]] = None
    # Pre-flight scope assessment produced by the mission planning pass.
    mission_scope: Optional[Dict[str, Any]] = None
    # Goal string copied from config so it's available in terminal callbacks.
    goal: str = ""
    # Semantic acceptance gate result (set by the gate, survives report overwrites).
    acceptance_evidence: Optional[Dict[str, Any]] = None
    # Cost-policy execution strategy telemetry.
    strategy_used: str = ""
    same_failure_count: int = 0
    last_repair_failure: str = ""
    execution_budget_used_usd: float = 0.0
    autorun_child_run_id: str = ""
    autorun_policy: str = ""
    autorun_skipped_reason: str = ""
    # MBOP Phase 1 intake — set before supervisor.run() so _rank_initial_context can read it (#1040)
    mbop_intake: Any = None  # Optional[MBOPIntakeResult]
    # Supervisor-first autonomy policy (#147)
    completion_mode: str = ""        # set at end of run; read by MBOP Phase 11
    behavior_tracker: Any = None     # BehaviorTracker instance; created in _worker

    def add(self, phase: str, status: str, detail: str = "", **data: Any) -> None:
        event = SupervisorEvent(phase=phase, status=status, detail=detail, data=data)
        if callable(self.audit_resolver):
            self.audit_resolver(event)
        self.events.append(event)
        if callable(self.update_hook):
            self.update_hook(self)

    def touch(self) -> None:
        if callable(self.update_hook):
            self.update_hook(self)

    @property
    def started_at(self) -> Optional[float]:
        """Unix timestamp of the first event, or None if no events exist."""
        return self.events[0].timestamp if self.events else None

    @property
    def last_updated_at(self) -> Optional[float]:
        """Unix timestamp of the most recent event, or None if no events exist."""
        return self.events[-1].timestamp if self.events else None

    def is_zombie(self, threshold_seconds: float = 1800.0) -> bool:
        """Return True if the run is stuck: status is 'running' but no new event
        has been recorded in the last threshold_seconds.

        A long-running but active session is not a zombie — only one that has
        stopped producing events (no actions, no updates) for an extended period.
        """
        import time
        if self.status not in ("running", "cancelling"):
            return False
        last = self.last_updated_at
        if last is None:
            return False
        return (time.time() - last) > threshold_seconds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "rank_id": self.rank_id,
            "status": self.status,
            "outcome": self.outcome,
            "failure_class": self.failure_class,
            "branch": self.branch,
            "repair_cycles_used": self.repair_cycles_used,
            "max_repair_cycles": self.max_repair_cycles,
            "api_escalations_used": self.api_escalations_used,
            "api_escalations_failed_unconfigured": self.api_escalations_failed_unconfigured,
            "api_budget_used_usd": round(self.api_budget_used_usd, 6),
            "max_api_escalations_per_run": self.max_api_escalations_per_run,
            "max_api_budget_usd": round(self.max_api_budget_usd, 6),
            "events": [e.to_dict() for e in self.events],
            "report": self.report,
            "cancel_requested": bool(self.cancel_requested),
            "cancel_reason": _safe_redact(self.cancel_reason),
            "capability_signals": dict(self.capability_signals),
            "decomposition": self.decomposition,
            "mission_scope": self.mission_scope,
            "goal": self.goal,
            "strategy_used": self.strategy_used,
            "same_failure_count": self.same_failure_count,
            "execution_budget_used_usd": round(self.execution_budget_used_usd, 6),
            "autorun_child_run_id": self.autorun_child_run_id,
            "autorun_policy": self.autorun_policy,
            "autorun_skipped_reason": self.autorun_skipped_reason,
            "completion_mode": self.completion_mode,
        }


