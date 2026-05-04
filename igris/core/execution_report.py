"""
Execution report persistence for IGRIS_GPT.

Reports are stored as JSON files under ``.igris/reports/``.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from igris.core import safety
from igris.models.config import CONFIG


def _reports_dir() -> Path:
    d = CONFIG.project_root / ".igris" / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_report(
    command_id: str,
    capability_id: str,
    returncode: int,
    stdout: str,
    stderr: str,
    started_at: str,
    finished_at: str,
    duration_ms: int,
    task_id: Optional[int] = None,
) -> Dict:
    """Create and persist an execution report."""
    success = returncode == 0
    failure_type = None
    next_recommendation = None
    if not success:
        if "failed" in stderr.lower() or "FAILED" in stdout:
            failure_type = "test_failed"
            next_recommendation = "Review failing tests and fix"
        else:
            failure_type = "command_error"
            next_recommendation = "Check stderr for details"

    report = {
        "report_id": str(uuid.uuid4()),
        "task_id": task_id,
        "command_id": command_id,
        "capability_id": capability_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "returncode": returncode,
        "stdout_truncated": safety.truncate_output(safety.redact_secrets(stdout)),
        "stderr_truncated": safety.truncate_output(safety.redact_secrets(stderr)),
        "success": success,
        "failure_type": failure_type,
        "next_recommendation": next_recommendation,
        "artifacts": [],
    }
    fp = _reports_dir() / f"{report['report_id']}.json"
    fp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def get_report(report_id: str) -> Optional[Dict]:
    fp = _reports_dir() / f"{report_id}.json"
    if not fp.exists():
        return None
    return json.loads(fp.read_text(encoding="utf-8"))


def recent_reports(limit: int = 20) -> List[Dict]:
    files = sorted(_reports_dir().glob("*.json"), key=lambda p: p.stat().st_mtime)
    reports: List[Dict] = []
    for fp in files[-limit:]:
        try:
            reports.append(json.loads(fp.read_text(encoding="utf-8")))
        except Exception:
            continue
    return reports
