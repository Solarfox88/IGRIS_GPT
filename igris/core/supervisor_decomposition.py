"""Decomposition helpers extracted from SelfRepairSupervisor.

Block 3 of #1356 Phase 4.  These functions were originally instance methods on
``SelfRepairSupervisor``.  They have been extracted to this module to reduce
the size of the monolith.  The original class retains thin delegation wrappers
for backward compatibility.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

from igris.core.supervisor_models import (
    DECOMPOSITION_REQUIRED_FIELDS,
    PLANNING_MAX_STEPS,
    PLANNING_TIMEOUT_SECONDS,
    RankSupervisorConfig,
    SupervisorRun,
    _safe_redact,
)


# Short prompt template for the local decomposition attempt (max_steps=15).
DECOMP_SHORT_PROMPT = (
    "DECOMPOSE — no code, output JSON only.\n"
    "Mission: '{goal}'\n"
    "Signals: {signals}\n\n"
    "Rules:\n"
    "- Each sub-mission touches at most 1-2 files and is implementable in <40 reasoning steps.\n"
    "- Prefer 4-8 atomic sub-missions over 2-3 large ones.\n"
    "- First sub-mission must be self-contained (no deps on later ones).\n"
    "- Include concrete file paths and function names in each goal.\n\n"
    "Output ONLY:\n"
    '{{"why_too_large":"<reason>","sub_missions":[{{"title":"<t>","goal":"<g>","risk_level":"low"}}],"first_sub_mission":"<t>","human_approval_required":false}}'
)


# ------------------------------------------------------------------
# Mission planning
# ------------------------------------------------------------------

def plan_mission(
    supervisor: Any, run: SupervisorRun, config: RankSupervisorConfig
) -> Dict[str, Any]:
    """Pre-flight read-only reasoning pass: estimate scope and flag if
    decomposition is needed BEFORE any code is written.

    Returns a MissionScope dict (may be empty on planning failure — the run
    proceeds normally in that case so planning never blocks a mission).
    """
    planning_goal = (
        "PLANNING PASS — read-only analysis only, do NOT modify any files.\n\n"
        f"Mission goal: {config.goal}\n\n"
        "Analyse the codebase and output ONLY valid JSON with these fields:\n"
        "- files_to_touch: list of file paths you would need to modify\n"
        "- estimated_complexity: 'low', 'medium', or 'high'\n"
        "- decomposition_recommended: true if the mission is too large for a single attempt\n"
        "- decomposition_reason: one sentence explaining why (if recommended)\n"
        "- safe_entry_point: the smallest first concrete step\n"
        "- risks: list of strings describing potential pitfalls\n\n"
        "Output ONLY the JSON object, nothing else."
    )
    run.add(
        "mission_planning",
        "running",
        "Running pre-flight mission scope analysis (read-only)",
        max_steps=PLANNING_MAX_STEPS,
        timeout_seconds=PLANNING_TIMEOUT_SECONDS,
    )
    planner_profile = str(
        os.getenv("IGRIS_ROLE_PLANNER_PROFILE", "mini_execution")
    ).strip() or "mini_execution"
    planner_task_type = str(
        os.getenv("IGRIS_ROLE_PLANNER_TASK_TYPE", "code_reasoning")
    ).strip() or "code_reasoning"
    result = supervisor.backend.run_reasoning(
        planning_goal,
        max_steps=PLANNING_MAX_STEPS,
        initial_context={"read_only": True, "planning_pass": True},
        timeout=PLANNING_TIMEOUT_SECONDS,
        task_type=planner_task_type,
        preferred_profile=planner_profile,
    )
    raw = _safe_redact(
        result.get("final_summary") or result.get("output") or ""
    )
    scope: Dict[str, Any] = {}
    try:
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            scope = json.loads(json_match.group())
    except (json.JSONDecodeError, AttributeError):
        scope = {"raw_output": raw}
    run.add(
        "mission_planning",
        "success" if scope and "estimated_complexity" in scope else "partial",
        (
            f"Planning complete. complexity={scope.get('estimated_complexity', '?')} "
            f"decomposition_recommended={scope.get('decomposition_recommended', False)}"
        ),
        estimated_complexity=scope.get("estimated_complexity", "unknown"),
        decomposition_recommended=bool(scope.get("decomposition_recommended", False)),
        files_to_touch=list(scope.get("files_to_touch") or []),
    )
    run.mission_scope = scope
    run.report["mission_scope"] = scope
    run.report["mission_planning_profile"] = planner_profile
    run.report["mission_planning_task_type"] = planner_task_type

    # M3 — Model-aware escalation: when the local model says the mission is
    # high-complexity AND the operator has configured API escalation, ask the
    # helper for strategic advice BEFORE the first attempt.  This is purely
    # advisory: advice is recorded in run events but never blocks the run.
    if (
        scope.get("estimated_complexity") == "high"
        and config.allow_api_escalation
        and config.max_api_escalations_per_run > 0
    ):
        run.add(
            "model_aware_escalation",
            "running",
            "High complexity detected during planning — requesting advisory strategy from API helper.",
            complexity="high",
        )
        advice = supervisor._maybe_api_escalate(
            run,
            config,
            failure="high_complexity_planning",
            cycle=0,
        )
        if advice:
            run.add(
                "model_aware_escalation",
                "success",
                f"Planning-phase advisory received. strategy: "
                f"{str(advice.get('suggested_repair_strategy',''))[:120]}",
                confidence=advice.get("confidence"),
                risk=advice.get("risk"),
            )
            # Surface escalation hints in the mission scope so they're
            # visible alongside planning output.
            scope["escalation_strategy_hint"] = advice.get("suggested_repair_strategy", "")
            scope["escalation_risk"] = advice.get("risk", "")
            run.mission_scope = scope
            run.report["mission_scope"] = scope
        else:
            run.add(
                "model_aware_escalation",
                "skipped",
                "Planning-phase escalation skipped (helper not configured or budget exhausted).",
            )

    return scope


# ------------------------------------------------------------------
# Decomposition
# ------------------------------------------------------------------

def ask_igris_decompose(
    supervisor: Any, run: SupervisorRun, config: RankSupervisorConfig
) -> Dict[str, Any]:
    """Ask IGRIS to decompose a too-large mission into sub-missions.

    Uses a fallback chain:
      1. Local reasoning short-prompt (max_steps=15)
      2. API helper (if configured and budget allows)
      3. Deterministic fallback (always succeeds)
    """
    signals = dict(run.capability_signals)

    # --- emit decomposition_request event (same as before) ---
    context = supervisor._rank_initial_context(config, run=run)
    context.update({
        "decomposition_required": True,
        "capability_limit_signals": signals,
        "repair_cycles_used": run.repair_cycles_used,
        "max_repair_cycles": run.max_repair_cycles,
    })
    run.add(
        "decomposition_request",
        "running",
        f"Asking IGRIS to decompose mission. signals={signals}",
        capability_signals=signals,
        original_goal=_safe_redact(config.goal),
    )

    # --- 1. Local short-prompt attempt ---
    short_prompt = DECOMP_SHORT_PROMPT.format(
        goal=_safe_redact(config.goal),
        signals=signals,
    )
    result = supervisor.backend.run_reasoning(
        short_prompt,
        max_steps=15,
        initial_context=context,
        timeout=config.reasoning_timeout_seconds,
    )
    raw = _safe_redact(
        result.get("final_summary") or result.get("output") or ""
    )
    decomposition: Dict[str, Any] = {}
    try:
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            decomposition = json.loads(json_match.group())
    except (json.JSONDecodeError, AttributeError):
        decomposition = {}

    fields_missing = [f for f in DECOMPOSITION_REQUIRED_FIELDS if f not in decomposition]

    if not fields_missing:
        # Local reasoning succeeded
        decomposition["generated_by"] = "local_reasoning"
    else:
        prefer_deterministic = (
            str(os.getenv("IGRIS_PREFER_DETERMINISTIC_DECOMPOSITION", "true")).strip().lower() != "false"
        )
        if prefer_deterministic and supervisor._goal_needs_preflight_decomposition(config.goal):
            decomposition = supervisor._deterministic_decompose_fallback(config.goal, signals)
            fields_missing = []
        else:
            # --- 2. API helper attempt ---
            api_result = supervisor._api_helper_decompose(run, config, signals)
            if api_result is not None:
                decomposition = api_result
                fields_missing = [f for f in DECOMPOSITION_REQUIRED_FIELDS if f not in decomposition]
            else:
                # --- 3. Deterministic fallback ---
                decomposition = supervisor._deterministic_decompose_fallback(config.goal, signals)
                fields_missing = []

    fields_present = [f for f in DECOMPOSITION_REQUIRED_FIELDS if f in decomposition]
    fields_missing_final = [f for f in DECOMPOSITION_REQUIRED_FIELDS if f not in decomposition]
    decomposition["_fields_present"] = fields_present
    decomposition["_fields_missing"] = fields_missing_final
    decomposition["_capability_signals"] = signals

    run.add(
        "decomposition_response",
        "success" if not fields_missing_final else "fallback",
        (
            f"IGRIS decomposition generated via {decomposition.get('generated_by','unknown')}. "
            f"present={fields_present} missing={fields_missing_final}"
        ),
        fields_present=fields_present,
        fields_missing=fields_missing_final,
        generated_by=decomposition.get("generated_by", "unknown"),
    )
    run.decomposition = decomposition

    # Epic #1078 — DecompositionValidator quality gate.
    # Validate sub_missions structure and log a quality score so the operator
    # can identify noisy / low-quality decompositions in the audit trail.
    _sub_missions_raw = decomposition.get("sub_missions") or []
    if _sub_missions_raw:
        try:
            from igris.core.decomposition_validator import DecompositionValidator
            _val_report = DecompositionValidator().validate(_sub_missions_raw)
            run.add(
                "decomposition_quality",
                "ok" if _val_report.valid else "warning",
                (
                    f"DecompositionValidator: valid={_val_report.valid} "
                    f"score={_val_report.quality_score:.2f} "
                    f"issues={len(_val_report.issues)}"
                    + (
                        " — " + "; ".join(i.message for i in _val_report.issues[:3])
                        if _val_report.issues else ""
                    )
                ),
                quality_score=round(_val_report.quality_score, 3),
                valid=_val_report.valid,
                issue_count=len(_val_report.issues),
                issue_codes=[i.code for i in _val_report.issues],
            )
            decomposition["_quality_score"] = round(_val_report.quality_score, 3)
            decomposition["_quality_valid"] = _val_report.valid
            decomposition["_quality_issues"] = [
                {"code": i.code, "message": i.message, "index": i.index}
                for i in _val_report.issues
            ]
            decomposition["_validation_summary"] = _val_report.to_diagnostics()
        except Exception as _val_exc:
            run.add(
                "decomposition_quality",
                "skipped",
                f"DecompositionValidator unavailable: {_val_exc}",
            )

    return decomposition


def api_helper_decompose(
    supervisor: Any,
    run: SupervisorRun,
    config: RankSupervisorConfig,
    signals: Dict[str, int],
) -> Optional[Dict[str, Any]]:
    """Try to obtain a decomposition from the API helper.

    Returns a decomposition dict with generated_by='api_helper' on success,
    or None if the helper is not available, budget is exhausted, or the
    response is invalid.
    """
    # Budget check
    if run.api_escalations_used >= config.max_api_escalations_per_run:
        return None

    if not supervisor.backend.api_helper_is_configured():
        run.add(
            "decomposition_api",
            "not_configured",
            "API helper not configured; skipping decomposition escalation.",
        )
        return None

    packet: Dict[str, Any] = {
        "task": "decomposition",
        "goal": _safe_redact(config.goal),
        "signals": signals,
        "run_id": run.run_id,
        "decomposition_guidance": (
            "Prefer 4-8 atomic sub-missions over 2-3 large ones. "
            "Each sub-mission should touch at most 1-2 files and be implementable "
            "in fewer than 40 reasoning steps. Include concrete file paths and "
            "function names in each goal. The first sub-mission must be "
            "self-contained with no dependencies on later ones."
        ),
    }
    run.add(
        "decomposition_api_request",
        "running",
        "Calling API helper for decomposition.",
    )
    api_result = supervisor.backend.call_api_helper(
        packet,
        model=config.api_helper_model,
        max_tokens=512,
        timeout=45,
    )
    run.api_escalations_used += 1

    if not api_result.success:
        run.add(
            "decomposition_api_response",
            "failure",
            f"API helper decomposition failed: {_safe_redact(api_result.error)}",
        )
        return None

    # Parse response
    resp: Dict[str, Any] = {}
    try:
        resp = json.loads(api_result.output)
    except (json.JSONDecodeError, ValueError):
        pass

    why = resp.get("why_too_large", "")
    subs = resp.get("sub_missions")
    first = resp.get("first_sub_mission", "")

    if (
        why and isinstance(why, str)
        and subs and isinstance(subs, list) and len(subs) > 0
        and isinstance(first, str)
    ):
        decomp: Dict[str, Any] = {
            "why_too_large": _safe_redact(why),
            "sub_missions": subs,
            "first_sub_mission": _safe_redact(first),
            "human_approval_required": bool(resp.get("human_approval_required", True)),
            "generated_by": "api_helper",
        }
        run.add(
            "decomposition_api_response",
            "success",
            "API helper returned valid decomposition.",
        )
        return decomp

    run.add(
        "decomposition_api_response",
        "partial",
        "API helper returned incomplete decomposition; falling back.",
    )
    return None
