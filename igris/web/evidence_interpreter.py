"""Evidence interpretation for Control Room UX (#1130).

Transforms raw evidence data into structured, human-readable cards
for the operator. Each card type has a consistent schema:

    {
        "type": str,          # card type identifier
        "title": str,         # human-readable title
        "status": str,        # ok | warning | error | empty
        "summary": str,       # one-line human-readable summary
        "details": dict,      # type-specific structured data
    }
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from igris.core.safety import redact_secrets


# ---------------------------------------------------------------------------
# Truncation helper
# ---------------------------------------------------------------------------

MAX_LOG_CHARS = 2000
MAX_DETAIL_CHARS = 500


def _truncate(text: str, limit: int = MAX_LOG_CHARS) -> str:
    """Truncate long text with indicator."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"… [truncated, {len(text) - limit} chars omitted]"


def _safe_redact(value: Any) -> str:
    return redact_secrets(str(value) if value is not None else "")


# ---------------------------------------------------------------------------
# Evidence card builders
# ---------------------------------------------------------------------------

def interpret_test_result(test_data: Dict[str, Any]) -> Dict[str, Any]:
    """Interpret test result evidence into a structured card."""
    if not test_data or not test_data.get("available"):
        return {
            "type": "test_result",
            "title": "Test Results",
            "status": "empty",
            "summary": "No test results available for this run.",
            "details": {},
        }

    phase = test_data.get("phase", "unknown")
    status = test_data.get("status", "unknown")
    detail = _truncate(str(test_data.get("detail", "")), MAX_DETAIL_CHARS)

    card_status = "ok" if status == "success" else "error" if status == "failure" else "warning"
    summary = f"{phase}: {status}"
    if detail:
        summary += f" — {detail[:100]}"

    return {
        "type": "test_result",
        "title": "Test Results",
        "status": card_status,
        "summary": _safe_redact(summary),
        "details": {
            "phase": phase,
            "test_status": status,
            "detail": _safe_redact(detail),
        },
    }


