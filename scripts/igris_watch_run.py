#!/usr/bin/env python3
"""Compact supervisor run watcher.

Usage:
  scripts/igris_watch_run.py <run_id>
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url=url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _print_summary(data: dict) -> None:
    print(f"run_id: {data.get('run_id', '')}")
    print(f"rank_id: {data.get('rank_id', '')}")
    print(f"status: {data.get('status', '')}")
    print(f"failure_class: {data.get('failure_class', '')}")
    print(f"branch: {data.get('branch', '')}")
    print(f"current_stage: {data.get('current_stage', '')}")
    print(f"failed_stage: {data.get('failed_stage', '')}")
    print(f"repair_cycles: {data.get('repair_cycles_used', 0)}")
    print(
        "api_escalation: "
        f"calls={data.get('api_escalations_used', 0)} "
        f"budget_usd={data.get('api_budget_used_usd', 0)}"
    )
    stage = data.get("stage_summary", {}) or {}
    counts = stage.get("counts", {}) or {}
    print(
        "stages: "
        f"success={counts.get('success', 0)} "
        f"failure={counts.get('failure', 0)} "
        f"pending={counts.get('pending', 0)} "
        f"running={counts.get('running', 0)} "
        f"skipped={counts.get('skipped', 0)}"
    )
    audit = data.get("audit_summary", {}) or {}
    ac = audit.get("counts", {}) or {}
    print(
        "audit: "
        f"new={ac.get('audit-new', 0)} "
        f"reviewed={ac.get('audit-reviewed', 0)} "
        f"fixed={ac.get('audit-fixed', 0)} "
        f"deferred={ac.get('audit-deferred', 0)} "
        f"due={audit.get('next_review_due_count', 0)}"
    )
    last = data.get("last_event", {}) or {}
    print(
        "last_event: "
        f"{last.get('phase', '')}/{last.get('status', '')} "
        f"audit={last.get('audit_status', '')}"
    )
    print(f"escalation_issue: {data.get('escalation_issue_url', '')}")
    print(f"next_action: {data.get('next_action', '')}")


def _compact_from_full(payload: dict) -> dict:
    events = payload.get("events") or []
    last = events[-1] if events else {}
    return {
        "run_id": payload.get("run_id", ""),
        "rank_id": payload.get("rank_id", ""),
        "status": payload.get("status", ""),
        "failure_class": payload.get("failure_class", ""),
        "branch": payload.get("branch", ""),
        "repair_cycles_used": payload.get("repair_cycles_used", 0),
        "api_escalations_used": payload.get("api_escalations_used", 0),
        "api_budget_used_usd": payload.get("api_budget_used_usd", 0),
        "current_stage": "",
        "failed_stage": "",
        "stage_summary": {"counts": {}},
        "audit_summary": {"counts": {}, "next_review_due_count": 0},
        "escalation_issue_url": "",
        "last_event": {
            "phase": last.get("phase", ""),
            "status": last.get("status", ""),
            "audit_status": last.get("audit_status", ""),
        },
        "next_action": "",
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: scripts/igris_watch_run.py <run_id>", file=sys.stderr)
        return 2
    run_id = sys.argv[1].strip()
    if not run_id:
        print("run_id is required", file=sys.stderr)
        return 2

    summary_url = f"http://127.0.0.1:7778/api/rank/runs/{run_id}/summary"
    detail_url = f"http://127.0.0.1:7778/api/rank/runs/{run_id}"
    try:
        data = _get_json(summary_url)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        try:
            data = _compact_from_full(_get_json(detail_url))
        except Exception as inner:  # pragma: no cover - defensive fallback
            print(f"error: {inner}", file=sys.stderr)
            return 1
    except Exception as exc:  # pragma: no cover - defensive fallback
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _print_summary(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
