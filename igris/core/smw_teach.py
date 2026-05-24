from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class Incident:
    incident_id: str
    pattern_name: str
    detected_at: float
    resolved_at: Optional[float]
    root_cause: str
    actions_applied: List[str]
    outcome: str
    evidence: str


def record_incident(incident: Incident, project_root: str) -> None:
    p = Path(project_root) / ".igris" / "smw_knowledge_base.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    arr = []
    if p.exists():
        try:
            arr = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            arr = []
    arr.append(asdict(incident))
    p.write_text(json.dumps(arr, indent=2), encoding="utf-8")


def load_incidents(project_root: str) -> List[Incident]:
    p = Path(project_root) / ".igris" / "smw_knowledge_base.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return [Incident(**x) for x in data]
    except Exception:
        return []


def should_open_igris_issue(pattern_name: str, project_root: str) -> bool:
    incidents = [i for i in load_incidents(project_root) if i.pattern_name == pattern_name]
    if len(incidents) < 2:
        return False
    p = subprocess.run(["gh", "issue", "list", "--state", "open", "--label", "smw-teach", "--search", pattern_name], cwd=project_root, capture_output=True, text=True)
    return not bool((p.stdout or "").strip())


async def teach_back(incident: Incident, project_root: str) -> None:
    record_incident(incident, project_root)
    try:
        from igris.core.memory_graph import MemoryGraph
        graph = MemoryGraph(project_root)
        graph.add_node(
            "lesson",
            content={
                "pattern_name": incident.pattern_name,
                "action_taken": ",".join(incident.actions_applied or []),
                "failure_class": incident.pattern_name,
                "resolution": getattr(incident, "resolution_summary", "") or "",
            },
            confidence=0.8,
        )
    except Exception:
        pass
    if should_open_igris_issue(incident.pattern_name, project_root):
        title = f"feat(igris): handle {incident.pattern_name} autonomously"
        body = (
            f"## Perché questa issue esiste\n\n"
            f"Il SMW teaching loop ha rilevato il pattern **`{incident.pattern_name}`** "
            f"per la seconda volta (o più). Questo indica che IGRIS non gestisce ancora "
            f"questo scenario in autonomia e richiede un improvement del codice.\n\n"
            f"## Pattern ripetuto\n\n`{incident.pattern_name}`\n\n"
            f"## Root cause identificata\n\n{incident.root_cause}\n\n"
            f"## Evidence\n\n{incident.evidence}\n\n"
            f"---\n*Opened by: IGRIS (autonomous agent)*"
        )
        subprocess.run(["gh", "issue", "create", "--title", title, "--body", body, "--label", "smw-teach,created-by:igris"], cwd=project_root, capture_output=True, text=True)
