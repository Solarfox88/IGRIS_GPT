"""Decomposition helpers extracted from SelfRepairSupervisor.

Block 3 of #1356 Phase 4.  These functions were originally instance methods on
``SelfRepairSupervisor``.  They have been extracted to this module to reduce
the size of the monolith.  The original class retains thin delegation wrappers
for backward compatibility.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from igris.core.supervisor_models import (
    DECOMPOSITION_REQUIRED_FIELDS,
    PLANNING_MAX_STEPS,
    PLANNING_TIMEOUT_SECONDS,
    MissionPlan,
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


# ------------------------------------------------------------------
# Deterministic decomposition fallback
# ------------------------------------------------------------------

def deterministic_decompose_fallback(
    goal: str,
    signals: Dict[str, int],
) -> Dict[str, Any]:
    """Always produce a syntactically complete decomposition from the goal text.

    Parsing strategy (in order of priority):
    1. Numbered/bulleted list items in the goal (\\n- / \\n* / \\n1. / \\n2. etc.)
    2. Semicolon-separated clauses (;)
    3. Semantic split: if goal mentions endpoint/API → 2 sub-missions
       (backend implementation + test coverage). Never split on '.' or ','
       because those are sentence/decimal separators, not list boundaries.
    4. Last resort: treat the entire goal as a single sub-mission.
    """

    def _infer_risk(text: str) -> str:
        t = text.lower()
        if any(k in t for k in ("zombie", "orphan", "delete", "destroy", "drop")):
            return "high"
        if any(k in t for k in ("report", "badge", "endpoint", "api", "dashboard")):
            return "medium"
        return "low"

    def _infer_file_scopes(text: str) -> List[str]:
        t = text.lower()
        if any(k in t for k in ("endpoint", "api", "server", "route")):
            return ["igris/web/server.py", "igris/core/"]
        if any(k in t for k in ("dashboard", "badge", "ui", "card")):
            return ["igris/web/static/**", "igris/web/templates/**"]
        # Memory Tree specific layers — most precise match first
        if any(k in t for k in ("memory_content_store", "content_store")):
            return ["igris/core/memory_content_store.py", "tests/test_memory_content_store.py"]
        if any(k in t for k in ("memory_scorer", "memoryscorer")):
            return ["igris/core/memory_scorer.py", "tests/test_memory_scorer.py"]
        if any(k in t for k in ("topic_tree", "topictree", "global_digest", "globaldigest")):
            return [
                "igris/core/memory_topic_tree.py",
                "igris/core/memory_global_digest.py",
                "tests/test_memory_topic_tree.py",
            ]
        if any(k in t for k in ("memory tree", "memory_tree", "memorytree",
                                 "memory chunker", "memory_chunker")):
            return [
                "igris/core/memory_chunker.py",
                "igris/core/memory_graph.py",
                "igris/core/",
                "tests/",
            ]
        # Broader memory/hierarchy patterns
        if any(k in t for k in ("memory", "chunk", "score", "topic", "global", "hierarchy")):
            return ["igris/core/", "tests/"]
        if "test" in t:
            return ["tests/"]
        if any(k in t for k in ("supervisor", "repair")):
            return ["igris/core/self_repair_supervisor.py"]
        # #913: fallback is now igris/core/ + tests/ instead of igris/**
        # A broad igris/** scope caused no_diff_repair loops because Igris
        # could not determine which file to edit.
        return ["igris/core/", "tests/"]

    def _infer_test_targets(text: str) -> List[str]:
        # Extract explicit test file paths like tests/test_foo.py
        matches = re.findall(r"tests/[\w/]+\.py", text)
        if matches:
            return matches
        if "test" in text.lower():
            return ["tests/"]
        return []

    def _make_sub(
        title: str,
        goal_text: str,
        *,
        explicit_file_scopes: Optional[List[str]] = None,
        explicit_acceptance_criteria: Optional[List[str]] = None,
        explicit_tests: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Build a sub-mission dict.

        When explicit_* params are provided they take precedence over inference.
        Anti-loop guard (#913): if both scopes and criteria are generic the sub-
        mission is flagged human_approval_required=True so a human can refine them
        before Igris runs — preventing the no_diff_repair → fallback loop.
        """
        safe = _safe_redact(goal_text)
        scopes = (
            explicit_file_scopes
            if explicit_file_scopes is not None
            else _infer_file_scopes(goal_text)
        )
        criteria = (
            explicit_acceptance_criteria
            if explicit_acceptance_criteria is not None
            else [f"{title} implemented and validated"]
        )
        tests = (
            explicit_tests
            if explicit_tests is not None
            else _infer_test_targets(goal_text)
        )
        # Anti-loop guard: broad scope + generic criterion → require human review.
        # This prevents Igris from entering a no_diff_repair loop where it cannot
        # determine which file to edit or how to verify success.
        _broad_scopes = {"igris/core/", "tests/", "igris/**"}
        _scope_is_broad = set(scopes) <= _broad_scopes
        _criteria_generic = criteria == [f"{title} implemented and validated"]
        human_approval = _scope_is_broad and _criteria_generic
        return {
            "title": title[:60],
            "goal": safe,
            "dependencies": [],
            "acceptance_criteria": criteria,
            "allowed_file_scopes": scopes,
            "tests": tests,
            "risk_level": _infer_risk(goal_text),
            "human_approval_required": human_approval,
        }

    safe_goal = _safe_redact(str(goal))

    # --- Strategy 1: explicit bulleted/numbered list items ---
    bullet_parts = re.split(r"\n\s*(?:[-*]|\d+\.)\s+", safe_goal)
    # Only use bullet split if it produced ≥2 meaningful items (each ≥30 chars)
    bullet_items = [p.strip() for p in bullet_parts if len(p.strip()) >= 30]
    if len(bullet_items) >= 2:
        components = bullet_items[:4]
        sub_missions = [_make_sub(c[:50].capitalize(), c) for c in components]
        why = (
            f"Mission contains {len(components)} explicit list items requiring separate "
            f"reasoning passes. Signals: {signals}"
        )
        return {
            "why_too_large": _safe_redact(why),
            "sub_missions": sub_missions,
            "first_sub_mission": sub_missions[0]["title"],
            "human_approval_required": True,
            "generated_by": "deterministic_fallback",
        }

    # --- Strategy 2: semicolon-separated clauses ---
    semi_parts = [p.strip() for p in safe_goal.split(";") if len(p.strip()) >= 30]
    if len(semi_parts) >= 2:
        components = semi_parts[:4]
        sub_missions = [_make_sub(c[:50].capitalize(), c) for c in components]
        why = (
            f"Mission contains {len(components)} semicolon-delimited components. "
            f"Signals: {signals}"
        )
        return {
            "why_too_large": _safe_redact(why),
            "sub_missions": sub_missions,
            "first_sub_mission": sub_missions[0]["title"],
            "human_approval_required": True,
            "generated_by": "deterministic_fallback",
        }

    # --- Strategy 3: semantic split for endpoint/API missions ---
    gl = safe_goal.lower()
    is_endpoint_mission = any(k in gl for k in ("endpoint", "/api/", "get /", "post /", "put /"))
    has_test_requirement = "test" in gl
    if is_endpoint_mission:
        # Sub-mission 1: backend implementation
        impl_goal = (
            f"{safe_goal.rstrip('.')}. "
            "Focus on implementing the backend endpoint logic only. "
            "Do not write tests in this sub-mission."
        )
        # Sub-mission 2: test coverage (only if tests mentioned)
        sub_missions = [_make_sub("Backend endpoint implementation", impl_goal)]
        if has_test_requirement:
            test_files = _infer_test_targets(safe_goal) or ["tests/"]
            test_goal = (
                f"Add comprehensive test coverage for: {safe_goal[:200]}. "
                f"Write tests in {', '.join(test_files)}. "
                "Assume the endpoint is already implemented."
            )
            sub_missions.append(_make_sub("Test coverage", test_goal))
        return {
            "why_too_large": _safe_redact(
                f"Endpoint mission split into {len(sub_missions)} semantic sub-missions "
                f"(implementation + tests). Signals: {signals}"
            ),
            "sub_missions": sub_missions,
            "first_sub_mission": sub_missions[0]["title"],
            "human_approval_required": True,
            "generated_by": "deterministic_fallback",
        }

    # --- Strategy 4: semantic split for memory-tree hierarchy missions ---
    # #913: Rewrote from 4 generic sub-missions to 5 explicit, bounded steps.
    # Each step has: precise file_scopes, verifiable acceptance_criteria, explicit tests.
    # Step 0 is read-only (architecture plan) and gates the implementation steps.
    # human_approval_required=True so a human confirms the plan before Igris runs code.
    is_memory_tree_mission = (
        "memory tree" in gl
        and any(k in gl for k in ("chunk", "score", "topic", "global", "pipeline", "hierarchy"))
    )
    if is_memory_tree_mission:
        sub_missions = [
            # Step 0 — read-only architecture plan (no production code written)
            _make_sub(
                "MemoryTree Step 0: architecture verification",
                (
                    "Read-only architecture pass for Memory Tree hierarchy (issue #536). "
                    "Read igris/core/memory_chunker.py, igris/core/memory_graph.py, "
                    "igris/core/memory_content_store.py (if it exists). "
                    "Identify which of the 4 layers (ContentStore, Scorer, TopicTree, GlobalDigest) "
                    "are missing or stub-only. "
                    "Output a JSON plan to .igris/memory_tree_plan.json listing each layer with: "
                    "layer_name, target_file, status (missing|stub|complete), "
                    "first_function_to_implement. Do not write any production code."
                ),
                explicit_file_scopes=[
                    "igris/core/memory_chunker.py",
                    "igris/core/memory_graph.py",
                    "igris/core/memory_content_store.py",
                    ".igris/memory_tree_plan.json",
                ],
                explicit_acceptance_criteria=[
                    ".igris/memory_tree_plan.json exists and is valid JSON",
                    "Each layer entry has status in {missing, stub, complete}",
                    "No production code written or modified in this step",
                ],
                explicit_tests=[],
            ),
            # Step 1 — MemoryContentStore: raw storage layer
            _make_sub(
                "MemoryTree Step 1: MemoryContentStore",
                (
                    "Implement igris/core/memory_content_store.py for Memory Tree hierarchy (issue #536). "
                    "Create MemoryContentStore class with methods: "
                    "store(chunk_id: str, content: str, metadata: dict) -> None, "
                    "retrieve(chunk_id: str) -> dict, "
                    "list_ids() -> List[str]. "
                    "Use SQLite via the pattern in igris/core/memory_graph.py — no new dependencies. "
                    "Write tests/test_memory_content_store.py with ≥3 unit tests covering "
                    "store, retrieve, list_ids. All tests must pass with: "
                    "pytest tests/test_memory_content_store.py"
                ),
                explicit_file_scopes=[
                    "igris/core/memory_content_store.py",
                    "tests/test_memory_content_store.py",
                ],
                explicit_acceptance_criteria=[
                    "igris/core/memory_content_store.py exists and is not a stub",
                    "MemoryContentStore.store(), .retrieve(), .list_ids() all implemented",
                    "tests/test_memory_content_store.py has ≥3 test functions",
                    "pytest tests/test_memory_content_store.py exits with code 0",
                ],
                explicit_tests=["tests/test_memory_content_store.py"],
            ),
            # Step 2 — MemoryScorer: keyword-based relevance scoring
            _make_sub(
                "MemoryTree Step 2: MemoryScorer",
                (
                    "Implement igris/core/memory_scorer.py for Memory Tree hierarchy (issue #536). "
                    "Create MemoryScorer class with methods: "
                    "score(chunk_id: str, query: str) -> float, "
                    "rank(chunk_ids: List[str], query: str) -> List[Tuple[str, float]] "
                    "(sorted descending by score). "
                    "Use keyword overlap or TF-IDF — no external ML dependencies. "
                    "Write tests/test_memory_scorer.py with ≥3 unit tests verifying "
                    "score range [0,1] and rank ordering. All tests must pass with: "
                    "pytest tests/test_memory_scorer.py"
                ),
                explicit_file_scopes=[
                    "igris/core/memory_scorer.py",
                    "tests/test_memory_scorer.py",
                ],
                explicit_acceptance_criteria=[
                    "igris/core/memory_scorer.py exists and is not a stub",
                    "MemoryScorer.score() returns float in [0.0, 1.0]",
                    "MemoryScorer.rank() returns list sorted by score descending",
                    "tests/test_memory_scorer.py has ≥3 test functions",
                    "pytest tests/test_memory_scorer.py exits with code 0",
                ],
                explicit_tests=["tests/test_memory_scorer.py"],
            ),
            # Step 3 — TopicTree + GlobalDigest: grouping and synthesis
            _make_sub(
                "MemoryTree Step 3: TopicTree and GlobalDigest",
                (
                    "Implement igris/core/memory_topic_tree.py for Memory Tree hierarchy (issue #536). "
                    "Create TopicTree class with: "
                    "add_chunk(chunk_id: str, topic_key: str) -> None, "
                    "get_topic(topic_key: str) -> List[str], "
                    "list_topics() -> List[str]. "
                    "Create GlobalDigest class (same file or igris/core/memory_global_digest.py) with: "
                    "summarize(topic_keys: List[str]) -> str, "
                    "refresh() -> None. "
                    "Write tests/test_memory_topic_tree.py with ≥4 unit tests. "
                    "All tests must pass with: pytest tests/test_memory_topic_tree.py"
                ),
                explicit_file_scopes=[
                    "igris/core/memory_topic_tree.py",
                    "igris/core/memory_global_digest.py",
                    "tests/test_memory_topic_tree.py",
                ],
                explicit_acceptance_criteria=[
                    "TopicTree.add_chunk(), .get_topic(), .list_topics() all implemented",
                    "GlobalDigest.summarize() and .refresh() both implemented",
                    "tests/test_memory_topic_tree.py has ≥4 test functions",
                    "pytest tests/test_memory_topic_tree.py exits with code 0",
                ],
                explicit_tests=["tests/test_memory_topic_tree.py"],
            ),
            # Step 4 — Retrieval integration in memory_graph.py + feature flag
            _make_sub(
                "MemoryTree Step 4: retrieval integration",
                (
                    "Integrate Memory Tree layers into igris/core/memory_graph.py (issue #536). "
                    "Add retrieve_tree(query: str, top_k: int = 5) -> List[dict] method that: "
                    "(1) fetches chunk_ids from MemoryContentStore.list_ids(), "
                    "(2) scores via MemoryScorer.rank(chunk_ids, query), "
                    "(3) groups top results by topic via TopicTree, "
                    "(4) returns top_k results as list of dicts with keys: "
                    "chunk_id, content, score, topic. "
                    "Gate the method behind IGRIS_MEMORY_TREE_ENABLED env var (default '0'): "
                    "when disabled return [] immediately (no exception). "
                    "Write tests/test_memory_tree_integration.py with ≥3 integration tests "
                    "covering: enabled path returns results, disabled path returns [], "
                    "result dicts have required keys. "
                    "All tests must pass with: pytest tests/test_memory_tree_integration.py"
                ),
                explicit_file_scopes=[
                    "igris/core/memory_graph.py",
                    "tests/test_memory_tree_integration.py",
                ],
                explicit_acceptance_criteria=[
                    "memory_graph.py has retrieve_tree() method",
                    "IGRIS_MEMORY_TREE_ENABLED=0 → retrieve_tree() returns []",
                    "IGRIS_MEMORY_TREE_ENABLED=1 → retrieve_tree() returns list of dicts",
                    "Each result dict has keys: chunk_id, content, score, topic",
                    "tests/test_memory_tree_integration.py has ≥3 test functions",
                    "pytest tests/test_memory_tree_integration.py exits with code 0",
                ],
                explicit_tests=["tests/test_memory_tree_integration.py"],
            ),
        ]
        return {
            "why_too_large": _safe_redact(
                f"Memory Tree hierarchy mission requires staged implementation across 5 bounded steps "
                f"(Step 0: read-only architecture plan → Steps 1-4: ContentStore, Scorer, "
                f"TopicTree+GlobalDigest, retrieval integration). Signals: {signals}"
            ),
            "sub_missions": sub_missions,
            "first_sub_mission": sub_missions[0]["title"],
            "human_approval_required": True,
            "generated_by": "deterministic_fallback",
        }

    # --- Strategy 5: single sub-mission (whole goal, scoped) ---
    sub_missions = [_make_sub("Complete mission", safe_goal)]
    return {
        "why_too_large": _safe_redact(
            f"Mission could not be structurally decomposed; presented as single bounded "
            f"sub-mission for focused retry. Signals: {signals}"
        ),
        "sub_missions": sub_missions,
        "first_sub_mission": sub_missions[0]["title"],
        "human_approval_required": True,
        "generated_by": "deterministic_fallback",
    }