def interpret_ci_result(evidence_events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Interpret CI/gate events into a structured card."""
    if not evidence_events:
        return {
            "type": "ci_result",
            "title": "CI / Quality Gates",
            "status": "empty",
            "summary": "No CI or quality gate events recorded.",
            "details": {"gates": []},
        }

    gates = []
    has_failure = False
    for ev in evidence_events:
        gate_status = ev.get("status", "unknown")
        if gate_status == "failure":
            has_failure = True
        gates.append({
            "phase": ev.get("phase", "unknown"),
            "status": gate_status,
            "detail": _safe_redact(_truncate(str(ev.get("detail", "")), MAX_DETAIL_CHARS)),
            "ts": ev.get("ts", 0),
        })

    card_status = "error" if has_failure else "ok"
    passed = sum(1 for g in gates if g["status"] == "success")
    summary = f"{passed}/{len(gates)} gates passed"
    if has_failure:
        failed_names = [g["phase"] for g in gates if g["status"] == "failure"]
        summary += f" — FAILED: {', '.join(failed_names[:3])}"

    return {
        "type": "ci_result",
        "title": "CI / Quality Gates",
        "status": card_status,
        "summary": summary,
        "details": {"gates": gates, "total": len(gates), "passed": passed},
    }


def interpret_diff_summary(diff_data: Dict[str, Any]) -> Dict[str, Any]:
    """Interpret diff summary into a structured card."""
    if not diff_data or not diff_data.get("available"):
        error = diff_data.get("error", "") if diff_data else ""
        return {
            "type": "diff_summary",
            "title": "Code Changes",
            "status": "empty" if not error else "error",
            "summary": f"Diff not available{': ' + str(error)[:100] if error else ''}.",
            "details": {},
        }

    files = diff_data.get("files_changed", [])
    summary_line = str(diff_data.get("summary", ""))
    if not files and summary_line == "no changes":
        return {
            "type": "diff_summary",
            "title": "Code Changes",
            "status": "empty",
            "summary": "No code changes detected.",
            "details": {"files": [], "summary": "no changes"},
        }

    return {
        "type": "diff_summary",
        "title": "Code Changes",
        "status": "ok",
        "summary": f"{len(files)} file(s) changed — {summary_line[:100]}",
        "details": {
            "files": files[:20],  # cap display
            "file_count": len(files),
            "summary": _safe_redact(summary_line),
        },
    }


def interpret_browser_evidence(run_events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Interpret browser evidence from run events (#1130).

    Looks for events with phase 'browser_evidence' or 'evidence_collection'
    that contain screenshot/console/network data.
    """
    browser_events = [
        ev for ev in (run_events or [])
        if (ev.get("phase", "") or "") in ("browser_evidence", "evidence_collection", "browser_check")
    ]
    if not browser_events:
        return {
            "type": "browser_evidence",
            "title": "Browser Evidence",
            "status": "empty",
            "summary": "No browser evidence collected for this run.",
            "details": {},
        }

    screenshots = 0
    console_entries = 0
    network_entries = 0
    has_error = False
    for ev in browser_events:
        data = ev.get("data", {}) if isinstance(ev.get("data"), dict) else {}
        screenshots += len(data.get("screenshots", []))
        console_entries += len(data.get("console", []))
        network_entries += len(data.get("network", []))
        if ev.get("status") == "failure":
            has_error = True

    card_status = "error" if has_error else "ok" if screenshots > 0 else "warning"
    summary = f"{screenshots} screenshot(s), {console_entries} console, {network_entries} network events"

    return {
        "type": "browser_evidence",
        "title": "Browser Evidence",
        "status": card_status,
        "summary": summary,
        "details": {
            "screenshot_count": screenshots,
            "console_count": console_entries,
            "network_count": network_entries,
            "event_count": len(browser_events),
        },
    }


def interpret_devops_health(health_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Interpret DevOps health check into a structured card."""
    if not health_data:
        return {
            "type": "devops_health",
            "title": "DevOps / VPS Health",
            "status": "empty",
            "summary": "No health data available.",
            "details": {},
        }

    checks = {}
    has_error = False
    for key in ("disk", "memory", "igris_service"):
        check = health_data.get(key, {})
        if isinstance(check, dict):
            checks[key] = check.get("status", "unknown")
            if check.get("status") == "error":
                has_error = True

    card_status = "error" if has_error else "ok"
    ok_count = sum(1 for v in checks.values() if v == "ok")
    summary = f"{ok_count}/{len(checks)} checks OK"
    if has_error:
        failed = [k for k, v in checks.items() if v == "error"]
        summary += f" — issues: {', '.join(failed)}"

    return {
        "type": "devops_health",
        "title": "DevOps / VPS Health",
        "status": card_status,
        "summary": summary,
        "details": health_data,
    }


def interpret_memory_influence(influence_data: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Interpret memory influence report into a structured card."""
    if not influence_data:
        return {
            "type": "memory_influence",
            "title": "Memory Influence",
            "status": "empty",
            "summary": "No memory entries influenced this run.",
            "details": {"entries": []},
        }

    stale_count = sum(1 for e in influence_data if e.get("stale"))
    contradiction_count = sum(1 for e in influence_data if e.get("contradiction"))

    card_status = "warning" if (stale_count > 0 or contradiction_count > 0) else "ok"
    summary = f"{len(influence_data)} memory entries used"
    if stale_count:
        summary += f", {stale_count} stale"
    if contradiction_count:
        summary += f", {contradiction_count} contradictions"

    return {
        "type": "memory_influence",
        "title": "Memory Influence",
        "status": card_status,
        "summary": summary,
        "details": {
            "entries": influence_data[:10],
            "total": len(influence_data),
            "stale_count": stale_count,
            "contradiction_count": contradiction_count,
        },
    }


# ---------------------------------------------------------------------------
# Composite evidence interpretation
# ---------------------------------------------------------------------------

def interpret_all_evidence(
    diff_summary: Optional[Dict[str, Any]] = None,
    test_results: Optional[Dict[str, Any]] = None,
    evidence_events: Optional[List[Dict[str, Any]]] = None,
    run_events: Optional[List[Dict[str, Any]]] = None,
    devops_health: Optional[Dict[str, Any]] = None,
    memory_influence: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Return all evidence cards for a run."""
    cards = [
        interpret_diff_summary(diff_summary or {}),
        interpret_test_result(test_results or {}),
        interpret_ci_result(evidence_events or []),
        interpret_browser_evidence(run_events or []),
        interpret_devops_health(devops_health),
        interpret_memory_influence(memory_influence),
    ]
    return cards


# ---------------------------------------------------------------------------
# Next-action recommendation
# ---------------------------------------------------------------------------

def compute_next_actions(
    outcome: str,
    failure_class: str = "",
    evidence_cards: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Return operator next-action recommendations based on run state."""
    actions: List[Dict[str, Any]] = []
    evidence_cards = evidence_cards or []

    if outcome == "success":
        actions.append({
            "id": "review_evidence",
            "label": "Review Evidence",
            "reason": "Run completed — verify changes before closing issue.",
            "approval_required": False,
        })
        actions.append({
            "id": "close_issue",
            "label": "Close GitHub Issue",
            "reason": "Evidence reviewed, run successful.",
            "approval_required": True,
        })
    elif outcome == "blocked":
        if failure_class in ("pytest_failure", "missing_tests"):
            actions.append({
                "id": "review_test_failures",
                "label": "Review Test Failures",
                "reason": f"Run blocked on {failure_class}.",
                "approval_required": False,
            })
        elif failure_class == "capability_ceiling_reached":
            actions.append({
                "id": "decompose_task",
                "label": "Decompose Task Manually",
                "reason": "Model capability ceiling reached.",
                "approval_required": False,
            })
        else:
            actions.append({
                "id": "review_risk_detail",
                "label": "Review Risk Detail",
                "reason": f"Run blocked: {failure_class or 'unknown'}.",
                "approval_required": False,
            })
        actions.append({
            "id": "retry_run",
            "label": "Retry Run",
            "reason": "Attempt another repair cycle.",
            "approval_required": True,
        })
    elif outcome == "decomposition_required":
        actions.append({
            "id": "review_decomposition",
            "label": "Review Decomposition",
            "reason": "Sub-missions generated — review dependency order.",
            "approval_required": False,
        })
        actions.append({
            "id": "approve_decomposition",
            "label": "Approve Sub-Missions",
            "reason": "Start executing decomposed sub-missions.",
            "approval_required": True,
        })
    elif outcome == "in_progress":
        actions.append({
            "id": "monitor_run",
            "label": "Monitor Progress",
            "reason": "Run is active — check timeline for status.",
            "approval_required": False,
        })
        actions.append({
            "id": "block_run",
            "label": "Block Run",
            "reason": "Emergency stop if needed.",
            "approval_required": True,
        })
    elif outcome == "cancelled":
        actions.append({
            "id": "review_cancellation",
            "label": "Review Cancellation",
            "reason": "Run was cancelled — check reason.",
            "approval_required": False,
        })

    # Add warnings from evidence cards
    error_cards = [c for c in evidence_cards if c.get("status") == "error"]
    if error_cards:
        card_names = ", ".join(c.get("title", "?") for c in error_cards[:3])
        actions.append({
            "id": "investigate_errors",
            "label": "Investigate Errors",
            "reason": f"Issues found in: {card_names}.",
            "approval_required": False,
        })

    return actions
