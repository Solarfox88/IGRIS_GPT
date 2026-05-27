from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from igris.agent.mission.mission_schema import Mission


def mission_reports_dir(project_root: str = ".") -> Path:
    path = Path(project_root) / ".igris" / "mission_brain" / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def mission_report_path(mission_id: str, project_root: str = ".") -> Path:
    return mission_reports_dir(project_root) / f"{mission_id}.json"


def save_mission_report(mission: Mission, project_root: str = ".") -> Path:
    path = mission_report_path(mission.id, project_root)
    path.write_text(json.dumps(mission.to_dict(), indent=2), encoding="utf-8")
    return path


def load_mission_report(mission_id: str, project_root: str = ".") -> Optional[Mission]:
    path = mission_report_path(mission_id, project_root)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return Mission.from_dict(data)
