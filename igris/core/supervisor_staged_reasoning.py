"""Extracted staged-reasoning executor for the self-repair supervisor.

This module contains :func:`execute_staged_reasoning`, the per-stage mission
reasoning loop previously inlined as
``SelfRepairSupervisor._execute_staged_reasoning``. The logic is identical —
only the ``self`` receiver has been replaced with an explicit ``supervisor``
parameter so the function can live outside the class.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Set, Tuple

from igris.core.supervisor_analysis import (
    _changed_paths_between_diffs,
    _diff_changed_paths,
    _extract_attempted_write_paths,
    _has_ui_surface_change,
    classify_failure,
)

if TYPE_CHECKING:
    from igris.core.supervisor_models import (
        MissionPlan,
        RankSupervisorConfig,
        SupervisorRun,
    )


def execute_staged_reasoning(
    supervisor: Any,
    run: "SupervisorRun",
    config: "RankSupervisorConfig",
    plan: "MissionPlan",
    statuses: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, Any], str, bool]:
    aggregated_files: List[str] = []
    summaries: List[str] = []
    stage_failure = ""
    runtime_refresh_required = False
    last_status = "finished"
    last_stop_reason = "finish"
    loop_ids: List[str] = []

    for stage in plan.stages:
        if stage.stage_id in {"targeted_tests", "full_pytest", "pr_ci_merge", "post_merge_runtime", "final_report"}:
            continue

        if not stage.required and stage.stage_id == "docs_config_update" and not supervisor._goal_requires_docs_or_config(config.goal):
            supervisor._set_stage_status(
                run,
                statuses,
                stage.stage_id,
                "skipped",
                "Optional docs/config stage skipped: mission does not require docs/config updates.",
                no_op=True,
            )
            continue

        if not stage.required:
            supervisor._set_stage_status(
                run,
                statuses,
                stage.stage_id,
                "skipped",
                "Stage is optional for this mission and was skipped.",
                no_op=True,
            )
            continue

        current_status = statuses.get(stage.stage_id, {}).get("status")
        if current_status in {"success", "skipped"}:
            supervisor._set_stage_status(
                run,
                statuses,
                stage.stage_id,
                "success",
                "Stage already validated; preserving progress across attempts.",
                no_op=True,
            )
            continue

        if supervisor._stage_is_already_satisfied(stage, config):
            supervisor._set_stage_status(
                run,
                statuses,
                stage.stage_id,
                "success",
                "Stage already satisfied; marked complete as no-op.",
                no_op=True,
            )
            continue

        if stage.stage_id == "understand_locate":
            supervisor._set_stage_status(
                run,
                statuses,
                stage.stage_id,
                "success",
                "Mission scope classified and relevant files located.",
                no_op=True,
            )
            continue

        ui_retry_attempt = 0
        ui_retry_budget = 2
        ui_retry_invalid_paths: List[str] = []
        ui_seen_paths: Set[str] = set()
        ui_hard_forbidden = (
            supervisor._ui_stage_hard_forbidden_paths(statuses, config)
            if stage.stage_id == "ui_dashboard_change"
            else set()
        )
        while True:
            before_diff = supervisor.backend.git_diff()
            before_paths = set(_diff_changed_paths(before_diff.output))
            stage_goal = (
                supervisor._ui_stage_retry_goal(
                    base_goal=config.goal,
                    stage=stage,
                    hard_forbidden=ui_hard_forbidden,
                    retry_attempt=ui_retry_attempt,
                    invalid_paths=ui_retry_invalid_paths,
                )
                if stage.stage_id == "ui_dashboard_change"
                else (
                    f"{config.goal}\n\n"
                    f"[stage:{stage.stage_id}] {stage.goal}\n"
                    f"Allowed file families: {', '.join(stage.allowed_file_families) or 'mission-owned minimal scope'}.\n"
                    f"Acceptance criteria: {'; '.join(stage.acceptance_criteria)}"
                )
            )
            stage_context = supervisor._rank_initial_context(config, run=run)
            stage_context.update({
                "mission_orchestration_mode": plan.mode,
                "mission_stage_id": stage.stage_id,
                "mission_stage_goal": stage.goal,
                "mission_stage_allowed_file_families": stage.allowed_file_families,
                "mission_stage_acceptance_criteria": stage.acceptance_criteria,
                "mission_stage_validation": stage.validation,
                "mission_stage_repair_strategy": stage.repair_strategy,
            })
            rank_task_type = (
                "semantic_repair"
                if stage.stage_id and "endpoint" in str(stage.stage_id).lower()
                else "code_reasoning"
            )
            run.add(
                "rank_reasoning",
                "running",
                f"Running staged mission reasoning: {stage.stage_id}",
                stage_id=stage.stage_id,
                timeout_seconds=config.reasoning_timeout_seconds,
                task_type=rank_task_type,
            )
            result = supervisor.backend.run_reasoning(
                stage_goal,
                max_steps=140,
                initial_context=stage_context,
                timeout=config.reasoning_timeout_seconds,
                task_type=rank_task_type,
            )
            status = str(result.get("status", ""))
            stop_reason = str(result.get("stop_reason", ""))
            files_modified = list(result.get("files_modified") or [])
            attempted_write_paths = _extract_attempted_write_paths(result)
            if files_modified:
                for path in files_modified:
                    if path not in aggregated_files:
                        aggregated_files.append(path)
            summaries.append(f"[{stage.stage_id}] {result.get('final_summary', '')}")
            loop_id = str(result.get("loop_id", ""))
            if loop_id:
                loop_ids.append(loop_id)
            run.add(
                "rank_reasoning",
                status,
                result.get("final_summary", ""),
                stage_id=stage.stage_id,
                loop_id=loop_id,
                stop_reason=stop_reason,
                files_modified=files_modified,
                attempted_write_paths=attempted_write_paths,
                orchestrator_used=result.get("orchestrator_used", False),
                reasoning_execution_provider=result.get("reasoning_execution_provider", ""),
                reasoning_execution_model=result.get("reasoning_execution_model", ""),
                reasoning_execution_profile=result.get("reasoning_execution_profile", ""),
                local_model_available=result.get("local_model_available", False),
            )
            after_diff = supervisor.backend.git_diff()
            after_paths = set(_diff_changed_paths(after_diff.output))
            changed_paths = _changed_paths_between_diffs(before_diff.output, after_diff.output)
            observed_paths = list(dict.fromkeys(files_modified + attempted_write_paths + sorted(changed_paths)))
            valid_paths, invalid_paths = supervisor._validate_new_stage_paths(
                stage,
                before_paths,
                after_paths,
                observed_paths,
                changed_paths=changed_paths,
            )
            if not valid_paths:
                invalid_path_list = [path.strip() for path in invalid_paths.split(",") if path.strip()]
                if stage.stage_id == "ui_dashboard_change":
                    for path in observed_paths:
                        if supervisor._path_in_allowed_family(path, stage.allowed_file_families):
                            ui_seen_paths.add(path)
                    if any(path in ui_hard_forbidden for path in invalid_path_list):
                        ui_retry_invalid_paths = invalid_path_list
                        restored_ok, restored_paths = supervisor._restore_ui_stage_scope(
                            run,
                            stage,
                            changed_paths,
                            observed_paths,
                        )
                        if not restored_ok:
                            supervisor._set_stage_status(
                                run,
                                statuses,
                                stage.stage_id,
                                "failure",
                                "UI-stage recovery failed while restoring stage-local edits.",
                            )
                            stage_failure = "wrong_file_edit"
                            last_status = status or "blocked"
                            last_stop_reason = stop_reason or "blocked"
                            break
                        if ui_retry_attempt < ui_retry_budget:
                            ui_retry_attempt += 1
                            run.add(
                                "ui_stage_retry",
                                "running",
                                "Retrying ui_dashboard_change with UI-only constraints after stage-local wrong_file_edit.",
                                retry_attempt=ui_retry_attempt,
                                retry_budget=ui_retry_budget,
                                hard_forbidden=sorted(ui_hard_forbidden),
                                restored_paths=restored_paths,
                                invalid_paths=invalid_path_list,
                            )
                            continue
                        searched = sorted(ui_seen_paths) or ["(none)"]
                        supervisor._set_stage_status(
                            run,
                            statuses,
                            stage.stage_id,
                            "failure",
                            "UI-only recovery exhausted after repeated wrong_file_edit attempts. "
                            f"UI files searched/touched: {', '.join(searched)}. "
                            f"Attempted forbidden edits: {', '.join(sorted(set(ui_retry_invalid_paths)) or ['(none)'])}.",
                        )
                        stage_failure = "wrong_file_edit"
                        last_status = status or "blocked"
                        last_stop_reason = stop_reason or "blocked"
                        break
                supervisor._set_stage_status(
                    run,
                    statuses,
                    stage.stage_id,
                    "failure",
                    f"Stage touched out-of-scope files: {invalid_paths}",
                )
                stage_failure = "wrong_file_edit"
                last_status = status or "blocked"
                last_stop_reason = stop_reason or "blocked"
                break
            # Guard: a required stage with allowed_file_families that produced no
            # diff and is not pre-satisfied must be treated as failure, not success.
            # Without this check _validate_new_stage_paths returns (True, "") for
            # empty candidate_paths, and the stage falls through to success —
            # a false positive ("stage required segnato success senza evidence").
            # Only fires when status == "finished": timeout/blocked paths are handled
            # by the existing `if status != "finished":` block below.
            if (
                status == "finished"
                and stage.required
                and stage.allowed_file_families
                and not changed_paths
                and not observed_paths
                and not supervisor._stage_is_already_satisfied(stage, config)
            ):
                supervisor._set_stage_status(
                    run,
                    statuses,
                    stage.stage_id,
                    "failure",
                    f"Required stage '{stage.stage_id}' produced no file changes "
                    "and is not already satisfied.",
                )
                stage_failure = "reasoning_loop_blocked"
                last_status = status or "blocked"
                last_stop_reason = stop_reason or "no_change"
                break
            runtime_refresh_required = runtime_refresh_required or any(str(path).startswith("igris/") for path in files_modified)
            if status != "finished":
                if (
                    stage.stage_id == "ui_dashboard_change"
                    and stop_reason in {"reasoning_timeout", "budget_exceeded"}
                ):
                    has_ui_diff = _has_ui_surface_change(after_diff.output)
                    stage_satisfied = supervisor._stage_is_already_satisfied(stage, config)
                    if has_ui_diff or stage_satisfied:
                        supervisor._track_non_blocking_behavior(
                            run,
                            statuses,
                            stage.stage_id,
                            "ui_stage_timeout_accepted",
                            "UI stage timed out but validated UI visibility evidence was present; accepting stage with degraded status.",
                        )
                        supervisor._set_stage_status(
                            run,
                            statuses,
                            stage.stage_id,
                            "success",
                            "UI stage accepted after timeout because mission-owned UI visibility evidence is present.",
                        )
                        last_status = "finished"
                        last_stop_reason = stop_reason or "reasoning_timeout"
                        break
                if status in {"blocked", "error", "stopped"} or stop_reason in {"blocked", "ask_user", "max_steps", "reasoning_timeout", "budget_exceeded"}:
                    supervisor._set_stage_status(
                        run,
                        statuses,
                        stage.stage_id,
                        "failure",
                        result.get("final_summary", "") or f"Stage {stage.stage_id} did not finish cleanly.",
                    )
                    stage_failure = classify_failure(reasoning_result=result)
                    last_status = status
                    last_stop_reason = stop_reason
                    break
                supervisor._track_non_blocking_behavior(
                    run,
                    statuses,
                    stage.stage_id,
                    "degraded_reasoning",
                    f"Stage {stage.stage_id} accepted with degraded reasoning status {status}/{stop_reason}.",
                )
            supervisor._set_stage_status(
                run,
                statuses,
                stage.stage_id,
                "success",
                result.get("final_summary", "") or f"Stage {stage.stage_id} completed.",
            )
            last_status = status or "finished"
            last_stop_reason = stop_reason or "finish"
            break
        if stage_failure:
            break

    aggregated = {
        "status": last_status,
        "stop_reason": last_stop_reason,
        "files_modified": aggregated_files,
        "final_summary": "\n".join(part for part in summaries if part).strip(),
        "loop_id": ",".join(loop_ids),
        "goal": config.goal,
    }
    return aggregated, stage_failure, runtime_refresh_required
