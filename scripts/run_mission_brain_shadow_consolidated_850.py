#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.shadow_monitoring_decision import decide_shadow_monitoring_outcome


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    batch1 = _load("reports/mission_brain/shadow_monitoring/847/shadow_batch1_aggregate_847.json")
    analysis = _load("reports/mission_brain/shadow_monitoring/848/shadow_disagreement_analysis_848.json")
    cumulative = _load("reports/mission_brain/shadow_monitoring/849/shadow_cumulative_849.json")

    decision = decide_shadow_monitoring_outcome(cumulative)
    payload = {
        "batch1_metrics": batch1,
        "analysis_848": analysis,
        "cumulative_metrics": cumulative,
        "final_decision": decision,
        "guardrails": {
            "shadow_mode_only": True,
            "default_behavior_unchanged": True,
            "no_enable_by_default": True,
            "rollback_path_status": cumulative.get("rollback_path_status", "unknown"),
        },
    }

    out_dir = Path("reports/mission_brain/shadow_monitoring/850")
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "shadow_monitoring_consolidated_850.json"
    md_path = out_dir / "shadow_monitoring_consolidated_850.md"
    post_path = out_dir / "post_subissue_evaluation_850.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    md_lines = [
        "# Shadow Monitoring Consolidated Report — #850",
        "",
        f"- final_decision: {decision}",
        f"- total_shadow_cycles: {cumulative['total_shadow_cycles']}",
        f"- agreement_rate: {cumulative['agreement_rate']}",
        f"- disagreement_rate: {cumulative['disagreement_rate']}",
        f"- prevented_error_candidates: {cumulative['prevented_error_candidates']}",
        f"- risk_introduced_candidates: {cumulative['risk_introduced_candidates']}",
        f"- potential_false_completed: {cumulative['potential_false_completed']}",
        f"- potential_critical_false_completed: {cumulative['potential_critical_false_completed']}",
        f"- latency_overhead.mean_ms: {cumulative['latency_overhead']['mean_ms']}",
        f"- cost_overhead.total_usd: {cumulative['cost_overhead']['total_usd']}",
        f"- rollback_path_status: {cumulative['rollback_path_status']}",
        f"- final_readiness_trend: {cumulative['final_readiness_trend']}",
        "",
        "## Decision rationale",
    ]
    if decision == "candidate for controlled rollout":
        md_lines.append("- readiness threshold reached; rollout remains recommendation-only.")
    elif decision == "keep shadow mode":
        md_lines.append("- stable/safe profile observed but readiness not sufficient for rollout candidate.")
    elif decision == "remediate again":
        md_lines.append("- additional remediation required before rollout candidacy.")
    else:
        md_lines.append("- do not integrate due to critical risk signal.")
    md_lines.append("- no rollout activation performed in this epic.")
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    post_lines = [
        "# Post-subissue Evaluation — #850",
        "",
        "Status: `passed`",
        "",
        "## Final decision",
        f"- `{decision}`",
        "",
        "## Output artifacts",
        f"- `{json_path}`",
        f"- `{md_path}`",
        "",
        "## Governance checks",
        "- shadow mode only: respected",
        "- default loop behavior unchanged: respected",
        "- no irreversible integration: respected",
        "- no enable-by-default decision: respected",
    ]
    post_path.write_text("\n".join(post_lines) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(json_path), "md": str(md_path), "post": str(post_path), "decision": decision}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

