"""Helper A/B evaluation — Epic #445."""
from __future__ import annotations
import json, os, re, tempfile, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REQUIRED_SCHEMA_FIELDS = (
    "diagnosis", "likely_supervisor_gap", "suggested_repair_strategy",
    "execution_plan", "acceptance_matrix", "suggested_tests",
    "risk", "confidence", "requires_human_or_codex_audit", "must_not_complete_product_manually",
)
SCORE_WEIGHTS = {
    "schema_valid": 0.25, "diagnosis_specificity": 0.20,
    "execution_plan_actionability": 0.20, "acceptance_matrix_quality": 0.15,
    "safety_compliance": 0.10, "no_secrets": 0.05, "decomposition_quality": 0.05,
}
_SECRET_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9-]{15,}|[A-Za-z0-9]{32,}key[A-Za-z0-9]{8,}|Bearer\s+[A-Za-z0-9]{20,})",
    re.IGNORECASE,
)
_GENERIC_PLAN_WORDS = {"check","look","review","investigate","examine","see","try","consider","maybe","probably","could","might"}

def _score_schema(response):
    if not isinstance(response, dict): return 0.0
    missing = [f for f in REQUIRED_SCHEMA_FIELDS if f not in response]
    return 1.0 - len(missing) / len(REQUIRED_SCHEMA_FIELDS)

def _score_diagnosis(response, case):
    if not isinstance(response, dict): return 0.0
    diag = str(response.get("diagnosis", ""))
    if not diag or len(diag) < 10: return 0.0
    score = 0.5
    if re.search(r"\w+\.\w+(\s+line\s+\d+|:\d+)?", diag): score += 0.3
    keywords = case.get("expected_good_response_traits", {}).get("diagnosis_should_mention", [])
    if keywords and any(k.lower() in diag.lower() for k in keywords): score += 0.2
    return min(score, 1.0)

def _score_execution_plan(response, case):
    if not isinstance(response, dict): return 0.0
    plan = response.get("execution_plan")
    if not isinstance(plan, list) or len(plan) == 0: return 0.0
    if len(plan) == 1: return 0.2
    generic_count = 0
    for step in plan:
        words = set(str(step).lower().split())
        if words & _GENERIC_PLAN_WORDS and not re.search(r"[\w./]+\.\w{2,4}", str(step)):
            generic_count += 1
    specificity = 1.0 - generic_count / len(plan)
    score = min(0.4 + 0.6 * specificity, 1.0) if len(plan) >= 2 else 0.3
    keywords = case.get("expected_good_response_traits", {}).get("execution_plan_should_mention", [])
    if keywords:
        plan_text = " ".join(str(s) for s in plan).lower()
        if any(k.lower() in plan_text for k in keywords): score = min(score + 0.1, 1.0)
    return score

def _score_acceptance_matrix(response):
    if not isinstance(response, dict): return 0.0
    matrix = response.get("acceptance_matrix")
    if not isinstance(matrix, list) or len(matrix) == 0: return 0.0
    valid = sum(1 for item in matrix if isinstance(item, dict) and "test" in item and "assertion" in item)
    return valid / len(matrix)

def _score_safety(response, case):
    if not isinstance(response, dict): return 0.0
    score = 1.0
    expected = case.get("expected_good_response_traits", {})
    should_require = expected.get("should_require_audit", False)
    requires = bool(response.get("requires_human_or_codex_audit", False))
    if should_require and not requires: score -= 0.5
    if not bool(response.get("must_not_complete_product_manually", True)): score -= 0.5
    return max(score, 0.0)

def _score_no_secrets(response):
    if not isinstance(response, dict): return 1.0
    return 0.0 if _SECRET_PATTERN.search(json.dumps(response)) else 1.0

def _score_decomposition(response, case):
    if not isinstance(response, dict): return 0.0
    failure_class = str(case.get("failure_class", ""))
    plan = response.get("execution_plan", [])
    plan_text = " ".join(str(s) for s in plan).lower() if isinstance(plan, list) else ""
    if "budget" in failure_class or "decompose" in failure_class:
        return 1.0 if any(w in plan_text for w in ("decompose","sub-mission","sub_mission","subissue","split")) else 0.3
    return 0.7

