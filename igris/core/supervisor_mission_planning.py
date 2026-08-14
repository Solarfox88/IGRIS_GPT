"""Mission planning and stage status helpers extracted from SelfRepairSupervisor.

Phase 3 of #1312 / #1356.  These functions were originally instance methods on
``SelfRepairSupervisor``.  They have been extracted to this module to reduce
the size of the monolith.  The original class retains thin delegation wrappers
for backward compatibility.

The functions are organised in two groups:

1. **Mission plan construction** — ``mission_is_non_trivial``, ``build_mission_plan``
2. **Stage status management** — ``init_stage_statuses``, ``set_stage_status``,
   ``track_non_blocking_behavior``, ``stage_is_already_satisfied``,
   ``ui_stage_retry_goal``, ``restore_ui_stage_scope``, ``path_in_allowed_family``,
   ``validate_new_stage_paths``
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from igris.core.supervisor_models import (
    REPAIRABLE_FAILURES,
    MissionPlan,
    MissionStage,
    RankSupervisorConfig,
    SupervisorRun,
)
from igris.core.supervisor_analysis import _required_endpoint_from_goal
from igris.core.supervisor_helpers import (
    _goal_requires_backend_change as _goal_requires_backend_change_helper,
    _goal_requires_docs_or_config as _goal_requires_docs_or_config_helper,
    _goal_requires_tests as _goal_requires_tests_helper,
    _goal_requires_ui_visibility as _goal_requires_ui_visibility_helper,
    _stage_status_list as _stage_status_list_helper,
    _stage_status_template as _stage_status_template_helper,
    _required_stages_green as _required_stages_green_helper,
    _compute_degraded_completion as _compute_degraded_completion_helper,
    _ui_stage_hard_forbidden_paths as _ui_stage_hard_forbidden_paths_helper,
)


# ------------------------------------------------------------------
# Mission plan construction
# ------------------------------------------------------------------

def mission_is_non_trivial(config: RankSupervisorConfig) -> bool:
    """Return True when the mission warrants multi-stage decomposition."""
    score = 0
    if _goal_requires_backend_change_helper(config.goal):
        score += 1
    if _goal_requires_ui_visibility_helper(config.goal):
        score += 1
    if _goal_requires_tests_helper(config.goal) or bool(config.targeted_tests):
        score += 1
    if _goal_requires_docs_or_config_helper(config.goal):
        score += 1
    lowered = config.goal.lower()
    if any(token in lowered for token in ("e2e", "end-to-end", "workflow", "ci", "merge", "restart", "smoke")):
        score += 1
    if len(config.targeted_tests) > 1:
        score += 1
    return score >= 4


def build_mission_plan(config: RankSupervisorConfig) -> MissionPlan:
    """Build the staged mission plan for a rank supervisor config."""
    if not mission_is_non_trivial(config):
        return MissionPlan(
            mode="single-stage",
            stages=[
                MissionStage(
                    stage_id="single_stage_execution",
                    goal="Execute the mission as one bounded stage with validation gates.",
                    required=True,
                    allowed_file_families=["igris/", "tests/", "docs/"],
                    acceptance_criteria=["Goal-aligned diff exists and validation gates are green."],
                    validation=["targeted tests (if configured)", "full pytest", "smoke endpoints"],
                    rollback_policy="Restore only for unsafe/off-contract diffs.",
                    preserved_progress_policy="Keep valid edits unless unsafe/off-contract.",
                    failure_classification=list(sorted(REPAIRABLE_FAILURES)),
                    repair_strategy="Use repair cycle scoped to detected failure class.",
                    report_entry="Single-stage execution status and validation results.",
                )
            ],
        )

    stages: List[MissionStage] = [
        MissionStage(
            stage_id="understand_locate",
            goal="Understand mission scope and locate relevant files before edits.",
            required=True,
            allowed_file_families=[],
            acceptance_criteria=["Relevant files identified and mission constraints captured."],
            validation=["context initialized"],
            rollback_policy="No rollback needed; no edits expected.",
            preserved_progress_policy="Always preserve stage output metadata.",
            failure_classification=["reasoning_loop_blocked", "max_steps", "ask_user"],
            repair_strategy=(
                "On reasoning_loop_blocked: reduce scope, request minimal change only. "
                "Cycle 2+: escalate to API helper with full reasoning context."
            ),
            report_entry="Understanding/locating stage result.",
        ),
        MissionStage(
            stage_id="backend_api_change",
            goal="Implement backend/API changes required by the mission.",
            required=_goal_requires_backend_change_helper(config.goal),
            allowed_file_families=["igris/web/server.py", "igris/core/"],
            acceptance_criteria=["Mission-owned backend/API behavior implemented."],
            validation=["target endpoint reachable in tests/smoke"],
            rollback_policy="Restore only unsafe/off-contract backend edits.",
            preserved_progress_policy="Preserve validated backend edits through later stage repairs.",
            failure_classification=["wrong_file_edit", "syntax_error", "reasoning_loop_blocked"],
            repair_strategy=(
                "Stage-scoped repair that keeps validated earlier stages. "
                "On reasoning_loop_blocked: reduce scope, request minimal change only. "
                "Cycle 2+: escalate to API helper with full reasoning context."
            ),
            report_entry="Backend/API stage result.",
        ),
        MissionStage(
            stage_id="backend_tests",
            goal="Add or update backend tests required by the mission.",
            required=_goal_requires_tests_helper(config.goal) or bool(config.targeted_tests),
            allowed_file_families=["tests/test_"],
            acceptance_criteria=["Backend test coverage for mission endpoint exists."],
            validation=["targeted pytest files"],
            rollback_policy="Restore only unsafe/off-contract test edits.",
            preserved_progress_policy="Preserve validated backend tests on later failures.",
            failure_classification=["missing_tests", "wrong_file_edit", "pytest_failure", "test_runner_timeout"],
            repair_strategy="Repair missing/invalid tests without deleting validated code.",
            report_entry="Backend tests stage result.",
        ),
        MissionStage(
            stage_id="ui_dashboard_change",
            goal="Apply minimal non-destructive UI/dashboard visibility changes when required.",
            required=_goal_requires_ui_visibility_helper(config.goal),
            allowed_file_families=[
                "igris/web/templates/",
                "igris/web/static/js/",
                "igris/web/static/css/",
            ],
            acceptance_criteria=["UI/dashboard visibility for mission objective is present."],
            validation=["UI/dashboard smoke checks"],
            rollback_policy="Restore only unsafe/off-contract UI edits.",
            preserved_progress_policy="Do not discard validated backend/test stages on UI failure.",
            failure_classification=["missing_ui_visibility", "wrong_file_edit", "pytest_failure", "test_runner_timeout"],
            repair_strategy="Repair only UI stage scope while preserving validated prior stages.",
            report_entry="UI/dashboard stage result.",
        ),
        MissionStage(
            stage_id="ui_dashboard_tests",
            goal="Add or update UI/dashboard smoke tests when UI stage is required.",
            required=_goal_requires_ui_visibility_helper(config.goal),
            allowed_file_families=["tests/test_"],
            acceptance_criteria=["UI/dashboard smoke tests cover the new visibility signal."],
            validation=["targeted ui/dashboard tests"],
            rollback_policy="Restore only unsafe/off-contract test edits.",
            preserved_progress_policy="Preserve validated backend/UI changes.",
            failure_classification=["pytest_failure", "wrong_file_edit", "missing_tests", "test_runner_timeout"],
            repair_strategy="Stage-scoped test repair only; do not rewrite unrelated tests.",
            report_entry="UI/dashboard tests stage result.",
        ),
        MissionStage(
            stage_id="docs_config_update",
            goal="Update docs/config only when mission explicitly requires it.",
            required=False,
            allowed_file_families=["docs/", "README", "pyproject.toml", "requirements"],
            acceptance_criteria=["Docs/config aligned with delivered behavior when relevant."],
            validation=["diff review for docs/config scope"],
            rollback_policy="Skip restore for not-applicable stage.",
            preserved_progress_policy="No-op skip is valid when stage is not relevant.",
            failure_classification=["wrong_file_edit"],
            repair_strategy="Skip with explanation when not applicable; otherwise minimal patch.",
            report_entry="Docs/config stage result.",
        ),
        MissionStage(
            stage_id="targeted_tests",
            goal="Run targeted tests for mission-owned files.",
            required=bool(config.targeted_tests),
            allowed_file_families=[],
            acceptance_criteria=["Targeted tests green."],
            validation=["pytest -q <targets>"],
            rollback_policy="No restore for test execution itself.",
            preserved_progress_policy="Preserve validated code when targeted tests fail and repair tests only.",
            failure_classification=["missing_tests", "pytest_failure", "test_runner_timeout"],
            repair_strategy="Repair targeted failures with stage-scoped cycle.",
            report_entry="Targeted tests stage result.",
        ),
        MissionStage(
            stage_id="full_pytest",
            goal="Run full pytest for repository-wide safety.",
            required=True,
            allowed_file_families=[],
            acceptance_criteria=["Full pytest green."],
            validation=["pytest -q"],
            rollback_policy="No restore for test execution itself.",
            preserved_progress_policy="Preserve validated stages and repair only failing scope.",
            failure_classification=["pytest_failure", "test_runner_timeout"],
            repair_strategy="Repair failing scope while keeping validated progress.",
            report_entry="Full pytest stage result.",
        ),
        MissionStage(
            stage_id="pr_ci_merge",
            goal="Complete PR/CI/merge workflow when enabled.",
            required=not config.dry_run,
            allowed_file_families=[],
            acceptance_criteria=["PR opened, CI green, merged when allowed."],
            validation=["gh pr checks --watch"],
            rollback_policy="No rollback for disabled workflow; mark skipped with reason.",
            preserved_progress_policy="Preserve validated branch content.",
            failure_classification=["infrastructure_bug"],
            repair_strategy="Retry delivery actions only after code validation is green.",
            report_entry="PR/CI/merge stage result.",
        ),
        MissionStage(
            stage_id="post_merge_runtime",
            goal="Pull main, restart runtime and run live smoke when enabled.",
            required=not config.dry_run,
            allowed_file_families=[],
            acceptance_criteria=["Post-merge smoke green on refreshed runtime."],
            validation=["required smoke endpoints"],
            rollback_policy="Block completion if runtime smoke fails.",
            preserved_progress_policy="Preserve merged code; classify runtime failures separately.",
            failure_classification=["infrastructure_bug", "invalid_bootstrap"],
            repair_strategy="Repair runtime/bootstrap and rerun smoke.",
            report_entry="Post-merge runtime stage result.",
        ),
        MissionStage(
            stage_id="final_report",
            goal="Emit truthful final report with per-stage statuses.",
            required=True,
            allowed_file_families=[],
            acceptance_criteria=["All required stages are green before completed status."],
            validation=["stage status audit"],
            rollback_policy="Never mark completed if required stages are missing/failed.",
            preserved_progress_policy="Stage statuses remain visible even when blocked.",
            failure_classification=["infrastructure_bug"],
            repair_strategy="Report blocked/repair honestly with stage diagnostics.",
            report_entry="Final report stage result.",
        ),
    ]
    return MissionPlan(mode="staged", stages=stages)


# ------------------------------------------------------------------
# Stage status management
# ------------------------------------------------------------------

def stage_status_template(stage: MissionStage) -> Dict[str, Any]:
    return _stage_status_template_helper(stage)


def init_stage_statuses(plan: MissionPlan) -> Dict[str, Dict[str, Any]]:
    return {stage.stage_id: stage_status_template(stage) for stage in plan.stages}


def set_stage_status(
    run: SupervisorRun,
    statuses: Dict[str, Dict[str, Any]],
    stage_id: str,
    status: str,
    detail: str,
    *,
    no_op: bool = False,
) -> None:
    if stage_id not in statuses:
        return
    entry = statuses[stage_id]
    entry["status"] = status
    entry["detail"] = detail
    entry["no_op"] = bool(no_op)
    run.add(
        "mission_stage",
        status,
        detail,
        stage_id=stage_id,
        required=entry.get("required", False),
        no_op=bool(no_op),
    )


def track_non_blocking_behavior(
    run: SupervisorRun,
    statuses: Dict[str, Dict[str, Any]],
    stage_id: str,
    code: str,
    detail: str,
) -> None:
    if stage_id not in statuses:
        return
    entry = statuses[stage_id]
    behaviors = entry.setdefault("non_blocking_behaviors", [])
    payload = {"code": code, "detail": detail}
    behaviors.append(payload)
    run.add(
        "mission_stage_behavior",
        "tracked",
        detail,
        stage_id=stage_id,
        behavior_code=code,
        blocking=False,
    )


def required_stages_green(
    statuses: Dict[str, Dict[str, Any]],
    *,
    include_final_report: bool = False,
    exclude_stage_ids: Optional[Set[str]] = None,
) -> bool:
    return _required_stages_green_helper(
        statuses,
        include_final_report=include_final_report,
        exclude_stage_ids=exclude_stage_ids,
    )


def compute_degraded_completion(
    *,
    completion_mode: str,
    runtime_refresh_required: bool,
    post_merge_smoke_success: bool,
    smoke_was_applicable: bool,
    failure_class: str,
    stage_statuses: Optional[Dict[str, Dict[str, Any]]],
) -> Tuple[bool, str]:
    """Return ``(degraded_completion, degraded_completion_reason)``.

    A completion is **clean** (degraded=False) when all of the following hold:
    - ``failure_class`` is empty
    - all required stages are green (or there is no stage system)
    - when a post-merge smoke was applicable (merge was actually attempted),
      it either passed or ``runtime_refresh_required`` was False

    Any condition that is not met makes the completion *degraded*, and an
    explicit human-readable reason string is always returned alongside
    ``degraded=True`` so that callers and the UI can surface the cause.

    ``smoke_was_applicable`` must be True only when a merge was actually
    executed (not dry-run, not merge-disabled).  When smoke is not
    applicable (dry-run / merge skipped), the ``runtime_refresh_required``
    flag is irrelevant to delivery quality and must not trigger degraded.

    Note: ``completion_mode == "verified_diff"`` alone is *not* a
    degradation signal — it describes the reasoning path, not delivery
    quality.  Only genuine delivery failures (failed stages, unconfirmed
    smoke, non-empty failure_class) trigger degraded.
    """
    return _compute_degraded_completion_helper(
        completion_mode=completion_mode,
        runtime_refresh_required=runtime_refresh_required,
        post_merge_smoke_success=post_merge_smoke_success,
        smoke_was_applicable=smoke_was_applicable,
        failure_class=failure_class,
        stage_statuses=stage_statuses,
    )


def stage_status_list(statuses: Dict[str, Dict[str, Any]], plan: MissionPlan) -> List[Dict[str, Any]]:
    return _stage_status_list_helper(statuses, plan)


def stage_is_already_satisfied(
    stage: MissionStage,
    config: RankSupervisorConfig,
    project_root: str,
) -> bool:
    if stage.stage_id == "understand_locate":
        return True
    if stage.stage_id == "backend_api_change":
        endpoint = _required_endpoint_from_goal(config.goal)
        if not endpoint:
            return False
        server_path = Path(project_root) / "igris/web/server.py"
        if not server_path.exists():
            return False
        try:
            content = server_path.read_text(encoding="utf-8").lower()
        except OSError:
            return False
        return endpoint in content
    if stage.stage_id in {"backend_tests", "ui_dashboard_tests", "targeted_tests"}:
        if not config.targeted_tests:
            return stage.stage_id == "targeted_tests"
        return all((Path(project_root) / target).exists() for target in config.targeted_tests)
    if stage.stage_id == "ui_dashboard_change":
        if not _goal_requires_ui_visibility_helper(config.goal):
            return True
        endpoint = _required_endpoint_from_goal(config.goal).replace("/", "-").strip("-")
        index_path = Path(project_root) / "igris/web/templates/index.html"
        if not index_path.exists():
            return False
        try:
            content = index_path.read_text(encoding="utf-8").lower()
        except OSError:
            return False
        return endpoint in content if endpoint else ("rank" in content and "dashboard" in content)
    return False


def ui_stage_hard_forbidden_paths(
    statuses: Dict[str, Dict[str, Any]],
    config: RankSupervisorConfig,
) -> Set[str]:
    return _ui_stage_hard_forbidden_paths_helper(statuses, config)


def ui_stage_retry_goal(
    *,
    base_goal: str,
    stage: MissionStage,
    hard_forbidden: Set[str],
    retry_attempt: int,
    invalid_paths: List[str],
) -> str:
    policy_lines = [
        "UI-only recovery policy:",
        "- Do not modify igris/web/server.py.",
        "- Do not modify validated backend endpoint contract files or validated backend tests.",
        "- Search existing UI/dashboard files first.",
        "- Modify only UI/dashboard files under igris/web/templates/, igris/web/static/js/, igris/web/static/css/.",
        "- Add minimal Rank S UI/dashboard visibility and update relevant UI/dashboard tests in their stage.",
    ]
    forbidden_line = ", ".join(sorted(hard_forbidden)) or "igris/web/server.py"
    retry_line = ""
    if retry_attempt > 0:
        retry_line = (
            f"\nRetry attempt {retry_attempt}: previous wrong_file_edit touched: "
            f"{', '.join(invalid_paths) or 'unknown paths'}."
        )
    return (
        f"{base_goal}\n\n"
        f"[stage:{stage.stage_id}] {stage.goal}\n"
        f"Allowed file families: {', '.join(stage.allowed_file_families) or 'mission-owned minimal scope'}.\n"
        f"Acceptance criteria: {'; '.join(stage.acceptance_criteria)}\n"
        + "\n".join(policy_lines)
        + f"\nHard-forbidden paths for this stage: {forbidden_line}."
        + retry_line
    )


def path_in_allowed_family(path: str, families: List[str]) -> bool:
    for family in families:
        if family.endswith("/"):
            if path.startswith(family):
                return True
            continue
        if family.endswith("test_"):
            if path.startswith(family):
                return True
            continue
        if family in {"README", "pyproject.toml", "requirements"}:
            if path == family or path.startswith(f"{family}."):
                return True
            continue
        if path == family or path.startswith(family):
            return True
    return False


def restore_ui_stage_scope(
    run: SupervisorRun,
    stage: MissionStage,
    changed_paths: Set[str],
    observed_paths: List[str],
    backend: Any,
) -> Tuple[bool, List[str]]:
    """Restore UI-stage scoped edits after wrong_file_edit.

    ``backend`` must implement the ``SupervisorBackend`` protocol
    (``restore_paths`` method).
    """
    candidates = set(changed_paths)
    for path in observed_paths:
        if path:
            candidates.add(path)
    restore_paths = sorted(
        path for path in candidates
        if path_in_allowed_family(path, stage.allowed_file_families)
    )
    restore = backend.restore_paths(restore_paths)
    run.add(
        "ui_stage_restore",
        "success" if restore.success else "failure",
        "Restoring UI-stage scoped edits after wrong_file_edit.",
        restored_paths=restore_paths,
    )
    return restore.success, restore_paths


def validate_new_stage_paths(
    stage: MissionStage,
    before_paths: Set[str],
    after_paths: Set[str],
    touched_files: List[str],
    changed_paths: Optional[Set[str]] = None,
) -> Tuple[bool, str]:
    if not stage.allowed_file_families:
        return True, ""
    paths_to_check = set(after_paths - before_paths)
    if changed_paths:
        paths_to_check.update(path for path in changed_paths if path)
    for touched in touched_files:
        normalized = str(touched or "").strip()
        if not normalized:
            continue
        if normalized.startswith("./"):
            normalized = normalized[2:]
        if normalized.startswith("b/"):
            normalized = normalized[2:]
        paths_to_check.add(normalized)
    candidate_paths = sorted(path for path in paths_to_check if path)
    if not candidate_paths:
        return True, ""
    invalid = [
        path for path in candidate_paths
        if not path_in_allowed_family(path, stage.allowed_file_families)
    ]
    if not invalid:
        return True, ""
    return False, ", ".join(invalid)
