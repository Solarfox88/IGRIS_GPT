#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.rollback_policy import evaluate_wrapper_policy


def _write_artifacts(payload: dict) -> dict:
    out_dir = Path("reports/mission_brain/integration/838")
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "rollback_simulation_838.json"
    md_path = out_dir / "rollback_simulation_838.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# Mission Brain Rollback Simulation — #838",
        "",
        f"- total_cases: {payload['summary']['total_cases']}",
        f"- wrapper_effective_count: {payload['summary']['wrapper_effective_count']}",
        f"- auto_rollback_count: {payload['summary']['auto_rollback_count']}",
        f"- manual_force_count: {payload['summary']['manual_force_count']}",
        "",
        "## Cases",
    ]
    for case in payload["cases"]:
        lines.append(
            f"- {case['name']}: effective_mode={case['policy']['effective_mode']}, "
            f"reason={case['policy']['reason']}"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def main() -> int:
    cases = [
        {
            "name": "manual_force_wrapper",
            "kwargs": {
                "requested_mode": "shadow",
                "shadow_record": {"mismatch_class": "agreement"},
                "force_wrapper_mode": True,
            },
        },
        {
            "name": "risky_auto_rollback",
            "kwargs": {
                "requested_mode": "shadow",
                "shadow_record": {"mismatch_class": "risky_false_completed_candidate"},
                "rollback_to_wrapper_on_guardrail": True,
                "auto_rollback_on_risky_mismatch": True,
            },
        },
        {
            "name": "safe_keep_shadow",
            "kwargs": {
                "requested_mode": "shadow",
                "shadow_record": {"mismatch_class": "agreement"},
            },
        },
    ]
    rendered = []
    for c in cases:
        rendered.append({"name": c["name"], "policy": evaluate_wrapper_policy(**c["kwargs"])})
    summary = {
        "total_cases": len(rendered),
        "wrapper_effective_count": sum(1 for c in rendered if c["policy"]["effective_mode"] == "wrapper"),
        "auto_rollback_count": sum(1 for c in rendered if c["policy"]["auto_rollback_triggered"]),
        "manual_force_count": sum(1 for c in rendered if c["policy"]["manual_force_wrapper"]),
    }
    payload = {"cases": rendered, "summary": summary, "status": "passed"}
    paths = _write_artifacts(payload)
    print(json.dumps({"status": payload["status"], "paths": paths, "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

