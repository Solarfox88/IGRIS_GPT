#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from igris.agent.mission.shadow_comparison import compare_shadow_records


def _load_shadow_records(project_root: Path) -> List[Dict[str, Any]]:
    shadow_dir = project_root / ".igris" / "mission_brain" / "shadow"
    if not shadow_dir.exists():
        return []
    records: List[Dict[str, Any]] = []
    for path in sorted(shadow_dir.glob("*.json")):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return records


def _write_outputs(project_root: Path, payload: Dict[str, Any]) -> Dict[str, str]:
    out_dir = project_root / "reports" / "mission_brain" / "integration" / "837"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "shadow_comparison_837.json"
    md_path = out_dir / "shadow_comparison_837.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    s = payload["summary"]
    lines = [
        "# Mission Brain Shadow Comparison — #837",
        "",
        f"- total_runs: {s['total_runs']}",
        f"- agreement_count: {s['agreement_count']}",
        f"- disagreement_count: {s['disagreement_count']}",
        f"- agreement_rate: {s['agreement_rate']}",
        f"- risky_mismatch_count: {s['risky_mismatch_count']}",
        f"- safe_mismatch_count: {s['safe_mismatch_count']}",
        f"- quality_gate_pass_rate: {s['quality_gate_pass_rate']}",
        f"- satisfaction_gate_pass_rate: {s['satisfaction_gate_pass_rate']}",
        "",
        "## Mismatch classes",
    ]
    for k, v in sorted(s["mismatch_classes"].items()):
        lines.append(f"- {k}: {v}")

    lines.extend(
        [
            "",
            "## Thresholds",
            "- risky_mismatch_count must remain 0 for rollout candidate",
            "- agreement_rate target >= 0.80 for stronger confidence",
            "- no behavior switch in this phase (analysis-only)",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def main() -> int:
    project_root = Path(".").resolve()
    records = _load_shadow_records(project_root)
    summary = compare_shadow_records(records).to_dict()
    payload = {
        "records_count": len(records),
        "summary": summary,
        "status": "passed" if summary["total_runs"] > 0 else "partial",
    }
    paths = _write_outputs(project_root, payload)
    print(json.dumps({"status": payload["status"], "paths": paths, "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

