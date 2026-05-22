from __future__ import annotations

import json
import time
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


def _mk(name, desc, sev, value, threshold, action):
    return WeakSignal(name, desc, sev, value, threshold, action, time.time())


def _ts(r):
    raw = r.get('created_at', '')
    if not raw:
        return 0.0
    try:
        from datetime import datetime, timezone
        s = str(raw).replace('Z', '+00:00')
        return datetime.fromisoformat(s).astimezone(timezone.utc).timestamp()
    except Exception:
        return 0.0


def _budget_ceiling_hit(r):
    used = int(r.get('api_escalations_used', 0))
    mx = int(r.get('max_api_escalations_per_run', 0))
    return mx > 0 and used >= mx


def _load_runs(project_root):
    p = Path(project_root) / '.igris' / 'supervisor_runs.json'
    if not p.exists():
        return []
    try:
        payload = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return []
    runs_dict = payload.get('runs', {}) if isinstance(payload, dict) else {}
    if not isinstance(runs_dict, dict):
        return []
    runs = list(runs_dict.values())
    runs.sort(key=lambda r: _ts(r))
    return runs


def detect_model_overkill(runs):
    sample = runs[-20:]
    if not sample:
        return None
    escalated = sum(1 for r in sample if r.get('api_escalations_used', 0) > 0 and not _budget_ceiling_hit(r))
    rate = escalated / len(sample)
    return _mk('model_overkill', 'Frequent escalation without budget ceiling pressure', 'WARN', rate, 0.6, 'Tune routing thresholds') if rate > 0.6 else None


def detect_decomposition_inflation(runs):
    sample = runs[-10:]
    if not sample:
        return None
    decomp_count = sum(1 for r in sample if r.get('failure_class') == 'decomposition_required')
    rate = decomp_count / len(sample)
    return _mk('decomposition_inflation', f'Decomposition required in {decomp_count}/{len(sample)} recent runs', 'WARN', rate, 0.5, 'Refine decomposition prompts') if rate > 0.5 else None


def detect_systemic_capability_gap(runs):
    sample = runs[-20:]
    mp: Dict[str, set] = {}
    for r in sample:
        fc = r.get('failure_class') or r.get('last_failure_class')
        run_id = r.get('run_id') or r.get('rank_id')
        if fc and run_id:
            mp.setdefault(str(fc), set()).add(str(run_id))
    for fc, run_ids in mp.items():
        if len(run_ids) > 3:
            return _mk('systemic_capability_gap', f"Failure class '{fc}' repeated in {len(run_ids)} distinct runs", 'ACTION_REQUIRED', float(len(run_ids)), 3.0, 'Open diagnostic issue and retrain')
    return None


def detect_repair_cycle_saturation(runs):
    sample = runs[-10:]
    if not sample:
        return None
    sat = sum(1 for r in sample if r.get('repair_cycles_used') == r.get('max_repair_cycles') and r.get('max_repair_cycles'))
    rate = sat / len(sample)
    return _mk('repair_cycle_saturation', 'Most runs hit repair-cycle maximum', 'WARN', rate, 0.7, 'Increase diagnosis quality before repairs') if rate > 0.7 else None


def detect_cost_drift(runs):
    now = time.time()
    wk = 7 * 24 * 3600
    this_week = [float(r.get('api_budget_used_usd', 0.0)) for r in runs if 0 < now - _ts(r) <= wk]
    prev_week = [float(r.get('api_budget_used_usd', 0.0)) for r in runs if wk < now - _ts(r) <= 2 * wk]
    if not this_week or not prev_week:
        return None
    a = sum(this_week) / len(this_week)
    b = sum(prev_week) / len(prev_week)
    if b <= 0:
        return None
    return _mk('cost_drift', 'Average API spend drifted significantly week-over-week', 'ACTION_REQUIRED', a, b * 1.3, 'Audit escalation and model policy') if a > b * 1.3 else None


def detect_fix_not_sticky(runs, project_root):
    done_at: Dict[str, float] = {}
    for r in runs:
        branch = r.get('branch', '')
        if not branch:
            continue
        if r.get('status') == 'done':
            ts = _ts({'created_at': r.get('updated_at') or r.get('created_at', '')})
            done_at[branch] = ts
        elif branch in done_at and r.get('status') not in ('done', None):
            elapsed = _ts(r) - done_at[branch]
            if 0 < elapsed <= 48 * 3600:
                return _mk('fix_not_sticky', f'Branch {branch!r} re-appeared non-done within 48h after completion', 'ACTION_REQUIRED', elapsed, 48 * 3600, 'Open regression diagnostic issue')
    return None


def detect_escalation_rate_high(runs):
    sample = runs[-20:]
    if not sample:
        return None
    rate = sum(1 for r in sample if r.get('api_escalations_used', 0) > 0) / len(sample)
    return _mk('escalation_rate_high', 'Escalations happening in over half of recent runs', 'WARN', rate, 0.5, 'Tune local-first policy') if rate > 0.5 else None


def run_all_detectors(project_root):
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


def save_weak_signals(signals, project_root):
    p = Path(project_root) / '.igris' / 'weak_signals.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([asdict(s) for s in signals], indent=2), encoding='utf-8')


def get_weak_signal_summary(project_root):
    runs = _load_runs(project_root)
    signals = run_all_detectors(project_root)
    sample20 = runs[-20:]
    sample10 = runs[-10:]
    avg_cycles = (sum(float(r.get('repair_cycles_used', 0)) for r in sample10) / len(sample10)) if sample10 else 0.0
    escalation_rate = (sum(1 for r in sample20 if r.get('api_escalations_used', 0) > 0) / len(sample20)) if sample20 else 0.0
    now = time.time()
    wk = 7 * 24 * 3600
    cur = [float(r.get('api_budget_used_usd', 0.0)) for r in runs if 0 < now - _ts(r) <= wk]
    prev = [float(r.get('api_budget_used_usd', 0.0)) for r in runs if wk < now - _ts(r) <= 2 * wk]
    cur_avg = (sum(cur) / len(cur)) if cur else 0.0
    prev_avg = (sum(prev) / len(prev)) if prev else 0.0
    cost_drift_pct = ((cur_avg - prev_avg) / prev_avg * 100.0) if prev_avg > 0 else 0.0
    done_total = sum(1 for r in runs if r.get('status') == 'done')
    sticky_hits = 1 if detect_fix_not_sticky(runs, project_root) else 0
    fix_sticky_rate = 1.0 - (sticky_hits / done_total) if done_total else 1.0
    return {
        'weak_signals_active': [asdict(s) for s in signals],
        'metrics': {
            'avg_repair_cycles': avg_cycles,
            'escalation_rate': escalation_rate,
            'cost_drift_pct': cost_drift_pct,
            'fix_sticky_rate': fix_sticky_rate,
        },
    }