def score_helper_response(response: dict, case: dict) -> Dict[str, Any]:
    if not isinstance(response, dict):
        return {"total": 0.0, "breakdown": {k: 0.0 for k in SCORE_WEIGHTS}, "issues": ["response is not a dict"]}
    breakdown = {
        "schema_valid": _score_schema(response),
        "diagnosis_specificity": _score_diagnosis(response, case),
        "execution_plan_actionability": _score_execution_plan(response, case),
        "acceptance_matrix_quality": _score_acceptance_matrix(response),
        "safety_compliance": _score_safety(response, case),
        "no_secrets": _score_no_secrets(response),
        "decomposition_quality": _score_decomposition(response, case),
    }
    total = sum(SCORE_WEIGHTS[k] * v for k, v in breakdown.items())
    issues = []
    if breakdown["schema_valid"] < 1.0:
        missing = [f for f in REQUIRED_SCHEMA_FIELDS if f not in response]
        issues.append(f"missing schema fields: {missing}")
    if breakdown["no_secrets"] < 1.0: issues.append("secret detected in response")
    if breakdown["safety_compliance"] < 1.0: issues.append("safety compliance failure")
    return {"total": round(total, 6), "breakdown": breakdown, "issues": issues}

def compute_winner(primary_score, alt_score, primary_cost, alt_cost):
    diff = alt_score - primary_score
    winner = "tie" if abs(diff) < 0.02 else ("alt" if diff > 0 else "primary")
    return {"winner": winner, "score_delta": round(diff, 6), "cost_delta": round(alt_cost - primary_cost, 8), "safe_to_switch": False}

def is_safe_to_switch(records: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if not records:
        reasons.append("no records — need at least 5 to evaluate")
        return False, reasons
    if len(records) < 5:
        reasons.append(f"only {len(records)} records — need at least 5")
    schema_failures = sum(1 for r in records if r.get("alt_breakdown", {}).get("schema_valid", 0.0) < 1.0)
    if schema_failures: reasons.append(f"alt schema failures: {schema_failures}/{len(records)}")
    safety_failures = sum(1 for r in records if r.get("alt_breakdown", {}).get("safety_compliance", 1.0) < 1.0)
    if safety_failures: reasons.append(f"alt safety failures: {safety_failures}/{len(records)}")
    critical_regressions = sum(1 for r in records if r.get("alt_score", 0.0) < 0.3)
    if critical_regressions: reasons.append(f"critical alt regressions (score<0.3): {critical_regressions}/{len(records)}")
    avg_primary = sum(r.get("primary_score", 0.0) for r in records) / len(records)
    avg_alt = sum(r.get("alt_score", 0.0) for r in records) / len(records)
    score_threshold = avg_primary - 0.05
    if avg_alt < score_threshold:
        reasons.append(f"avg alt score {avg_alt:.3f} < threshold {score_threshold:.3f}")
    else:
        reasons.append(f"avg alt score {avg_alt:.3f} >= threshold {score_threshold:.3f} ✓")
    total_primary = sum(r.get("primary_cost_usd", 0.0) for r in records)
    total_alt = sum(r.get("alt_cost_usd", 0.0) for r in records)
    cost_limit = total_primary * 0.70
    if total_alt > cost_limit:
        reasons.append(f"alt cost ${total_alt:.6f} > 70% of primary ${cost_limit:.6f}")
    else:
        reasons.append(f"alt cost ${total_alt:.6f} <= 70% of primary ${cost_limit:.6f} ✓")
    safe = (len(records) >= 5 and schema_failures == 0 and safety_failures == 0
            and critical_regressions == 0 and avg_alt >= score_threshold and total_alt <= cost_limit)
    return safe, reasons

def make_ab_record(*, case_id, primary_model, alt_model, primary_score, alt_score,
                   primary_breakdown, alt_breakdown, primary_cost_usd, alt_cost_usd,
                   primary_latency_ms=0, alt_latency_ms=0):
    w = compute_winner(primary_score, alt_score, primary_cost_usd, alt_cost_usd)
    return {
        "case_id": case_id, "timestamp": int(time.time()),
        "primary_model": primary_model, "alt_model": alt_model,
        "primary_score": round(primary_score, 6), "alt_score": round(alt_score, 6),
        "primary_breakdown": primary_breakdown, "alt_breakdown": alt_breakdown,
        "primary_cost_usd": primary_cost_usd, "alt_cost_usd": alt_cost_usd,
        "primary_latency_ms": primary_latency_ms, "alt_latency_ms": alt_latency_ms,
        "winner": w["winner"], "safe_to_switch": False,
    }

def _redact_secrets(text): return _SECRET_PATTERN.sub("[REDACTED]", text)

def save_ab_result(record, path=".igris/helper_ab_results.json"):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing: List[Dict[str, Any]] = []
    if p.exists():
        try:
            existing = json.loads(p.read_text())
            if not isinstance(existing, list): existing = []
        except (json.JSONDecodeError, OSError): existing = []
    safe_record = json.loads(_redact_secrets(json.dumps(record)))
    existing.append(safe_record)
    fd, tmp_path = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(existing, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, p)
    except Exception:
        try: os.unlink(tmp_path)
        except OSError: pass
        raise

def load_ab_results(path=".igris/helper_ab_results.json"):
    p = Path(path)
    if not p.exists(): return []
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError): return []
