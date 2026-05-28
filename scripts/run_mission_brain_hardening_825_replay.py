from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from igris.agent.mission.mission_orchestrator import run_mission_pipeline
from igris.agent.mission.quality_gate import evaluate_quality_gate
from igris.agent.mission.satisfaction_gate import evaluate_satisfaction_gate


def _cases() -> List[Dict[str, object]]:
    return [
        {
            "case_id": "fc_case_791_m2",
            "source_report": "reports/mission_brain/adoption/791/m2_report.json",
            "user_input": (
                "Pianifica e verifica i 3 blocchi: step outcome logger, correlazione sezioni-outcome, "
                "weight updater ogni 50 run per issue #777."
            ),
            "repo_view": {
                "issue_url": "https://github.com/Solarfox88/IGRIS_GPT/issues/777",
                "paths": ["igris/core/context_manager.py", ".igris/context_weights.json", "igris/web/server.py"],
                "category": "multi_step",
            },
        },
        {
            "case_id": "fc_case_792_m4",
            "source_report": "reports/mission_brain/adoption/792/m4_report.json",
            "user_input": (
                "Verifica in sequenza su issue #776: presenza step outcome logger, tracciamento outcome, "
                "e disponibilita evidenze per report operativo."
            ),
            "repo_view": {
                "issue_url": "https://github.com/Solarfox88/IGRIS_GPT/issues/776",
                "paths": ["igris/core/integration_layer.py", "igris/core/context_manager.py"],
                "category": "multi_step",
            },
        },
    ]


def run_replay(project_root: str = ".") -> Dict[str, object]:
    out_dir = Path(project_root) / "reports" / "mission_brain" / "hardening" / "825"
    out_dir.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, object]] = []
    for case in _cases():
        mission = run_mission_pipeline(
            user_input=str(case["user_input"]),
            project="igrisgpt",
            repo_view=dict(case["repo_view"]),
            command_map={f"ACT-{i:03d}": f"echo shallow-{i}" for i in range(1, 6)},
            dry_run=True,
            project_root=project_root,
        )
        quality = evaluate_quality_gate(mission)
        satisfaction = evaluate_satisfaction_gate(mission)
        results.append(
            {
                "case_id": case["case_id"],
                "source_report": case["source_report"],
                "declared_status_after_825": mission.status,
                "quality_passed": quality["passed"],
                "satisfaction_passed": satisfaction["passed"],
                "quality_reasons": quality.get("reasons", []),
                "insufficient_multistep_evidence_detected": "insufficient_multistep_evidence" in quality.get("reasons", []),
                "incomplete_checklist_evidence_detected": "incomplete_checklist_evidence" in quality.get("reasons", []),
                "evidence_depths": [r.evidence_depth for r in mission.execution_results],
            }
        )

    false_completed_count = sum(1 for item in results if item["declared_status_after_825"] == "completed")
    summary = {
        "suite": "mission_brain_hardening_825_replay",
        "cases": results,
        "false_completed_count": false_completed_count,
        "critical_false_completed_count": 0,
        "all_cases_non_completed": false_completed_count == 0,
    }
    (out_dir / "hardening_825_replay.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run_replay(project_root="."), indent=2))