# ------------------------------------------------------------------
# Parallel decomposed execution
# ------------------------------------------------------------------

def run_decomposed_parallel(
    supervisor: Any,
    sub_goals: List[str],
    base_max_steps: int = 20,
    preferred_profile: Optional[str] = None,
    depends_on_map: Optional[Dict[str, List[str]]] = None,
) -> List[dict]:
    """Run decomposed sub-goals in parallel, respecting dependency order (Epic #1075).

    Args:
        supervisor: the SelfRepairSupervisor instance (for project_root access)
        sub_goals: list of goal strings
        base_max_steps: max steps per task
        preferred_profile: LLM profile for all tasks
        depends_on_map: optional dict mapping task_id → list[task_id] it depends on.
                        When provided, tasks are executed in topological order (waves).
    """
    from igris.core.parallel_task_runner import (
        ParallelTask, ParallelTaskRunner, build_dependency_order,
        detect_file_conflicts, merge_results,
    )

    tasks = [
        ParallelTask(
            task_id=f"sub_{i}",
            goal=goal,
            max_steps=base_max_steps,
            preferred_profile=preferred_profile,
            depends_on=(depends_on_map or {}).get(f"sub_{i}", []),
        )
        for i, goal in enumerate(sub_goals)
    ]

    # Epic #1075 — pre-run conflict detection
    conflicts = detect_file_conflicts(tasks)
    if conflicts:
        _logger = logging.getLogger("igris.supervisor.parallel")
        _logger.warning(
            "parallel_submissions: file-scope conflicts detected in %d file(s): %s",
            len(conflicts), list(conflicts.keys())[:5],
        )

    runner = ParallelTaskRunner(supervisor.project_root, max_concurrent=3)
    parallel_results = runner.run_sync(tasks)

    return [
        pr.result.to_dict() if pr.result is not None else {"status": "error", "error": pr.error}
        for pr in parallel_results
    ]


