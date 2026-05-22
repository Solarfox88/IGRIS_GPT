from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class WeakSignal:
    name: str
    description: str
    severity: str
    metric_value: float
    threshold: float
    recommended_action: str
    detected_at: float


def _mk(name: str, desc: str, sev: str, value: float, threshold: float, action: str) -> WeakSignal:
    return WeakSignal(name, desc, sev, value, threshold, action, time.time())


def detect_model_overkill(runs: List[Dict[str, Any]]) -> Optional[WeakSignal]:
    sample = runs[-20:]
    if not sample:
        return None
    escalated = sum(1 for r in sample if r.get("api_escalations_used", 0) > 0 and not r.get("api_budget_ceiling_hit", False))
    rate = escalated / len(sample)
    return _mk("model_overkill", "Frequent escalation without budget ceiling pressure", "WARN", rate, 0.6, "Tune routing thresholds") if rate > 0.6 else None


def detect_decomposition_inflation(runs: List[Dict[str, Any]]) -> Optional[WeakSignal]:
    sample = [r for r in runs[-5:] if r.get("decomposition_required")]
    if not sample:
        return None
    avg = sum(float(r.get("sub_issues_count", 0)) for r in sample) / len(sample)
    return _mk("decomposition_inflation", "Decomposition producing too many sub-issues", "WARN", avg, 3.0, "Refine decomposition prompts") if avg > 3 else None


def detect_systemic_capability_gap(runs: List[Dict[str, Any]]) -> Optional[WeakSignal]:
    sample = runs[-20:]
    mp: Dict[str, set] = {}
    for r in sample:
        fc = r.get("last_failure_class")
        issue = r.get("issue_number")
        if fc and issue is not None:
            mp.setdefault(str(fc), set()).add(issue)
    for fc, issues in mp.items():
        if len(issues) > 3:
            return _mk("systemic_capability_gap", f"Failure class '{fc}' repeated across multiple issues", "ACTION_REQUIRED", float(len(issues)), 3.0, "Open diagnostic issue and retrain")
    return None


def detect_repair_cycle_saturation(runs: List[Dict[str, Any]]) -> Optional[WeakSignal]:
    sample = runs[-10:]
    if not sample:
        return None
    sat = sum(1 for r in sample if r.get("repair_cycles_used") == r.get("max_repair_cycles"))
    rate = sat / len(sample)
    return _mk("repair_cycle_saturation", "Most runs hit repair-cycle maximum", "WARN", rate, 0.7, "Increase diagnosis quality before repairs") if rate > 0.7 else None


def detect_cost_drift(runs: List[Dict[str, Any]]) -> Optional[WeakSignal]:
    now = time.time()
    wk = 7 * 24 * 3600
    this_week = [float(r.get("api_budget_used_usd", 0.0)) for r in runs if now - float(r.get("started_at", now)) <= wk]
    prev_week = [float(r.get("api_budget_used_usd", 0.0)) for r in runs if wk < (now - float(r.get("started_at", now))) <= 2 * wk]
    if not this_week or not prev_week:
        return None
    a = sum(this_week) / len(this_week)
    b = sum(prev_week) / len(prev_week)
    if b <= 0:
        return None
    return _mk("cost_drift", "Average API spend drifted significantly week-over-week", "ACTION_REQUIRED", a, b * 1.3, "Audit escalation and model policy") if a > b * 1.3 else None


def detect_fix_not_sticky(runs: List[Dict[str, Any]], project_root: str) -> Optional[WeakSignal]:
    done = {}
    for r in runs:
        issue = r.get("issue_number")
        if issue is None:
            continue
        if r.get("status") == "done":
            done[issue] = float(r.get("finished_at", r.get("started_at", 0.0)))
        if issue in done and r.get("status") != "done":
            ts = float(r.get("started_at", 0.0))
            if 0 <= ts - done[issue] <= 48 * 3600:
                return _mk("fix_not_sticky", f"Issue #{issue} re-opened within 48h after done", "ACTION_REQUIRED", ts - done[issue], 48 * 3600, "Open regression diagnostic issue")
    return None


def detect_escalation_rate_high(runs: List[Dict[str, Any]]) -> Optional[WeakSignal]:
    sample = runs[-20:]
    if not sample:
        return None
    rate = sum(1 for r in sample if r.get("api_escalations_used", 0) > 0) / len(sample)
    return _mk("escalation_rate_high", "Escalations happening in over half of recent runs", "WARN", rate, 0.5, "Tune local-first policy") if rate > 0.5 else None


def _load_runs(project_root: str) -> List[Dict[str, Any]]:
    p = Path(project_root) / ".igris" / "supervisor_runs.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def run_all_detectors(project_root: str) -> List[WeakSignal]:
    runs = _load_runs(project_root)
    signals = [
        detect_model_overkill(runs),
        detect_decomposition_inflation(runs),
        detect_systemic_capability_gap(runs),
        detect_repair_cycle_saturation(runs),
        detect_cost_drift(runs),
        detect_fix_not_sticky(runs, project_root),
        detect_escalation_rate_high(runs),
    ]
    return [s for s in signals if s is not None]


def save_weak_signals(signals: List[WeakSignal], project_root: str) -> None:
    p = Path(project_root) / ".igris" / "weak_signals.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([asdict(s) for s in signals], indent=2), encoding="utf-8")


def get_weak_signal_summary(project_root: str) -> Dict[str, Any]:
    runs = _load_runs(project_root)
    signals = run_all_detectors(project_root)
    sample20 = runs[-20:]
    sample10 = runs[-10:]
    avg_cycles = (sum(float(r.get("repair_cycles_used", 0)) for r in sample10) / len(sample10)) if sample10 else 0.0
    escalation_rate = (sum(1 for r in sample20 if r.get("api_escalations_used", 0) > 0) / len(sample20)) if sample20 else 0.0
    now = time.time()
    wk = 7 * 24 * 3600
    cur = [float(r.get("api_budget_used_usd", 0.0)) for r in runs if now - float(r.get("started_at", now)) <= wk]
    prev = [float(r.get("api_budget_used_usd", 0.0)) for r in runs if wk < (now - float(r.get("started_at", now))) <= 2 * wk]
    cur_avg = (sum(cur) / len(cur)) if cur else 0.0
    prev_avg = (sum(prev) / len(prev)) if prev else 0.0
    cost_drift_pct = ((cur_avg - prev_avg) / prev_avg * 100.0) if prev_avg > 0 else 0.0
    done_total = sum(1 for r in runs if r.get("status") == "done")
    sticky_hits = 1 if detect_fix_not_sticky(runs, project_root) else 0
    fix_sticky_rate = 1.0 - (sticky_hits / done_total) if done_total else 1.0
    return {
        "weak_signals_active": [asdict(s) for s in signals],
        "metrics": {
            "avg_repair_cycles": avg_cycles,
            "escalation_rate": escalation_rate,
            "cost_drift_pct": cost_drift_pct,
            "fix_sticky_rate": fix_sticky_rate,
        },
    }
