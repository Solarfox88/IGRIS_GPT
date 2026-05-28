from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

from igris.agent.mission.mission_orchestrator import run_mission_pipeline


def _loop_status_to_decision(loop_status: str, stop_reason: str) -> str:
    status = (loop_status or "").strip().lower()
    stop = (stop_reason or "").strip().lower()
    if status == "finished" or stop == "finish":
        return "completed"
    if status in {"blocked", "failed"} or stop in {"blocked", "ask_user"}:
        return "failed"
    return "partial"


def _shadow_reports_dir(project_root: str) -> Path:
    path = Path(project_root) / ".igris" / "mission_brain" / "shadow"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _build_evidence_depth_summary(mission_data: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in mission_data.get("execution_results") or []:
        depth = str(item.get("evidence_depth") or "missing_evidence")
        counts[depth] = counts.get(depth, 0) + 1
    return counts


def run_shadow_comparison(
    *,
    user_input: str,
    loop_result: Any,
    project_root: str,
    compare_with_current_loop: bool,
    telemetry_enabled: bool,
) -> Dict[str, Any]:
    """Run Mission Brain in shadow mode and emit side-by-side telemetry."""
    mission = run_mission_pipeline(
        user_input=user_input,
        project="igrisgpt",
        repo_view=None,
        command_map=None,
        dry_run=True,
        project_root=project_root,
    )
    mission_data = mission.to_dict()
    loop_decision = _loop_status_to_decision(
        getattr(loop_result, "status", ""),
        getattr(loop_result, "stop_reason", ""),
    )
    mission_brain_decision = str(mission_data.get("status") or "partial")
    divergence = (
        bool(compare_with_current_loop)
        and loop_decision != mission_brain_decision
    )
    record: Dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "loop_id": getattr(loop_result, "loop_id", ""),
        "mission_id": mission_data.get("id", ""),
        "goal": user_input,
        "loop_decision": loop_decision,
        "mission_brain_decision": mission_brain_decision,
        "decision_divergence": divergence,
        "quality_gate_passed": bool(mission_data.get("quality_gate_passed", False)),
        "satisfaction_gate_passed": bool(mission_data.get("satisfaction_gate_passed", False)),
        "evidence_depth_summary": _build_evidence_depth_summary(mission_data),
        "mission_report_path": str(
            Path(project_root) / ".igris" / "mission_brain" / "reports" / f"{mission.id}.json"
        ),
    }

    if telemetry_enabled:
        out = _shadow_reports_dir(project_root) / f"{record['loop_id'] or mission.id}.json"
        out.write_text(json.dumps(record, indent=2), encoding="utf-8")
        record["shadow_record_path"] = str(out)

    return record

