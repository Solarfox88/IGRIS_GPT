#!/usr/bin/env python3
"""Extended Shadow Monitoring — Batch 2 (cycles 21–30).

Epic #857, Subissue #860.
Complementary goals: different complexity levels, edge cases, and
3 goal types that triggered disagreement in #845 (policy_check,
risk_assessment, verification).

Usage:
    python scripts/run_mission_brain_extended_shadow_batch2_860.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List

from igris.agent.mission.shadow_monitoring import aggregate_shadow_cycles
from igris.core.agent_reasoning_loop import AgentReasoningLoop
from igris.models.config import CONFIG


# ---------------------------------------------------------------------------
# Goal plan — 10 cycles, complementary to Batch 1 per protocol #858
# Batch 2: mix of complexities, edge cases, goals that triggered disagreement
# ---------------------------------------------------------------------------

_GOALS: List[Dict] = [
    # 3 goals that previously triggered disagreement in #845 / Batch 1
    {
        "cycle_id": "ext-batch2-c21",
        "goal": "Verifica la policy di sicurezza per push su main branch protetto",
        "goal_class": "policy_check",
        "goal_complexity": "simple",
    },
    {
        "cycle_id": "ext-batch2-c22",
        "goal": "Valuta rischio di un hotfix che bypassa la CI pipeline",
        "goal_class": "risk_assessment",
        "goal_complexity": "complex",
    },
    {
        "cycle_id": "ext-batch2-c23",
        "goal": "Verifica che l'esecuzione del task #819 soddisfi tutti i criteri di accettazione",
        "goal_class": "verification",
        "goal_complexity": "moderate",
    },
    # Edge cases: ambiguous goal, empty context, conflicting signals
    {
        "cycle_id": "ext-batch2-c24",
        "goal": "Migliora il sistema",
        "goal_class": "ambiguous_goal",
        "goal_complexity": "simple",
    },
    {
        "cycle_id": "ext-batch2-c25",
        "goal": "Procedi con il prossimo step",
        "goal_class": "empty_context",
        "goal_complexity": "simple",
    },
    {
        "cycle_id": "ext-batch2-c26",
        "goal": "Il task sembra completato ma i test falliscono ancora — decidi se chiudere o continuare",
        "goal_class": "conflicting_signals",
        "goal_complexity": "complex",
    },
    # Multi-step complex vs simple verification
    {
        "cycle_id": "ext-batch2-c27",
        "goal": "Pianifica la migrazione del database includendo rollback, test di carico e monitoring post-deploy",
        "goal_class": "multi_step_complex",
        "goal_complexity": "complex",
    },
    {
        "cycle_id": "ext-batch2-c28",
        "goal": "Controlla che il file .env non sia tracciato nel repository",
        "goal_class": "simple_verification",
        "goal_complexity": "simple",
    },
    # Regression detection and dependency check
    {
        "cycle_id": "ext-batch2-c29",
        "goal": "Rileva regressioni nei test di performance dopo l'ultima modifica al core",
        "goal_class": "regression_detection",
        "goal_complexity": "moderate",
    },
    {
        "cycle_id": "ext-batch2-c30",
        "goal": "Verifica le dipendenze circolari tra i moduli prima del merge finale",
        "goal_class": "dependency_check",
        "goal_complexity": "moderate",
    },
]


# ---------------------------------------------------------------------------
# Helpers (shared pattern with Batch 1)
# ---------------------------------------------------------------------------

def _loop_decision(status: str, stop_reason: str) -> str:
    s = (status or "").lower()
    r = (stop_reason or "").lower()
    if s == "finished" or r == "finish":
        return "completed"
    if s in {"blocked", "failed"} or r in {"blocked", "ask_user"}:
        return "failed"
    return "partial"


def _run_once(goal: str, shadow_enabled: bool) -> Dict:
    mb = CONFIG.mission_brain_integration
    mb.enabled = shadow_enabled
    mb.mode = "shadow"
    mb.compare_with_current_loop = True
    mb.telemetry_enabled = True
    mb.rollback_to_wrapper_on_guardrail = True

    t0 = time.monotonic()
    loop = AgentReasoningLoop(
        project_root=".",
        max_steps=3,
        max_consecutive_errors=2,
        task_type="policy_check",
        role="reviewer",
    )
    result = loop.run(goal=goal, mission_id="")
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return {"result": result, "elapsed_ms": elapsed_ms}


def _build_cycle_report(plan: Dict, baseline: Dict, shadow: Dict) -> Dict:
    base_res = baseline["result"]
    sh_res = shadow["result"]
    shadow_record = sh_res.mission_brain_shadow_record or {}
    wrapper_policy = sh_res.mission_brain_wrapper_policy or {}

    current_decision = _loop_decision(sh_res.status, sh_res.stop_reason)
    mb_decision = str(shadow_record.get("mission_brain_decision") or "partial")
    mismatch_class = str(shadow_record.get("mismatch_class") or "other_mismatch")
    agreement = bool(shadow_record.get("loop_decision") == mb_decision)

    risk_intro = mismatch_class == "risky_overclaim_by_mission_brain"
    prevented = mismatch_class == "safe_more_optimistic_mission_brain"
    potential_false_completed = risk_intro
    potential_critical_false_completed = risk_intro and str(
        wrapper_policy.get("effective_mode", "shadow")
    ) != "wrapper"
    potential_false_partial = mismatch_class == "safe_more_conservative_mission_brain"
    potential_false_failed = mismatch_class == "risky_false_completed_candidate"

    latency_overhead_ms = max(0.0, float(shadow["elapsed_ms"] - baseline["elapsed_ms"]))
    cost_overhead_usd = 0.0

    rollback_status = "ok"
    if sh_res.mission_brain_shadow_error:
        rollback_status = "degraded"
    if potential_critical_false_completed:
        rollback_status = "failed"

    report_usefulness_score = 0.8 if mismatch_class != "agreement" else 0.7

    return {
        "cycle_id": plan["cycle_id"],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "goal": plan["goal"],
        "goal_class": plan["goal_class"],
        "goal_complexity": plan["goal_complexity"],
        "mission_brain_decision": mb_decision,
        "current_loop_decision": current_decision,
        "agreement": agreement,
        "mismatch_class": mismatch_class,
        "prevented_error_candidate": prevented,
        "risk_introduced_candidate": risk_intro,
        "potential_false_completed": potential_false_completed,
        "potential_critical_false_completed": potential_critical_false_completed,
        "potential_false_partial": potential_false_partial,
        "potential_false_failed": potential_false_failed,
        "latency_overhead_ms": round(latency_overhead_ms, 3),
        "cost_overhead_usd": cost_overhead_usd,
        "rollback_path_status": rollback_status,
        "report_usefulness_score": report_usefulness_score,
        "baseline_loop_status": base_res.status,
        "shadow_loop_status": sh_res.status,
        "notes": "",
    }


def _check_stop_condition(cycle: Dict) -> str | None:
    if cycle.get("potential_critical_false_completed"):
        return "potential_critical_false_completed > 0"
    if cycle.get("risk_introduced_candidate") and cycle.get("mismatch_class") in {
        "risky_overclaim_by_mission_brain", "risky_false_completed_candidate"
    }:
        return f"risk_introduced_candidate with high-severity mismatch: {cycle['mismatch_class']}"
    return None


def _load_batch1_metrics() -> Dict:
    path = Path("reports/mission_brain/shadow_monitoring/859/extended_shadow_batch1_aggregate_859.json")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    mb = CONFIG.mission_brain_integration
    assert not mb.enabled, "STOP: Mission Brain enabled by default — violates hard constraint"
    assert mb.rollback_to_wrapper_on_guardrail, "STOP: rollback_to_wrapper disabled"
    assert not mb.allow_enforce_mode, "STOP: allow_enforce_mode is True — violates hard constraint"

    batch1_metrics = _load_batch1_metrics()
    prev_agreement_rate = float(batch1_metrics.get("agreement_rate", 0.0))

    cycle_reports: List[Dict] = []
    stop_reason: str | None = None

    for plan in _GOALS:
        baseline = _run_once(plan["goal"], shadow_enabled=False)
        shadow_run = _run_once(plan["goal"], shadow_enabled=True)
        cycle = _build_cycle_report(plan, baseline, shadow_run)
        cycle_reports.append(cycle)

        stop_reason = _check_stop_condition(cycle)
        if stop_reason:
            print(f"STOP CONDITION TRIGGERED after {cycle['cycle_id']}: {stop_reason}")
            break

    metrics = aggregate_shadow_cycles(cycle_reports)
    metrics["sample_representativeness_notes"] = (
        "Batch 2 covers 10 complementary goal classes including edge cases "
        "(ambiguous_goal, empty_context, conflicting_signals) and 3 reprise "
        "classes from #845 (policy_check, risk_assessment, verification)."
    )

    # Trend detection vs Batch 1
    current_agreement = float(metrics.get("agreement_rate", 0.0))
    if current_agreement > prev_agreement_rate:
        trend_direction = "improving"
    elif current_agreement < prev_agreement_rate:
        trend_direction = "worsening"
    else:
        trend_direction = "stable"
    metrics["trend_direction_vs_batch1"] = trend_direction
    metrics["batch1_agreement_rate"] = prev_agreement_rate

    out_dir = Path("reports/mission_brain/shadow_monitoring/860")
    out_dir.mkdir(parents=True, exist_ok=True)
    cycles_path = out_dir / "extended_shadow_batch2_cycles_860.json"
    agg_path = out_dir / "extended_shadow_batch2_aggregate_860.json"
    md_path = out_dir / "extended_shadow_batch2_report_860.md"

    cycles_path.write_text(json.dumps(cycle_reports, indent=2), encoding="utf-8")
    agg_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    evaluation = "blocked" if stop_reason else "passed"
    md_lines = [
        "# Extended Shadow Monitoring Batch 2 — #860",
        "",
        f"- batch_cycles: {len(cycle_reports)}",
        f"- cumulative_cycles: {len(cycle_reports) + 20}  (10 from #845 + 10 from #859 + {len(cycle_reports)} here)",
        f"- agreement_rate (batch 2): {metrics['agreement_rate']}",
        f"- agreement_rate (batch 1): {prev_agreement_rate}",
        f"- trend_direction_vs_batch1: {trend_direction}",
        f"- disagreement_rate: {metrics['disagreement_rate']}",
        f"- disagreement_by_class: {metrics.get('disagreement_by_class', {})}",
        f"- dominant_mismatch_classes: {metrics.get('dominant_mismatch_classes', [])}",
        f"- prevented_error_candidates: {metrics['prevented_error_candidates']}",
        f"- risk_introduced_candidates: {metrics['risk_introduced_candidates']}",
        f"- potential_false_completed: {metrics['potential_false_completed']}",
        f"- potential_critical_false_completed: {metrics['potential_critical_false_completed']}",
        f"- potential_false_partial: {metrics['potential_false_partial']}",
        f"- potential_false_failed: {metrics['potential_false_failed']}",
        f"- report_usefulness_score: {metrics['report_usefulness_score']}",
        f"- latency_overhead.mean_ms: {metrics['latency_overhead']['mean_ms']}",
        f"- latency_overhead.p95_ms: {metrics['latency_overhead']['p95_ms']}",
        f"- cost_overhead.total_usd: {metrics['cost_overhead']['total_usd']}",
        f"- rollback_path_status: {metrics['rollback_path_status']}",
        f"- final_readiness_trend: {metrics['final_readiness_trend']}",
        f"- sample_representativeness_score: {metrics.get('sample_representativeness_score', 0.0)}",
        f"- sample_representativeness_notes: {metrics.get('sample_representativeness_notes', '')}",
        f"- decision_distribution_mission_brain: {metrics.get('decision_distribution_mission_brain', {})}",
        f"- decision_distribution_current_loop: {metrics.get('decision_distribution_current_loop', {})}",
        "",
        f"## Evaluation: {evaluation}",
    ]
    if stop_reason:
        md_lines.append(f"- STOP CONDITION: {stop_reason}")
    else:
        md_lines.append("- No stop conditions triggered")
        md_lines.append("- Next: #861 Analyze agreement/disagreement stability (30-cycle view)")

    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    output = {
        "cycles": str(cycles_path),
        "aggregate": str(agg_path),
        "md": str(md_path),
        "metrics": metrics,
        "trend_direction_vs_batch1": trend_direction,
        "stop_reason": stop_reason,
        "evaluation": evaluation,
    }
    print(json.dumps(output, indent=2))
    return 0 if not stop_reason else 1


if __name__ == "__main__":
    raise SystemExit(main())
