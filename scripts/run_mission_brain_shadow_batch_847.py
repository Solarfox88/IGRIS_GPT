#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List

from igris.agent.mission.shadow_monitoring import aggregate_shadow_cycles
from igris.core.agent_reasoning_loop import AgentReasoningLoop
from igris.models.config import CONFIG


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
    return {
        "result": result,
        "elapsed_ms": elapsed_ms,
    }


def _build_cycle_report(cycle_id: str, goal: str, baseline: Dict, shadow: Dict) -> Dict:
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
    cost_overhead_usd = 0.0  # local shadow mission pipeline in this batch

    rollback_status = "ok"
    if sh_res.mission_brain_shadow_error:
        rollback_status = "degraded"
    if potential_critical_false_completed:
        rollback_status = "failed"

    report_usefulness_score = 0.8 if mismatch_class != "agreement" else 0.7

    return {
        "cycle_id": cycle_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "goal": goal,
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


def main() -> int:
    goals: List[str] = [
        "Valuta coerenza policy di merge e sicurezza branch",
        "Controlla che i test critici siano inclusi nel piano",
        "Verifica rischio regressione in modifiche multi-file",
        "Classifica severita di un errore ripetuto nel loop",
        "Conferma che rollback wrapper resti disponibile",
    ]
    cycle_reports: List[Dict] = []
    for i, goal in enumerate(goals, start=1):
        baseline = _run_once(goal, shadow_enabled=False)
        shadow = _run_once(goal, shadow_enabled=True)
        cycle_reports.append(_build_cycle_report(f"batch1-c{i}", goal, baseline, shadow))

    metrics = aggregate_shadow_cycles(cycle_reports)
    out_dir = Path("reports/mission_brain/shadow_monitoring/847")
    out_dir.mkdir(parents=True, exist_ok=True)
    cycles_path = out_dir / "shadow_batch1_cycles_847.json"
    agg_path = out_dir / "shadow_batch1_aggregate_847.json"
    md_path = out_dir / "shadow_batch1_aggregate_847.md"
    cycles_path.write_text(json.dumps(cycle_reports, indent=2), encoding="utf-8")
    agg_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    md_lines = [
        "# Shadow Monitoring Batch-1 — #847",
        "",
        f"- total_shadow_cycles: {metrics['total_shadow_cycles']}",
        f"- agreement_rate: {metrics['agreement_rate']}",
        f"- disagreement_rate: {metrics['disagreement_rate']}",
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
    ]
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(json.dumps({"cycles": str(cycles_path), "aggregate": str(agg_path), "md": str(md_path), "metrics": metrics}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

