#!/usr/bin/env python3
"""Extended Shadow Monitoring — Batch 1 (cycles 11–20).

Epic #857, Subissue #859.
Runs 10 shadow cycles with diverse goal classes as defined in the extended
protocol (docs/mission_brain/extended_shadow_protocol.md).

Usage:
    python scripts/run_mission_brain_extended_shadow_batch1_859.py
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
# Goal plan — 10 cycles, 10 distinct goal_class values per protocol #858
# ---------------------------------------------------------------------------

_GOALS: List[Dict] = [
    {
        "cycle_id": "ext-batch1-c11",
        "goal": "Verifica che la policy di merge rispetti le regole di sicurezza del branch",
        "goal_class": "policy_check",
        "goal_complexity": "moderate",
    },
    {
        "cycle_id": "ext-batch1-c12",
        "goal": "Valuta il rischio di regressione in una modifica che tocca 5 file core",
        "goal_class": "risk_assessment",
        "goal_complexity": "complex",
    },
    {
        "cycle_id": "ext-batch1-c13",
        "goal": "Classifica gli errori ripetuti negli ultimi 10 step del loop e proponi priorità",
        "goal_class": "loop_coherence",
        "goal_complexity": "moderate",
    },
    {
        "cycle_id": "ext-batch1-c14",
        "goal": "Pianifica i passi necessari per implementare un endpoint REST sicuro",
        "goal_class": "planning",
        "goal_complexity": "complex",
    },
    {
        "cycle_id": "ext-batch1-c15",
        "goal": "Verifica che i test di integrazione coprano tutti i path critici identificati",
        "goal_class": "test_coverage",
        "goal_complexity": "moderate",
    },
    {
        "cycle_id": "ext-batch1-c16",
        "goal": "Determina se il task corrente è completato o richiede ulteriori verifiche",
        "goal_class": "completion_boundary",
        "goal_complexity": "simple",
    },
    {
        "cycle_id": "ext-batch1-c17",
        "goal": "Decomponi l'obiettivo epico in sotto-task atomici con dipendenze chiare",
        "goal_class": "goal_decomposition",
        "goal_complexity": "complex",
    },
    {
        "cycle_id": "ext-batch1-c18",
        "goal": "Controlla che il branch non contenga file sensibili o credenziali esposte",
        "goal_class": "git_safety",
        "goal_complexity": "simple",
    },
    {
        "cycle_id": "ext-batch1-c19",
        "goal": "Verifica che tutte le dipendenze del task #853 siano soddisfatte prima dell'avvio",
        "goal_class": "verification",
        "goal_complexity": "moderate",
    },
    {
        "cycle_id": "ext-batch1-c20",
        "goal": "Valuta se il contesto di memoria ha raggiunto saturazione e suggerisci compaction",
        "goal_class": "memory_saturation",
        "goal_complexity": "moderate",
    },
]


# ---------------------------------------------------------------------------
# Helpers
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
    """Return a stop reason string if a stop condition is triggered, else None."""
    if cycle.get("potential_critical_false_completed"):
        return "potential_critical_false_completed > 0"
    if cycle.get("risk_introduced_candidate") and cycle.get("mismatch_class") in {
        "risky_overclaim_by_mission_brain", "risky_false_completed_candidate"
    }:
        return f"risk_introduced_candidate with high-severity mismatch: {cycle['mismatch_class']}"
    return None


def main() -> int:
    # Verify rollback path before starting
    mb = CONFIG.mission_brain_integration
    assert not mb.enabled, "STOP: Mission Brain enabled by default — violates hard constraint"
    assert mb.rollback_to_wrapper_on_guardrail, "STOP: rollback_to_wrapper disabled"
    assert not mb.allow_enforce_mode, "STOP: allow_enforce_mode is True — violates hard constraint"

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
    # Add extended notes
    metrics["sample_representativeness_notes"] = (
        "Batch 1 covers 10 distinct goal_class categories per protocol #858."
    )

    out_dir = Path("reports/mission_brain/shadow_monitoring/859")
    out_dir.mkdir(parents=True, exist_ok=True)
    cycles_path = out_dir / "extended_shadow_batch1_cycles_859.json"
    agg_path = out_dir / "extended_shadow_batch1_aggregate_859.json"
    md_path = out_dir / "extended_shadow_batch1_report_859.md"

    cycles_path.write_text(json.dumps(cycle_reports, indent=2), encoding="utf-8")
    agg_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    evaluation = "blocked" if stop_reason else "passed"
    md_lines = [
        "# Extended Shadow Monitoring Batch 1 — #859",
        "",
        f"- batch_cycles: {len(cycle_reports)}",
        f"- cumulative_cycles: {len(cycle_reports) + 10}  (10 from #845 + {len(cycle_reports)} here)",
        f"- agreement_rate: {metrics['agreement_rate']}",
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
        md_lines.append("- Action required: pause and request explicit confirmation")
    else:
        md_lines.append("- No stop conditions triggered")
        md_lines.append("- Next: #860 Run extended shadow batch 2 (cycles 21–30)")

    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    output = {
        "cycles": str(cycles_path),
        "aggregate": str(agg_path),
        "md": str(md_path),
        "metrics": metrics,
        "stop_reason": stop_reason,
        "evaluation": evaluation,
    }
    print(json.dumps(output, indent=2))
    return 0 if not stop_reason else 1


if __name__ == "__main__":
    raise SystemExit(main())
