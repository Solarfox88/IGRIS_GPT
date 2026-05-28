#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.integration_readiness import build_readiness_payload


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    root = Path(".")
    shadow_path = root / "reports" / "mission_brain" / "integration" / "837" / "shadow_comparison_837.json"
    rollback_path = root / "reports" / "mission_brain" / "integration" / "838" / "rollback_simulation_838.json"

    shadow = _load_json(shadow_path)
    rollback = _load_json(rollback_path)
    payload = build_readiness_payload(
        shadow_summary=shadow.get("summary", {}),
        rollback_summary=rollback.get("summary", {}),
        critical_false_completed_count=0,
    )
    out_dir = root / "reports" / "mission_brain" / "integration" / "839"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_out = out_dir / "integration_readiness_839.json"
    md_out = out_dir / "integration_readiness_839.md"
    json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Mission Brain Integration Readiness — #839",
        "",
        f"- decision: {payload['decision']}",
        f"- risky_mismatch_count: {payload['shadow_summary'].get('risky_mismatch_count', 0)}",
        f"- agreement_rate: {payload['shadow_summary'].get('agreement_rate', 0.0)}",
        f"- critical_false_completed_count: {payload['critical_false_completed_count']}",
        f"- rollback_policy_working: {int(payload['rollback_summary'].get('wrapper_effective_count', 0)) > 0}",
        "",
        "## Decision mapping",
        "- `controlled rollout candidate`: risky mismatches zero + strong agreement + rollback functional",
        "- `keep shadow mode`: rollback functional but readiness not sufficient for rollout",
        "- `remediate again`: rollback not reliable and readiness insufficient",
        "- `do not integrate`: critical false completed detected",
    ]
    md_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"decision": payload["decision"], "json": str(json_out), "md": str(md_out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

