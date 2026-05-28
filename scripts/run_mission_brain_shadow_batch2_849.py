#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Tuple

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


def _run_once(goal: str, shadow_enabled: bool, max_steps: int, max_errors: int) -> Dict:
    mb = CONFIG.mission_brain_integration
    mb.enabled = shadow_enabled
    mb.mode = "shadow"
    mb.compare_with_current_loop = True
    mb.telemetry_enabled = True
    mb.rollback_to_wrapper_on_guardrail = True

    t0 = time.monotonic()
    loop = AgentReasoningLoop(
        project_root=".",
        max_steps=max_steps,
        max_consecutive_errors=max_errors,
        task_type="policy_check",
        role="reviewer",
    )
    result = loop.run(goal=goal, mission_id="")
    return {"result": result, "elapsed_ms": int((time.monotonic() - t0) * 1000)}


def _build_cycle_report(cycle_id: str, goal: str, baseline: Dict, shadow: Dict) -> Dict:
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

    rollback_status = "ok"
    if sh_res.mission_brain_shadow_error:
        rollback_status = "degraded"
    if potential_critical_false_completed:
        rollback_status = "failed"

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
        "latency_overhead_ms": round(max(0.0, float(shadow["elapsed_ms"] - baseline["elapsed_ms"])), 3),
        "cost_overhead_usd": 0.0,
        "rollback_path_status": rollback_status,
        "report_usefulness_score": 0.8 if not agreement else 0.7,
        "notes": "edge-case batch2",
    }


def _load_batch1_cycles() -> List[Dict]:
    path = Path("reports/mission_brain/shadow_monitoring/847/shadow_batch1_cycles_847.json")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    scenarios: List[Tuple[str, int, int]] = [
        ("Edge case: ambiguous stop reason with strict max steps", 2, 1),
        ("Edge case: repeated policy failure classification", 3, 1),
        ("Edge case: rollback wrapper continuity under disagreement", 3, 2),
        ("Edge case: low-step monitoring consistency", 1, 1),
        ("Edge case: disagreement taxonomy stability check", 4, 2),
    ]
    batch2_reports: List[Dict] = []
    for i, (goal, max_steps, max_errors) in enumerate(scenarios, start=1):
        baseline = _run_once(goal, shadow_enabled=False, max_steps=max_steps, max_errors=max_errors)
        shadow = _run_once(goal, shadow_enabled=True, max_steps=max_steps, max_errors=max_errors)
        batch2_reports.append(_build_cycle_report(f"batch2-c{i}", goal, baseline, shadow))

    batch2_metrics = aggregate_shadow_cycles(batch2_reports)
    all_cycles = _load_batch1_cycles() + batch2_reports
    cumulative_metrics = aggregate_shadow_cycles(all_cycles)

    out_dir = Path("reports/mission_brain/shadow_monitoring/849")
    out_dir.mkdir(parents=True, exist_ok=True)
    b2_cycles = out_dir / "shadow_batch2_cycles_849.json"
    b2_agg = out_dir / "shadow_batch2_aggregate_849.json"
    cum_agg = out_dir / "shadow_cumulative_849.json"
    md_path = out_dir / "shadow_batch2_summary_849.md"

    b2_cycles.write_text(json.dumps(batch2_reports, indent=2), encoding="utf-8")
    b2_agg.write_text(json.dumps(batch2_metrics, indent=2), encoding="utf-8")
    cum_agg.write_text(json.dumps(cumulative_metrics, indent=2), encoding="utf-8")

    md_lines = [
        "# Shadow Monitoring Batch-2 — #849",
        "",
        "## Batch-2 metrics",
        f"- total_shadow_cycles: {batch2_metrics['total_shadow_cycles']}",
        f"- agreement_rate: {batch2_metrics['agreement_rate']}",
        f"- disagreement_rate: {batch2_metrics['disagreement_rate']}",
        f"- potential_critical_false_completed: {batch2_metrics['potential_critical_false_completed']}",
        f"- rollback_path_status: {batch2_metrics['rollback_path_status']}",
        "",
        "## Cumulative metrics (batch1 + batch2)",
        f"- total_shadow_cycles: {cumulative_metrics['total_shadow_cycles']}",
        f"- agreement_rate: {cumulative_metrics['agreement_rate']}",
        f"- disagreement_rate: {cumulative_metrics['disagreement_rate']}",
        f"- risk_introduced_candidates: {cumulative_metrics['risk_introduced_candidates']}",
        f"- potential_false_completed: {cumulative_metrics['potential_false_completed']}",
        f"- potential_critical_false_completed: {cumulative_metrics['potential_critical_false_completed']}",
        f"- latency_overhead.mean_ms: {cumulative_metrics['latency_overhead']['mean_ms']}",
        f"- final_readiness_trend: {cumulative_metrics['final_readiness_trend']}",
    ]
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(json.dumps({
        "batch2_cycles": str(b2_cycles),
        "batch2_aggregate": str(b2_agg),
        "cumulative_aggregate": str(cum_agg),
        "summary_md": str(md_path),
        "batch2_metrics": batch2_metrics,
        "cumulative_metrics": cumulative_metrics,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

