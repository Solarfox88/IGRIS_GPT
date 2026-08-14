"""Pure helper functions extracted from SelfRepairSupervisor (Phase 2 of #1312).

These functions were originally ``@staticmethod`` methods on
``SelfRepairSupervisor``.  They are pure (no ``self`` / class-attribute
dependency) and have been extracted to this module to reduce the size of the
6,208-line monolith.  The original class retains thin delegation wrappers for
backward compatibility.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from igris.core.supervisor_models import (
    CAPABILITY_LIMIT_THRESHOLD,
    MissionPlan,
    MissionStage,
    RankSupervisorConfig,
    SupervisorRun,
    _safe_redact,
)


# ------------------------------------------------------------------
# Timestamp helpers
# ------------------------------------------------------------------

def _timestamp_to_iso(ts: Optional[float]) -> str:
    if ts is None:
        return ""
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _timestamp_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp_is_due(next_review_after: str) -> bool:
    if not str(next_review_after or "").strip():
        return True
    try:
        due = datetime.fromisoformat(str(next_review_after).replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(timezone.utc) >= due


# ------------------------------------------------------------------
# Sanitisation helpers
# ------------------------------------------------------------------

def _sanitize_escalation_value(value: Any) -> Any:
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, raw in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ("secret", "token", "password", "api_key", "authorization")):
                out[str(key)] = "[redacted]"
            else:
                out[str(key)] = _sanitize_escalation_value(raw)
        return out
    if isinstance(value, list):
        return [_sanitize_escalation_value(item) for item in value][:50]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    text = _safe_redact(value)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{6,}\b", "***REDACTED***", text)
    return text[:2000] + ("...(truncated)" if len(text) > 2000 else "")


# ------------------------------------------------------------------
# Helper-response validation
# ------------------------------------------------------------------

def _validate_helper_response(payload: Any) -> Tuple[bool, Dict[str, Any], str]:
    if not isinstance(payload, dict):
        return False, {}, "helper response is not a JSON object"
    required = [
        "diagnosis",
        "likely_supervisor_gap",
        "suggested_repair_strategy",
        "suggested_tests",
        "risk",
        "confidence",
        "requires_human_or_codex_audit",
        "must_not_complete_product_manually",
    ]
    missing = [key for key in required if key not in payload]
    normalized = {
        "diagnosis": payload.get("diagnosis", ""),
        "likely_supervisor_gap": payload.get("likely_supervisor_gap", ""),
        "suggested_repair_strategy": payload.get("suggested_repair_strategy", ""),
        "suggested_tests": payload.get("suggested_tests", []),
        "risk": payload.get("risk", "unknown"),
        "confidence": payload.get("confidence", 0),
        "requires_human_or_codex_audit": bool(payload.get("requires_human_or_codex_audit", False)),
        "must_not_complete_product_manually": bool(payload.get("must_not_complete_product_manually", False)),
        # Execution-plan fields (optional, backward-compatible).
        # advice_only is always True — helper is never an authority.
        "advice_only": True,
        "execution_plan": str(payload.get("execution_plan", "") or ""),
        "file_targets": list(payload.get("file_targets", []) or []),
        "operations": list(payload.get("operations", []) or []),
        "acceptance_matrix": list(payload.get("acceptance_matrix", []) or []),
        "required_tests": list(payload.get("required_tests", []) or []),
        "do_not_do": list(payload.get("do_not_do", []) or []),
        "retry_focus": str(payload.get("retry_focus", "") or ""),
    }
    if missing:
        return False, normalized, f"missing required helper fields: {', '.join(missing)}"
    return True, normalized, ""


# ------------------------------------------------------------------
# Cost-policy execution strategy helpers
# ------------------------------------------------------------------

def _get_max_same_failure_retries() -> int:
    """Max consecutive same-failure repairs before escalating to strong model."""
    try:
        return max(1, int(os.getenv("IGRIS_MAX_SAME_FAILURE_RETRIES", "2") or "2"))
    except (ValueError, TypeError):
        return 2


def _get_max_cost_per_run() -> float:
    """USD cap per supervised run; 0 means unlimited."""
    try:
        return max(0.0, float(os.getenv("IGRIS_MAX_COST_PER_RUN", "0") or "0"))
    except (ValueError, TypeError):
        return 0.0


def _is_codex_direct_execution_enabled() -> bool:
    """Experimental Codex direct execution — off by default.

    Only active when IGRIS_ENABLE_CODEX_DIRECT_EXECUTION=true.
    Uses its own budget: IGRIS_MAX_CODEX_DIRECT_BUDGET_USD (default 0 = disabled).
    """
    return os.getenv("IGRIS_ENABLE_CODEX_DIRECT_EXECUTION", "").lower() in ("true", "1", "yes")


def _get_max_codex_direct_budget_usd() -> float:
    """USD cap for experimental codex direct execution; 0 means disabled."""
    try:
        return max(0.0, float(os.getenv("IGRIS_MAX_CODEX_DIRECT_BUDGET_USD", "0") or "0"))
    except (ValueError, TypeError):
        return 0.0


def _get_max_cost_per_issue() -> float:
    """USD cap per issue; 0 means unlimited. Not yet enforced cross-run."""
    try:
        return max(0.0, float(os.getenv("IGRIS_MAX_COST_PER_ISSUE", "0") or "0"))
    except (ValueError, TypeError):
        return 0.0


def _strategy_for_repair(
    run: SupervisorRun,
    has_execution_plan: bool,
) -> Tuple[str, Optional[str]]:
    """Return (strategy_name, preferred_profile) for the next repair cycle.

    Rules:
    - No execution plan -> no strategy override (return empty/None).
    - same_failure_count < threshold -> mini strategy (cheap, helper-guided).
    - same_failure_count >= threshold -> strong strategy (gpt-4o escalation).

    Codex direct execution is experimental and NOT selected here; it requires
    IGRIS_ENABLE_CODEX_DIRECT_EXECUTION=true and is handled separately.
    """
    if not has_execution_plan:
        return "", None
    max_retries = _get_max_same_failure_retries()
    if run.same_failure_count >= max_retries:
        return "helper_advice_then_gpt4o_execution", "strong_execution"
    return "helper_advice_then_mini_execution", "mini_execution"


def _check_execution_budget(run: SupervisorRun) -> Optional[str]:
    """Return failure_class string if execution budget is exceeded, else None."""
    max_per_run = _get_max_cost_per_run()
    if max_per_run > 0 and run.execution_budget_used_usd >= max_per_run:
        return "execution_budget_exceeded"
    return None


# ------------------------------------------------------------------
# Telemetry / issue helpers
# ------------------------------------------------------------------

def _build_telemetry_fragment(
    time_to_first_diff_s: Optional[float],
    no_diff_count: int,
    decompose_count: int,
    attempt_outcomes: List[str],
    total_attempts: int,
) -> Dict[str, Any]:
    """Build execution-effectiveness telemetry fragment for run.report (Issue #715)."""
    denom = max(total_attempts, 1)
    return {
        "time_to_first_diff_s": time_to_first_diff_s,
        "no_diff_rate": round(no_diff_count / denom, 4),
        "decompose_rate": round(decompose_count / denom, 4),
        "attempt_outcomes": list(attempt_outcomes),
    }


def _repair_issue_already_created(run: SupervisorRun, failure: str) -> bool:
    for event in run.events:
        if event.phase != "repair_issue":
            continue
        if event.status != "success":
            continue
        if str(event.data.get("failure_class", "")) == failure:
            return True
    return False


# ------------------------------------------------------------------
# Goal classification helpers
# ------------------------------------------------------------------

def _goal_requires_backend_change(goal: str) -> bool:
    lowered = goal.lower()
    return any(token in lowered for token in ("backend", "api", "endpoint", "/api/"))


def _goal_requires_docs_or_config(goal: str) -> bool:
    lowered = goal.lower()
    return any(token in lowered for token in ("docs", "documentation", "readme", "config"))


def _goal_requires_tests(goal: str) -> bool:
    lowered = goal.lower()
    return any(token in lowered for token in ("test", "pytest", "coverage"))


def _goal_prefers_tool_first(goal: str) -> bool:
    text = (goal or "").lower()
    markers = ("analyze", "analysis", "compare", "mapping", "blueprint", "gap", "inventory", "logs", "roadmap")
    return any(m in text for m in markers)


def _goal_requires_ui_visibility(goal: str) -> bool:
    lowered = goal.lower()
    # Use word-boundary matching to avoid false positives from substrings
    # (e.g. Italian "qui" contains "ui", "visible" matches "visibility" correctly).
    _UI_PATTERNS = re.compile(
        r"\b(ui|dashboard|frontend)\b|visib",
        re.IGNORECASE,
    )
    return bool(_UI_PATTERNS.search(lowered))


def _goal_targets_rank_ui_card(goal: str) -> bool:
    lowered = goal.lower()
    if "/api/rank/ui-card" in lowered:
        return True
    if "ui-card" in lowered or "ui card" in lowered:
        return True
    return "rank card" in lowered and "ui" in lowered


def _goal_needs_preflight_decomposition(goal: str) -> bool:
    text = (goal or "").lower()
    strong_markers = (
        "memory tree",
        "hierarchy",
        "pipeline",
        "roadmap",
        "phase-2bis",
        "chunk",
        "topic",
        "global",
        "decompose",
    )
    score = sum(1 for marker in strong_markers if marker in text)
    return score >= 3 or len(text) >= 220


# ------------------------------------------------------------------
# Stage status helpers
# ------------------------------------------------------------------

def _stage_status_template(stage: MissionStage) -> Dict[str, Any]:
    return {
        "stage_id": stage.stage_id,
        "goal": stage.goal,
        "required": stage.required,
        "allowed_file_families": list(stage.allowed_file_families),
        "acceptance_criteria": list(stage.acceptance_criteria),
        "validation": list(stage.validation),
        "rollback_policy": stage.rollback_policy,
        "preserved_progress_policy": stage.preserved_progress_policy,
        "failure_classification": list(stage.failure_classification),
        "repair_strategy": stage.repair_strategy,
        "report_entry": stage.report_entry,
        "status": "pending",
        "detail": "",
        "no_op": False,
        "non_blocking_behaviors": [],
    }


def _required_stages_green(
    statuses: Dict[str, Dict[str, Any]],
    *,
    include_final_report: bool = False,
    exclude_stage_ids: Optional[Set[str]] = None,
) -> bool:
    excluded = exclude_stage_ids or set()
    for stage_id, entry in statuses.items():
        if stage_id in excluded:
            continue
        if not entry.get("required", False):
            continue
        if stage_id == "final_report" and not include_final_report:
            continue
        if entry.get("status") not in {"success", "skipped"}:
            return False
    return True


def _compute_degraded_completion(
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
    reasons: List[str] = []
    required_all_green = (
        stage_statuses is None
        or _required_stages_green(stage_statuses)
    )
    if failure_class:
        reasons.append(f"failure_class set: {failure_class}")
    if not required_all_green:
        reasons.append("not all required stages passed")
    if smoke_was_applicable and runtime_refresh_required and not post_merge_smoke_success:
        reasons.append(
            "post-merge smoke deferred; runtime refresh required but smoke not confirmed"
        )
    return bool(reasons), "; ".join(reasons)


def _stage_status_list(statuses: Dict[str, Dict[str, Any]], plan: MissionPlan) -> List[Dict[str, Any]]:
    ordered: List[Dict[str, Any]] = []
    for stage in plan.stages:
        entry = dict(statuses.get(stage.stage_id, {}))
        if entry:
            ordered.append(entry)
    return ordered


def _ui_stage_hard_forbidden_paths(
    statuses: Dict[str, Dict[str, Any]],
    config: RankSupervisorConfig,
) -> Set[str]:
    forbidden: Set[str] = set()
    if statuses.get("backend_api_change", {}).get("status") == "success":
        forbidden.add("igris/web/server.py")
    if statuses.get("backend_tests", {}).get("status") == "success":
        for target in config.targeted_tests:
            normalized = str(target or "").strip()
            if normalized:
                forbidden.add(normalized)
    return forbidden


# ------------------------------------------------------------------
# Repair prompt builders
# ------------------------------------------------------------------

def _build_reasoning_loop_repair_prompt(
    stage_id: str,
    goal: str,
    previous_reasoning_output: str,
    repair_cycle: int,
) -> str:
    """
    Costruisce un repair goal progressivo per reasoning_loop_blocked.

    Ciclo 1: semplifica il task, output minimo, approccio incrementale.
    Ciclo 2+: suddividi nel componente piu' piccolo risolvibile, ignora ottimizzazioni.
    """
    _ = previous_reasoning_output
    if repair_cycle <= 1:
        return (
            f"{goal} "
            f"(REPAIR CYCLE {repair_cycle} — previous attempt on stage '{stage_id}' "
            f"timed out or exceeded reasoning budget. "
            f"Focus ONLY on the minimal change needed. "
            f"Do not optimize, refactor, or add features beyond what the goal strictly requires. "
            f"Use an incremental approach: implement the smallest complete unit first, verify it, then stop. "
            f"Prioritise writing code and tests over exploration. Keep edits minimal, do not push.)"
        )
    return (
        f"{goal} "
        f"(REPAIR CYCLE {repair_cycle} — previous attempts on stage '{stage_id}' "
        f"were repeatedly blocked. "
        f"Break the task down to its single smallest resolvable sub-component. "
        f"Ignore all non-critical aspects, optimisations, and edge cases. "
        f"Implement only what is strictly necessary to satisfy the goal, nothing more. "
        f"Do not push.)"
    )


def _build_wrong_file_edit_repair_prompt(
    stage_id: str,
    goal: str,
    wrong_paths: List[str],
    allowed_families: List[str],
    repair_cycle: int,
) -> str:
    """
    Costruisce un repair goal per wrong_file_edit che:
    1. Elenca i file modificati fuori scope
    2. Elenca i file consentiti per lo stage
    3. Chiede di ripetere SOLO la modifica consentita
    4. Al ciclo 2+: aggiunge vincolo hard
    """
    wrong_list = "\n".join(f"  - {p}" for p in wrong_paths) if wrong_paths else "  - (unknown paths)"
    allowed_list = (
        "\n".join(f"  - {fam}" for fam in allowed_families)
        if allowed_families
        else "  - (mission-owned minimal scope)"
    )
    prompt = (
        f"{goal} "
        f"(REPAIR CYCLE {repair_cycle} — previous attempt on stage '{stage_id}' "
        f"modified files outside the allowed scope.\n"
        f"Files wrongly modified:\n{wrong_list}\n"
        f"Allowed file families:\n{allowed_list}\n"
        f"You MUST only modify files belonging to the allowed families listed above. "
        f"Repeat your edit but restrict ALL changes to the allowed files. "
        f"Do not touch any file outside the allowed families.)"
    )
    if repair_cycle >= 2:
        prompt += (
            " If you cannot complete the task within the allowed files, "
            "output ONLY the changes to allowed files and stop. "
            "Do not modify any file outside the allowed list under any circumstance."
        )
    return prompt


# ------------------------------------------------------------------
# UI visibility / test helpers
# ------------------------------------------------------------------

def _has_ui_visibility_change(files_modified: List[str]) -> bool:
    ui_markers = (
        "igris/web/templates/",
        "igris/web/static/js/",
        "igris/web/static/css/",
        ".html",
        ".js",
        ".css",
    )
    for path in files_modified:
        if any(marker in path for marker in ui_markers):
            return True
    return False


def _targeted_test_file(config: RankSupervisorConfig) -> str:
    for candidate in config.targeted_tests:
        if candidate.startswith("tests/test_") and candidate.endswith(".py"):
            return candidate
    return ""


# ------------------------------------------------------------------
# Report fragments
# ------------------------------------------------------------------

def _api_escalation_report_fragment(run: SupervisorRun) -> Dict[str, Any]:
    return {
        "api_escalation": {
            "calls_used": run.api_escalations_used,
            "calls_failed_unconfigured": run.api_escalations_failed_unconfigured,
            "budget_used_usd": round(run.api_budget_used_usd, 6),
        }
    }


# ------------------------------------------------------------------
# Capability-limit detection
# ------------------------------------------------------------------

def _record_capability_signal(run: SupervisorRun, signal: str) -> None:
    run.capability_signals[signal] = run.capability_signals.get(signal, 0) + 1


def _detect_capability_limit(run: SupervisorRun) -> Optional[str]:
    """Return the triggering signal if capability limit reached, or None.

    Fires when any single signal reaches CAPABILITY_LIMIT_THRESHOLD, or when
    the combined total of all distinct signals reaches the threshold (mixed-failure
    capability wall — e.g. one reasoning_timeout + one no_diff_repair).
    """
    for signal, count in run.capability_signals.items():
        if count >= CAPABILITY_LIMIT_THRESHOLD:
            return signal
    if sum(run.capability_signals.values()) >= CAPABILITY_LIMIT_THRESHOLD:
        _get = run.capability_signals.get
        return max(run.capability_signals, key=lambda k: _get(k, 0) or 0)
    return None


def _is_structural_ceiling(run: SupervisorRun, triggering_signal: str) -> bool:
    """Return True when the capability limit is structural, not transient.

    Only `max_steps_ceiling` (strong_execution profile exhausted its step budget)
    qualifies as a true structural ceiling.  Pure `reasoning_timeout` or
    `no_diff_repair` signals indicate transient failures where decomposition may
    still help — these go through the normal decompose path.
    """
    return run.capability_signals.get("max_steps_ceiling", 0) >= 1


def _should_fast_track_capability_limit(
    run: SupervisorRun,
    failure: str,
) -> Optional[str]:
    """Return capability signal when we should decompose immediately."""
    if failure not in {
        "reasoning_loop_blocked",
        "pytest_failure",
        "test_runner_timeout",
        "infrastructure_bug",
    }:
        return None
    return _detect_capability_limit(run)


# ------------------------------------------------------------------
# URL inference
# ------------------------------------------------------------------

def _infer_parent_issue_url(goal: str) -> Optional[str]:
    """Extract a GitHub issue URL from the goal string if present."""
    m = re.search(r"https://github\.com/[^\s\)\"']+/issues/\d+", goal)
    return m.group(0) if m else None
