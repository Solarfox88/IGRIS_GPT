from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class PRReviewRequest:
    pr_number: int
    pr_title: str
    pr_diff: str
    issue_description: str
    changed_files: List[str]
    ci_passed: bool
    run_id: str
    last_failure_class: str
    repair_cycles_used: int
    max_repair_cycles: int
    capability_signals: Dict[str, Any]


@dataclass
class PRReviewResult:
    pr_number: int
    approved: bool
    confidence: float
    model_used: str
    concerns: List[str]
    suggestion: str
    review_timestamp: float
    tiebreaker_used: bool


def _is_high_risk(request: PRReviewRequest) -> bool:
    if request.last_failure_class in {"wrong_file_edit", "reasoning_loop_blocked"}:
        return True
    if request.repair_cycles_used == request.max_repair_cycles:
        return True
    return int(request.capability_signals.get("reasoning_timeout", 0)) >= 2


def _call_deepseek_review(request: PRReviewRequest, model: str, api_key: str, base_url: str, timeout: int) -> Dict[str, Any]:
    prompt = {
        "task": "Review PR safety/quality for autonomous merge gate",
        "rubric": [
            "File changes match issue intent",
            "Fix addresses root cause, not only symptom",
            "Tests cover the failure scenario",
            "No untested breakage against existing patterns",
            "Style/structure respects project conventions",
        ],
        "pr": asdict(request),
        "return_json_schema": {
            "approved": "bool",
            "confidence": "float 0-1",
            "concerns": ["string"],
            "suggestion": "string",
        },
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a strict PR reviewer. Output only JSON."},
            {"role": "user", "content": json.dumps(prompt)},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    content = body.get("choices", [{}])[0].get("message", {}).get("content", "{}")
    parsed = json.loads(content)
    return {
        "approved": bool(parsed.get("approved", False)),
        "confidence": float(parsed.get("confidence", 0.0)),
        "concerns": parsed.get("concerns", []) or [],
        "suggestion": str(parsed.get("suggestion", "")),
    }


def _call_codex_tiebreaker(request: PRReviewRequest, project_root: str) -> Dict[str, Any]:
    helper_cmd = os.getenv("IGRIS_API_HELPER_COMMAND", "")
    if not helper_cmd:
        raise RuntimeError("IGRIS_API_HELPER_COMMAND not configured")
    packet = {
        "model": os.getenv("IGRIS_API_HELPER_MODEL", "gpt-5.4-mini"),
        "max_tokens": 700,
        "packet": {
            "mode": "smw_pr_tiebreaker",
            "rubric": "approve only if safe and complete",
            "pr": asdict(request),
        },
    }
    proc = subprocess.run(
        helper_cmd.split(),
        input=json.dumps(packet),
        capture_output=True,
        text=True,
        cwd=project_root,
        timeout=90,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout or proc.stderr or "helper command failed")
    data = json.loads(proc.stdout)
    return {
        "approved": bool(data.get("ok", False) and data.get("risk", "medium") != "high"),
        "confidence": float(data.get("confidence", 0.5)),
        "concerns": list(data.get("risk_notes", [])),
        "suggestion": str(data.get("suggested_repair_strategy", "")),
    }


async def review_pr(request: PRReviewRequest, project_root: str) -> PRReviewResult:
    logger = logging.getLogger("igris.smw.pr_review")
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    flash = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    pro = os.getenv("DEEPSEEK_STRONG_MODEL", "deepseek-reasoner")
    first_model = pro if _is_high_risk(request) else flash
    second_model = flash if first_model == pro else pro
    tiebreaker_used = False
    try:
        first = await asyncio.to_thread(_call_deepseek_review, request, first_model, api_key, base_url, 90 if first_model == pro else 60)
        merged = first
        model_used = first_model
        if first["confidence"] < 0.6:
            second = await asyncio.to_thread(_call_deepseek_review, request, second_model, api_key, base_url, 90 if second_model == pro else 60)
            model_used = f"{first_model}+{second_model}"
            merged = second if second["confidence"] >= first["confidence"] else first
            if second["approved"] != first["approved"]:
                tiebreaker_used = True
                tie = await asyncio.to_thread(_call_codex_tiebreaker, request, project_root)
                merged = tie
                model_used = f"{model_used}+codex_tiebreaker"
        return PRReviewResult(request.pr_number, merged["approved"], max(0.0, min(1.0, merged["confidence"])), model_used, merged.get("concerns", []), merged.get("suggestion", ""), time.time(), tiebreaker_used)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
        logger.warning("PR review fail-open for PR #%s: %s", request.pr_number, exc)
        return PRReviewResult(request.pr_number, True, 0.3, "fail_open", [f"review API unavailable: {exc}"], "Manual follow-up recommended.", time.time(), tiebreaker_used)


def load_review_results(project_root: str) -> List[PRReviewResult]:
    p = Path(project_root) / ".igris" / "pr_reviews.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return [PRReviewResult(**item) for item in data]


def save_review_result(result: PRReviewResult, project_root: str) -> None:
    p = Path(project_root) / ".igris" / "pr_reviews.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    items = []
    if p.exists():
        items = json.loads(p.read_text(encoding="utf-8"))
    items.append(asdict(result))
    p.write_text(json.dumps(items[-200:], indent=2), encoding="utf-8")
