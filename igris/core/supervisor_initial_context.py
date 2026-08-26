"""Initial context builder for rank supervisor reasoning.

Extracted from ``self_repair_supervisor.py`` (ADR-IGRIS-0013 supervisor split).
Builds the initial context dict for rank reasoning: project policies, UI
visibility policies, MBOP intake fields, and prior-run lessons.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional
import logging


_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from igris.core.supervisor_models import RankSupervisorConfig, SupervisorRun


def rank_initial_context(
    supervisor: Any,
    config: "RankSupervisorConfig",
    run: Optional["SupervisorRun"] = None,
) -> Dict[str, Any]:
    context: Dict[str, Any] = {
        "rank_test": config.rank_id,
        "project_root": supervisor.project_root,
        "must_not_push_directly_to_main": True,
        "must_not_merge_if_tests_fail": True,
        "suppress_human_gate": True,
        "must_not_ask_user": True,
        "supervised": True,
        "expected_endpoint_file": "igris/web/server.py",
        "safe_edit_policy": (
            "For existing large files use insert_after, insert_before, "
            "replace_range or append_file. Never full-file write server.py."
        ),
        "fastapi_test_policy": (
            "API tests must import create_app from igris.web.server and use "
            "TestClient(create_app()). Do not import app from igris.web.server."
        ),
        "implementation_quality_policy": (
            "Write real implementation code, not stubs. "
            "Do NOT add '# Placeholder', '# TODO', '# FIXME', or 'pass' in the "
            "function body. Do NOT return empty dicts, empty lists, or empty strings "
            "as field values. The implementation will be rejected by the semantic "
            "acceptance gate if stub patterns are detected."
        ),
    }
    if supervisor._goal_prefers_tool_first(config.goal):
        context["tool_first_policy"] = (
            "For broad analysis/mapping tasks, prefer deterministic tool-first work. "
            "Collect compact facts with ripgrep/python scripts, then reason on the summary "
            "instead of loading many files into LLM context."
        )
        context["tool_first_snapshot"] = supervisor._build_tool_first_snapshot()
    if supervisor._goal_requires_ui_visibility(config.goal):
        ui_card_contract_goal = supervisor._goal_targets_rank_ui_card(config.goal)
        ui_contract_satisfied = ui_card_contract_goal and supervisor._rank_ui_card_contract_satisfied()
        context["must_add_ui_visibility"] = True
        context["ui_visibility_policy"] = (
            "If the goal requires UI/dashboard visibility, modify a UI surface "
            "such as igris/web/templates/index.html, igris/web/static/js/app.js, "
            "or igris/web/static/css/style.css. Backend-only changes are not enough."
        )
        context["ui_contract_already_satisfied"] = ui_contract_satisfied
        if ui_contract_satisfied:
            context["ui_contract_policy"] = (
                "The /api/rank/ui-card contract is already satisfied in "
                "igris/web/server.py. Do not modify this route. Focus only on "
                "minimal UI/dashboard visibility edits and related UI checks."
            )
        if ui_card_contract_goal:
            context["ui_test_policy"] = (
                "UI tests must stay minimal and exact. Do not add placeholder routes, "
                "commented example paths, or unrelated assertions. Test the exact "
                "required endpoint plus the minimal UI/dashboard visibility signal. "
                "For /api/rank/ui-card, only assert the contract keys app, rank, status, "
                "and capability. Do not assert extra JSON keys such as data."
            )
        else:
            context["ui_test_policy"] = (
                "UI/dashboard tests must stay minimal and exact for this mission. "
                "Validate only the required endpoint contract and the requested "
                "visibility signal. Do not add placeholder routes or unrelated assertions."
            )
    for target in config.targeted_tests:
        if target.startswith("tests/test_") and target.endswith(".py"):
            target_path = Path(supervisor.project_root) / target
            if target_path.exists():
                context["targeted_test_file_exists"] = target
                context["targeted_test_policy"] = (
                    f"{target} already exists. Edit this file in place when needed. "
                    "Do not rediscover tests/ and do not recreate the file."
                )
            else:
                context["must_create_test_file"] = target
                context["anti_loop_instruction"] = (
                    f"Do not repeat test discovery after tests/ is known. "
                    f"Create {target} directly."
                )
            break

    # --- Inject MBOP Phase 1 intake fields (#1040) ---
    # These let the reasoning loop know the exact target file/module and acceptance
    # criteria from the start, eliminating blind find_files exploration.
    _intake = getattr(run, "mbop_intake", None) if run is not None else None
    if _intake is not None:
        try:
            if getattr(_intake, "what", ""):
                context["mbop_what"] = str(_intake.what)[:300]
            if getattr(_intake, "where", ""):
                context["mbop_where"] = str(_intake.where)[:300]
            if getattr(_intake, "why", ""):
                context["mbop_why"] = str(_intake.why)[:300]
            if getattr(_intake, "acceptance_criteria", []):
                context["mbop_acceptance_criteria"] = list(_intake.acceptance_criteria[:10])
            if getattr(_intake, "constraints", []):
                context["mbop_constraints"] = list(_intake.constraints[:5])
            if getattr(_intake, "extraction_ok", False):
                context["mbop_intake_ok"] = True
        except (TypeError, AttributeError, ValueError) as exc:
            _log.debug("supervisor_initial_context: narrowed catch failed: %s", exc, exc_info=True)

    # --- Inject MBOP Phase 10-11 prior-run lessons for the same issue (BUG2 fix) ---
    # Phases 10-11 fire after supervisor.run() returns, so they're not available
    # during the CURRENT run's repair cycle.  However, for SUBSEQUENT runs on the
    # same issue, these lessons prevent repeating the same mistakes.
    if config.issue_number:
        try:
            from igris.core.mbop_log import read_for_issue
            prior_events = read_for_issue(str(supervisor.project_root), config.issue_number)
            # Extract most recent Phase 11 lessons and Phase 10 criteria_missing
            prior_lessons: list = []
            prior_criteria_missing: list = []
            for ev in reversed(prior_events):
                if ev.get("phase") == "mbop_phase11_post_task_eval" and not prior_lessons:
                    extra = ev.get("extra", {}) or {}
                    lessons_raw = extra.get("lessons", [])
                    prior_lessons = [str(l) for l in lessons_raw if l][:5]
            for ev in reversed(prior_events):
                if ev.get("phase") == "mbop_phase10_satisfaction_gate" and not prior_criteria_missing:
                    extra = ev.get("extra", {}) or {}
                    prior_criteria_missing = [str(c) for c in extra.get("criteria_missing", []) if c][:5]
                    break
            if prior_lessons:
                context["mbop_prior_lessons"] = prior_lessons
            if prior_criteria_missing:
                context["mbop_prior_criteria_missing"] = prior_criteria_missing
        except (ImportError, OSError, ValueError, KeyError, TypeError) as exc:
            _log.debug("supervisor_initial_context: narrowed catch failed: %s", exc, exc_info=True)

    return context
