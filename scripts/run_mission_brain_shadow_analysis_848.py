#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from igris.agent.mission.shadow_monitoring_analysis import analyze_disagreements


def main() -> int:
    in_path = Path("reports/mission_brain/shadow_monitoring/847/shadow_batch1_cycles_847.json")
    rows = json.loads(in_path.read_text(encoding="utf-8"))
    out = analyze_disagreements(rows)

    out_dir = Path("reports/mission_brain/shadow_monitoring/848")
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "shadow_disagreement_analysis_848.json"
    md_path = out_dir / "shadow_disagreement_analysis_848.md"
    json_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    lines = [
        "# Shadow Monitoring Disagreement Analysis — #848",
        "",
        f"- total_cycles: {out['total_cycles']}",
        f"- disagreement_count: {out['disagreement_count']}",
        f"- disagreement_rate: {out['disagreement_rate']}",
        f"- dominant_mismatch_class: {out['dominant_mismatch_class']}",
        f"- prevented_error_candidates: {out['prevented_error_candidates']}",
        f"- risk_introduced_candidates: {out['risk_introduced_candidates']}",
        f"- potential_false_completed: {out['potential_false_completed']}",
        f"- potential_false_partial: {out['potential_false_partial']}",
        f"- potential_false_failed: {out['potential_false_failed']}",
        f"- recommendation_focus: {out['recommendation_focus']}",
        "",
        "## Mismatch classes",
    ]
    for k, v in sorted(out["mismatch_classes"].items()):
        lines.append(f"- {k}: {v}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({"json": str(json_path), "md": str(md_path), "analysis": out}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

