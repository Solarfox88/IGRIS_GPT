#!/usr/bin/env python3
"""EPIC #886 — #887: Define recovery recommendation taxonomy.

Usage:
    python scripts/run_recovery_taxonomy_887.py
"""
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.recovery_taxonomy import (
    RECOVERY_ACTIONS,
    RECOVERY_TEMPLATES,
    _validate_taxonomy,
    list_statuses_with_templates,
)


def main() -> int:
    _validate_taxonomy()

    # All templates have auto_executable=False
    violations = [s for s, t in RECOVERY_TEMPLATES.items() if t["auto_executable"] is not False]
    if violations:
        print(json.dumps({"STOP": f"auto_executable violations: {violations}"}, indent=2))
        return 1

    statuses = list_statuses_with_templates()

    result = {
        "epic": 886, "subissue": 887,
        "title": "Recovery Recommendation Taxonomy",
        "recovery_actions": sorted(RECOVERY_ACTIONS),
        "templates_count": len(RECOVERY_TEMPLATES),
        "covered_combined_statuses": statuses,
        "auto_executable_violations": 0,
        "all_advisory_only": True,
        "taxonomy_summary": [
            {
                "combined_status": s,
                "action": RECOVERY_TEMPLATES[s]["action"],
                "confidence": RECOVERY_TEMPLATES[s]["confidence"],
                "auto_executable": RECOVERY_TEMPLATES[s]["auto_executable"],
            }
            for s in statuses
        ],
        "invariants": [
            "auto_executable is ALWAYS False",
            "advisory_only is ALWAYS True",
            "safe_next_action is non-empty for all templates",
        ],
        "guardrails": {"advisory_only": True, "no_auto_execution": True, "default_off": True},
        "evaluation": "passed", "stop_reason": None, "next_subissue": 888,
    }

    out_dir = Path("reports/mission_brain/recovery/887")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "recovery_taxonomy_887.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    md = [
        "# Recovery Recommendation Taxonomy — #887",
        "## EPIC #886",
        "",
        "| combined_status | action | confidence | auto_executable |",
        "|-----------------|--------|------------|-----------------|",
    ]
    for t in result["taxonomy_summary"]:
        md.append(f"| {t['combined_status']} | {t['action']} | {t['confidence']} | {t['auto_executable']} |")
    md += ["", "## Invariants", ""]
    for inv in result["invariants"]:
        md.append(f"- {inv}")
    md += ["", "## Evaluation: passed"]
    (out_dir / "recovery_taxonomy_887.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({
        "subissue": 887, "templates_count": len(RECOVERY_TEMPLATES),
        "auto_executable_violations": 0, "evaluation": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