# ------------------------------------------------------------------
# Blocked decomposition required
# ------------------------------------------------------------------

def blocked_decomposition_required(
    supervisor: Any,
    run: SupervisorRun,
    triggering_signal: str,
    detail: str,
    decomposition: Dict[str, Any],
    *,
    config: Optional[RankSupervisorConfig] = None,
    mission_plan: Optional[MissionPlan] = None,
    stage_statuses: Optional[Dict[str, Dict[str, Any]]] = None,
    cleanup_workspace: bool = False,
) -> SupervisorRun:
    """Block the run with failure_class='decomposition_required' and attach the
    IGRIS-generated decomposition to the run report and durable storage."""
    run = supervisor._blocked(
        run,
        "decomposition_required",
        detail,
        mission_plan=mission_plan,
        stage_statuses=stage_statuses,
        cleanup_workspace=cleanup_workspace,
    )
    first_sub = _safe_redact(str(decomposition.get("first_sub_mission", "")))

    # Evaluate policy to decide whether to auto-create sub-issues
    # If no config was provided, default to requesting human approval.
    if config is not None:
        policy = supervisor._decomposition_policy(decomposition, config)
    else:
        policy = "request_human_approval"

    run.add(
        "decomposition_policy",
        "evaluated",
        f"Decomposition policy: {policy}",
        policy=policy,
        allow_auto_subissues=config.allow_auto_subissues if config is not None else False,
        allow_github_pr=config.allow_github_pr if config is not None else False,
        dry_run=config.dry_run if config is not None else True,
    )

    created_urls: List[str] = []
    if policy == "auto_create_subissues":
        created_urls = supervisor._auto_create_subissues(run, config, decomposition, triggering_signal)
        if created_urls:
            next_action = f"run:{first_sub}" if first_sub else "queued:first_sub_mission"
        else:
            # All issue creations failed — fall back to manual approval
            next_action = "request_approval:decomposition"
    elif policy == "block_unsafe_decomposition":
        run.add(
            "decomposition_policy",
            "blocked_unsafe",
            "Decomposition contains unsafe content (secret/destructive); human approval required.",
        )
        next_action = "request_approval:decomposition"
    else:  # "request_human_approval"
        next_action = "request_approval:decomposition"

    # Redact any strings inside sub_missions for safety.
    safe_decomposition: Dict[str, Any] = {}
    for k, v in decomposition.items():
        if isinstance(v, str):
            safe_decomposition[k] = _safe_redact(v)
        elif isinstance(v, list) and all(isinstance(i, dict) for i in v):
            safe_decomposition[k] = [
                {ik: _safe_redact(iv) if isinstance(iv, str) else iv
                 for ik, iv in item.items()}
                for item in v
            ]
        else:
            safe_decomposition[k] = v
    safe_decomposition["sub_issue_urls"] = created_urls if policy == "auto_create_subissues" else []
    safe_decomposition["policy"] = policy
    safe_decomposition["allow_auto_subissues"] = (
        config.allow_auto_subissues if config is not None else False
    )
    safe_decomposition["next_action"] = next_action
    # Resolve the approval ambiguity: if the policy already auto-approved the
    # decomposition (sub-issues created autonomously), human review is not needed
    # and the original human_approval_required=True from the LLM response is
    # overridden.  For all other policies human_approval_required keeps its
    # original value so callers can gate correctly.
    if policy == "auto_create_subissues" and created_urls:
        safe_decomposition["human_approval_required"] = False
        safe_decomposition["auto_approved_by_policy"] = True
        safe_decomposition["approval_status"] = "auto_approved_by_policy"
    else:
        safe_decomposition.setdefault("auto_approved_by_policy", False)
        safe_decomposition.setdefault("approval_status", "pending_human_approval")
    run.report.update({
        "decomposition_required": True,
        "capability_limit_signal": triggering_signal,
        "next_action": next_action,
        "decomposition": safe_decomposition,
    })
    run.decomposition = safe_decomposition
    run.touch()

    # Auto-queue child run on first sub-issue if policy approved it
    if policy == "auto_create_subissues" and created_urls and config is not None:
        supervisor._autorun_first_subissue(run, config, safe_decomposition, created_urls, triggering_signal)
        run.touch()

    return run
