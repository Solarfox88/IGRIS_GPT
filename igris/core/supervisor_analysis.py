"""Supervisor failure analysis and diff validation utilities.

Standalone functions for failure classification, diff analysis, baseline cache
management, and validation. Extracted from self_repair_supervisor.py for
modularity (Issue #1312).
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from igris.core.supervisor_models import CommandResult, WRITE_ACTION_TYPES


def classify_failure(
    reasoning_result: Optional[Dict[str, Any]] = None,
    diff: str = "",
    targeted_tests: Optional[CommandResult] = None,
    full_tests: Optional[CommandResult] = None,
    smoke: Optional[CommandResult] = None,
) -> str:
    reasoning_text = ""
    if reasoning_result:
        reasoning_text = "\n".join(
            str(reasoning_result.get(key, ""))
            for key in ("final_summary", "error", "stop_reason")
        )
    text = "\n".join([
        reasoning_text,
        diff or "",
        targeted_tests.error if targeted_tests else "",
        targeted_tests.output if targeted_tests else "",
        full_tests.error if full_tests else "",
        full_tests.output if full_tests else "",
    ])
    if _has_destructive_diff(diff):
        return "destructive_diff"
    if _is_llm_provider_unavailable(reasoning_text):
        return "infrastructure_bug"
    if targeted_tests and targeted_tests.returncode == 124:
        return "test_runner_timeout"
    if full_tests and full_tests.returncode == 124:
        return "test_runner_timeout"
    if targeted_tests and not targeted_tests.success:
        if _is_missing_test_target_error(targeted_tests):
            return "missing_tests"
        return "pytest_failure"
    if full_tests and not full_tests.success:
        return "pytest_failure"
    if reasoning_result:
        stop = str(reasoning_result.get("stop_reason", ""))
        status = str(reasoning_result.get("status", ""))
        if (
            "Python AST validation failed" in reasoning_text
            or "SyntaxError" in reasoning_text
            or "invalid syntax" in reasoning_text
        ):
            return "syntax_error"
        if stop in {"reasoning_timeout", "budget_exceeded", "no_diff_repair"}:
            return "reasoning_loop_blocked"
        if stop == "max_steps":
            return "max_steps"
        if stop == "ask_user":
            return "ask_user"
        if status == "blocked" or stop == "blocked":
            return "reasoning_loop_blocked"
        files = reasoning_result.get("files_modified") or []
        if "test" in str(reasoning_result.get("goal", "")).lower() and not any("test" in f for f in files):
            return "missing_tests"
    if "SyntaxError" in text or "invalid syntax" in text:
        return "syntax_error"
    if smoke and not smoke.success:
        smoke_text = "\n".join([smoke.output or "", smoke.error or ""]).lower()
        if "bootstrap" in smoke_text or "invalid bootstrap" in smoke_text:
            return "invalid_bootstrap"
        return "infrastructure_bug"
    return "infrastructure_bug"


def _extract_failed_pytest_nodes(text: str) -> List[str]:
    nodes = re.findall(r"FAILED\s+([^\s]+::[^\s]+)", text or "")
    if not nodes:
        nodes = re.findall(r"(tests/[A-Za-z0-9_./-]+\.py)", text or "")
    seen: set[str] = set()
    out: List[str] = []
    for node in nodes:
        key = str(node).strip()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _parse_pytest_collection_error(pytest_output: str) -> Optional[Dict[str, Any]]:
    """Parse pytest output to extract actionable collection error details.

    Returns a dict with error_type and context keys, or None if no known
    collection error is detected.  Supported patterns:

    * ``ImportError: cannot import name 'X' from 'Y'``
    * ``ImportError: cannot import name 'X'``  (no module qualifier)
    * ``ModuleNotFoundError: No module named 'X'``
    * ``AttributeError: module 'X' has no attribute 'Y'``
    * Generic ERROR during collection with no test selected (``no tests ran``)
    """
    if not pytest_output:
        return None

    text = pytest_output

    # Pattern 1: ImportError: cannot import name 'Symbol' from 'module.path'
    m = re.search(
        r"ImportError: cannot import name ['\"]([^'\"]+)['\"] from ['\"]([^'\"]+)['\"]",
        text,
    )
    if m:
        return {
            "error_type": "missing_symbol",
            "missing_symbol": m.group(1),
            "source_module": m.group(2),
        }

    # Pattern 1b: ImportError: cannot import name 'Symbol' (no 'from' clause)
    m = re.search(r"ImportError: cannot import name ['\"]([^'\"]+)['\"]", text)
    if m:
        # Try to infer the module from the collection path
        mod_m = re.search(r"from ([a-zA-Z0-9_.]+) import", text)
        return {
            "error_type": "missing_symbol",
            "missing_symbol": m.group(1),
            "source_module": mod_m.group(1) if mod_m else "",
        }

    # Pattern 2: ModuleNotFoundError: No module named 'X'
    m = re.search(r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]", text)
    if m:
        return {
            "error_type": "missing_module",
            "missing_module": m.group(1),
        }

    # Pattern 3: AttributeError: module 'X' has no attribute 'Y'
    m = re.search(
        r"AttributeError: module ['\"]([^'\"]+)['\"] has no attribute ['\"]([^'\"]+)['\"]",
        text,
    )
    if m:
        return {
            "error_type": "missing_symbol",
            "missing_symbol": m.group(2),
            "source_module": m.group(1),
        }

    # Pattern 4: generic collection error — EEE / no tests ran / ERROR collecting
    if re.search(r"(ERROR collecting|no tests ran|= no tests ran =|EEE)", text):
        # Extract the test file that failed collection
        file_m = re.search(r"ERROR collecting (tests/[^\s]+\.py)", text)
        return {
            "error_type": "collection_error",
            "failing_test_file": file_m.group(1) if file_m else "",
        }

    return None


def _baseline_failure_is_transient(baseline: CommandResult, diagnostics: Optional[CommandResult]) -> bool:
    if baseline.returncode == 124:
        return True
    if diagnostics and diagnostics.returncode == 124:
        return True
    text = "\n".join([
        baseline.output or "",
        baseline.error or "",
        diagnostics.output if diagnostics else "",
        diagnostics.error if diagnostics else "",
    ]).lower()
    transient_markers = (
        "keyboardinterrupt",
        "timed out",
        "timeout",
        "connection reset",
        "connection refused",
        "temporarily unavailable",
        "resource temporarily unavailable",
        "no space left on device",
    )
    return any(marker in text for marker in transient_markers)


def _allow_unrelated_vastai_baseline_failures(
    goal: str,
    baseline: CommandResult,
    diagnostics: Optional[CommandResult],
) -> bool:
    diag_text = "\n".join([diagnostics.output or "", diagnostics.error or ""]) if diagnostics else ""
    failed_nodes = _extract_failed_pytest_nodes(
        "\n".join([baseline.output or "", baseline.error or "", diag_text])
    )
    if not failed_nodes:
        return False
    if any("/test_vastai_" not in node for node in failed_nodes):
        return False
    goal_l = (goal or "").lower()
    goal_is_vastai = any(token in goal_l for token in ("vast", "gpu", "v100", "3090", "4090", "ollama"))
    return not goal_is_vastai


def _baseline_cache_path(project_root: str) -> Path:
    return Path(project_root) / ".igris" / "baseline_cache.json"


# ---------------------------------------------------------------------------
# Issue #626 — Delta baseline: detect pre-existing failures vs new regressions
# ---------------------------------------------------------------------------

def _known_failures_path(project_root: str) -> Path:
    return Path(project_root) / ".igris" / "known_baseline_failures.json"


def _load_known_baseline_failures(project_root: str, main_sha: str) -> Optional[List[str]]:
    """Return the list of test nodes known to fail on *main_sha*, or None if not cached."""
    path = _known_failures_path(project_root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if str(data.get("main_sha", "")).strip() == str(main_sha).strip():
            return list(data.get("failed_nodes", []))
    except Exception:
        pass
    return None


def _save_known_baseline_failures(
    project_root: str, main_sha: str, failed_nodes: List[str]
) -> None:
    """Persist the set of pre-existing failures for *main_sha*."""
    path = _known_failures_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data: Dict[str, Any] = {
        "main_sha": str(main_sha),
        "failed_nodes": list(failed_nodes),
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def _get_main_sha(project_root: str) -> str:
    """Return the current SHA of origin/main (or main if origin/main is absent)."""
    import subprocess as _sp
    for ref in ("origin/main", "main"):
        r = _sp.run(
            ["git", "rev-parse", ref],
            capture_output=True, text=True, cwd=str(project_root),
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return ""


def _diff_vs_main_is_empty(project_root: str, main_sha: str) -> bool:
    """True when HEAD has no diff relative to main (branch == main, no new commits)."""
    import subprocess as _sp
    if not main_sha:
        return False
    r = _sp.run(
        ["git", "diff", "--quiet", main_sha, "HEAD"],
        capture_output=True, cwd=str(project_root),
    )
    return r.returncode == 0


def _delta_baseline_failures(
    branch_failures: List[str], known_failures: List[str]
) -> List[str]:
    """Return failures present in *branch_failures* but NOT in *known_failures*.

    These are genuine regressions introduced by the current branch.
    """
    known_set = set(known_failures)
    return [f for f in branch_failures if f not in known_set]


def _load_valid_baseline_cache(
    project_root: str, head_sha: str, force_revalidate: bool = False
) -> Optional[Dict[str, Any]]:
    """Load a valid baseline cache entry, or return None on miss.

    Issue #730: also sets ``_miss_reason`` on the returned payload (or on a
    dummy dict when returning None) so callers can emit a ``baseline_revalidation``
    event with the reason for the miss.
    """
    ttl = max(60, int(os.getenv("IGRIS_BASELINE_CACHE_SECONDS", "1800")))
    path = _baseline_cache_path(project_root)
    if force_revalidate:
        return None  # caller will emit baseline_revalidation event with reason="force_revalidate"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if str(payload.get("head_sha", "")).strip() != str(head_sha).strip():
        payload["_miss_reason"] = "sha_changed"
        return None
    checked_at = float(payload.get("checked_at", 0.0) or 0.0)
    if checked_at <= 0:
        return None
    if (time.time() - checked_at) > ttl:
        # Issue #730 — cache stale due to age; surface this as a revalidation event
        _stale_age_s = round(time.time() - checked_at, 0)
        payload["_miss_reason"] = "stale"
        payload["_stale_age_s"] = _stale_age_s
        return None
    if not bool(payload.get("baseline_ok", False)):
        return None
    return payload


def _save_baseline_cache(project_root: str, head_sha: str, policy: str = "strict") -> None:
    path = _baseline_cache_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "head_sha": str(head_sha),
        "checked_at": float(time.time()),
        "baseline_ok": True,
        "policy": str(policy),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _baseline_sanity_targets(project_root: str) -> List[str]:
    raw = str(os.getenv("IGRIS_BASELINE_TEST_TARGETS", "")).strip()
    if raw:
        return [t for t in raw.split() if t.strip()]
    defaults = [
        "tests/test_health_readiness.py",
        "tests/test_rank_status.py",
    ]
    root = Path(project_root)
    return [t for t in defaults if (root / t).exists()]


def _has_immediately_dangerous_diff(diff: str) -> bool:
    """Fast pre-test check for diffs that would definitely break the app.

    Only catches two categories that cannot possibly be recovered by the test suite:
      1. Dangerous file tokens (.env, .venv, __pycache__, etc.)
      2. Structural deletions of def create_app or class bodies

    Import-deletion detection is left to _has_destructive_diff (used post-test via
    classify_failure), allowing the test suite to be the primary safety net.
    """
    # Use path-level matching (same logic as _has_destructive_diff) to avoid false
    # positives when ".env" appears in diff content rather than as a changed path.
    _dangerous_exact = {".env"}
    _dangerous_prefix = (".venv/", "__pycache__/", ".pytest_cache/", ".igris/")
    paths = _diff_changed_paths(diff)
    for path in paths:
        if path in _dangerous_exact or any(path.startswith(p) for p in _dangerous_prefix):
            return True
    if paths and all(path.startswith("tests/") for path in paths):
        return False
    python_removed_lines: List[str] = []
    python_added_lines: List[str] = []
    has_diff_headers = "diff --git " in diff
    if not has_diff_headers:
        for line in diff.splitlines():
            if line.startswith("-") and not line.startswith("---"):
                python_removed_lines.append(line)
            elif line.startswith("+") and not line.startswith("+++"):
                python_added_lines.append(line)
    else:
        current_path = ""
        for line in diff.splitlines():
            if line.startswith("diff --git "):
                parts = line.split()
                current_path = parts[3][2:] if len(parts) >= 4 and parts[3].startswith("b/") else ""
                continue
            if not current_path.endswith(".py"):
                continue
            if line.startswith("-") and not line.startswith("---"):
                python_removed_lines.append(line)
            elif line.startswith("+") and not line.startswith("+++"):
                python_added_lines.append(line)
    # Cross-reference: a structural token in a removed line is only dangerous when
    # the same token does NOT appear in any added line (modification vs. deletion).
    structural = ("def create_app", "class ")
    added_text = "\n".join(python_added_lines)
    for line in python_removed_lines:
        for token in structural:
            if token in line and token not in added_text:
                return True
    return False


def _has_destructive_diff(diff: str) -> bool:
    paths = _diff_changed_paths(diff)
    # .env exact match catches the secrets file; prefix match catches venv/cache dirs.
    # Substring matching on the raw diff is intentionally avoided to prevent false
    # positives on safe template files like .env.example.
    _dangerous_exact = {".env"}
    _dangerous_prefix = (".venv/", "__pycache__/", ".pytest_cache/", ".igris/")
    for path in paths:
        if path in _dangerous_exact or any(path.startswith(p) for p in _dangerous_prefix):
            return True
    if paths and all(path.startswith("tests/") for path in paths):
        return False

    python_removed_lines: List[str] = []
    has_diff_headers = "diff --git " in diff
    if not has_diff_headers:
        python_removed_lines = [
            line for line in diff.splitlines()
            if line.startswith("-") and not line.startswith("---")
        ]
    else:
        current_path = ""
        for line in diff.splitlines():
            if line.startswith("diff --git "):
                parts = line.split()
                if len(parts) >= 4:
                    current_path = parts[3][2:] if parts[3].startswith("b/") else parts[3]
                else:
                    current_path = ""
                continue
            if not (current_path.endswith(".py") and line.startswith("-") and not line.startswith("---")):
                continue
            python_removed_lines.append(line)

    # Structural deletions (app factory, class bodies) are always destructive.
    structural = ("def create_app", "class ")
    if any(any(token in line for token in structural) for line in python_removed_lines):
        return True

    # Import deletions: only destructive when an import is truly removed (not
    # reorganised).  Reorganisation removes and re-adds the same names, so the
    # module/symbol appears in an added import line.  We compare against added
    # import lines only (not all added text) to avoid false matches.
    def _extract_import_names(raw: str) -> List[str]:
        tokens = raw.lstrip("-+ \t").split()
        if not tokens:
            return []
        if tokens[0] == "from" and len(tokens) >= 4:
            return [t.rstrip(",") for t in tokens[3:] if t not in ("as", "(", ")")]
        if tokens[0] == "import":
            return [t.rstrip(",").split(".")[0] for t in tokens[1:] if t != "as"]
        return []

    added_import_names: set = set()
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++") and "import " in line:
            for name in _extract_import_names(line):
                added_import_names.add(name)

    import_removed_lines = [l for l in python_removed_lines if "import " in l]
    for removed in import_removed_lines:
        names = _extract_import_names(removed)
        # If NONE of the removed names are re-added, it's a true deletion.
        if names and not any(name in added_import_names for name in names):
            return True

    return False


def _has_invalid_fastapi_bootstrap_diff(diff: str) -> bool:
    paths = _diff_changed_paths(diff)
    if paths and "igris/web/server.py" not in paths:
        return False

    lowered = diff.lower()
    if "return jsonresponse" in lowered and "def create_app" in lowered:
        return True

    ui_card_route = "@app.get('/api/rank/ui-card')" in lowered or '@app.get("/api/rank/ui-card")' in lowered
    if "def run_app" in lowered and ui_card_route:
        return True

    if lowered.count("@app.get('/api/rank/ui-card')") > 1:
        return True
    if lowered.count('@app.get("/api/rank/ui-card")') > 1:
        return True

    bootstrap_routes = ("/api/health", "/api/readiness", "/api/ping")
    if any(route in lowered for route in bootstrap_routes) and "return jsonresponse" in lowered:
        return True

    return False


def _is_missing_test_target_error(result: Optional["CommandResult"]) -> bool:
    if not result:
        return False
    text = "\n".join([result.output or "", result.error or ""]).lower()
    return "file or directory not found" in text and "tests/test_" in text


def _is_llm_provider_unavailable(text: str) -> bool:
    lowered = (text or "").lower()
    return (
        "no suitable llm provider available" in lowered
        or "llm unavailable" in lowered
    )


def _required_endpoint_from_goal(goal: str) -> str:
    match = re.search(r"/api/[a-z0-9_/-]+", goal.lower())
    if not match:
        return ""
    return match.group(0)


def _is_valid_missing_tests_repair_diff(diff: str, goal: str) -> bool:
    paths = _diff_changed_paths(diff)
    if not paths:
        return False
    if not all(path.startswith("tests/") for path in paths):
        return False

    lowered = diff.lower()
    if "test_client(" in lowered:
        return False
    if "testclient(create_app())" not in lowered and "create_app()" not in lowered:
        return False

    required_endpoint = _required_endpoint_from_goal(goal)
    endpoints_found = set(re.findall(r"/api/[a-z0-9_/-]+", lowered))
    if required_endpoint:
        if required_endpoint not in endpoints_found:
            return False
        if any(endpoint != required_endpoint for endpoint in endpoints_found):
            return False
    if "/dashboard" in lowered:
        return False
    return True


def _has_flask_test_client_in_diff(diff: str) -> bool:
    """Return True when the diff *adds* Flask-style ``app.test_client()`` calls.

    FastAPI app objects have no ``test_client()`` method; using it causes
    ``AttributeError`` at pytest collection time (EEE errors).  This helper
    is used during ``pytest_failure`` repair validation to reject such diffs
    early so the repair cycle retries with explicit FastAPI TestClient guidance.
    Only lines that are *added* (starting with '+' but not '+++') are checked.
    """
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            if "test_client(" in line.lower():
                return True
    return False


def _is_valid_ui_test_diff(diff: str) -> bool:
    """Return True when a UI test diff stays minimal and exact.

    The UI rank task should use a read-only test against ``/api/rank/ui-card``.
    We reject diffs that introduce request bodies, alternate verbs, or app
    import patterns that have historically produced unstable bootstrap errors.
    """

    if "tests/test_rank_ui_card.py" not in diff:
        return True

    lowered = diff.lower()
    required_get = (
        'client.get("/api/rank/ui-card")' in lowered
        or "client.get('/api/rank/ui-card')" in lowered
    )
    required_factory = "testclient(create_app())" in lowered or "create_app()" in lowered
    forbidden_tokens = (
        "client.post(",
        "client.put(",
        "client.patch(",
        "client.delete(",
        "client.request(",
        "body(",
        "json=",
        "data=",
        "from igris.web.server import app",
        "response.json()['data']",
        'response.json()["data"]',
        "response.json().get('data')",
        'response.json().get("data")',
        "assert 'data' in response.json()",
        'assert "data" in response.json()',
    )
    if not required_get or not required_factory:
        return False
    return not any(token in lowered for token in forbidden_tokens)


def _diff_changed_paths(diff: str) -> List[str]:
    paths: List[str] = []
    for line in diff.splitlines():
        if not line.startswith("diff --git "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        path = parts[3]
        if path.startswith("b/"):
            path = path[2:]
        paths.append(path)
    return paths


def _diff_sections_by_path(diff: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    current_path = ""
    current_lines: List[str] = []
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            if current_path:
                sections[current_path] = "\n".join(current_lines)
            parts = line.split()
            if len(parts) >= 4:
                current_path = parts[3][2:] if parts[3].startswith("b/") else parts[3]
            else:
                current_path = ""
            current_lines = [line]
            continue
        if current_path:
            current_lines.append(line)
    if current_path:
        sections[current_path] = "\n".join(current_lines)
    return sections


def _changed_paths_between_diffs(before_diff: str, after_diff: str) -> Set[str]:
    before_sections = _diff_sections_by_path(before_diff)
    after_sections = _diff_sections_by_path(after_diff)
    changed: Set[str] = set()
    for path in set(before_sections.keys()).union(after_sections.keys()):
        if before_sections.get(path, "") != after_sections.get(path, ""):
            changed.add(path)
    return changed


def _normalize_candidate_path(path: str) -> str:
    normalized = str(path or "").strip().strip("'\"")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.startswith("a/") or normalized.startswith("b/"):
        normalized = normalized[2:]
    return normalized


def _extract_attempted_write_paths(reasoning_result: Dict[str, Any]) -> List[str]:
    paths: Set[str] = set()
    steps = reasoning_result.get("steps") or []
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            continue
        action_type = str(raw_step.get("action_type", "")).strip()
        if action_type not in WRITE_ACTION_TYPES:
            continue
        params = raw_step.get("parameters") or {}
        if isinstance(params, dict):
            for key in ("path", "file_path", "file", "target_path"):
                candidate = params.get(key)
                if not isinstance(candidate, str):
                    continue
                normalized = _normalize_candidate_path(candidate)
                if normalized:
                    paths.add(normalized)
        for text_key in ("error", "result_summary"):
            text = str(raw_step.get(text_key, "") or "")
            for match in re.findall(r"['\"]([A-Za-z0-9_./-]+\.[A-Za-z0-9_]+)['\"]", text):
                normalized = _normalize_candidate_path(match)
                if normalized and not normalized.startswith(("http://", "https://")):
                    paths.add(normalized)
    for text in [
        str(reasoning_result.get("final_summary", "") or ""),
        str(reasoning_result.get("error", "") or ""),
    ]:
        for match in re.findall(r"['\"]([A-Za-z0-9_./-]+\.[A-Za-z0-9_]+)['\"]", text):
            normalized = _normalize_candidate_path(match)
            if normalized and not normalized.startswith(("http://", "https://")):
                paths.add(normalized)
    for error in reasoning_result.get("errors") or []:
        text = str(error or "")
        for match in re.findall(r"['\"]([A-Za-z0-9_./-]+\.[A-Za-z0-9_]+)['\"]", text):
            normalized = _normalize_candidate_path(match)
            if normalized and not normalized.startswith(("http://", "https://")):
                paths.add(normalized)
    return sorted(paths)


def _is_product_only_ui_task_diff(diff: str) -> bool:
    """Return True when a repair diff only changes UI rank product files."""

    paths = _diff_changed_paths(diff)
    if not paths:
        return False

    product_prefixes = (
        "igris/web/templates/",
        "igris/web/static/js/",
        "igris/web/static/css/",
    )
    product_paths = {
        "igris/web/server.py",
        "tests/test_rank_ui_card.py",
        "tests/test_dashboard_tabs.py",
        "tests/test_guided_actions.py",
    }
    return all(path in product_paths or path.startswith(product_prefixes) for path in paths)


def _has_ui_surface_change(diff: str) -> bool:
    paths = _diff_changed_paths(diff)
    if not paths:
        return False
    ui_prefixes = (
        "igris/web/templates/",
        "igris/web/static/js/",
        "igris/web/static/css/",
    )
    return any(path.startswith(ui_prefixes) for path in paths)


def _touches_rank_ui_contract_files(diff: str) -> bool:
    paths = _diff_changed_paths(diff)
    if not paths:
        return False
    protected = {
        "igris/web/server.py",
        "tests/test_rank_ui_card.py",
    }
    return any(path in protected for path in paths)


def _smoke_output_is_valid(endpoint: str, output: str) -> bool:
    text = output.strip()
    if not text:
        return False
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False

    if endpoint.endswith("/api/health"):
        return payload.get("status") == "ok" and "version" in payload
    if endpoint.endswith("/api/readiness"):
        expected = ("project_root_exists", "project_root_is_dir", "templates", "static", "agents_registered")
        return all(payload.get(key) is True for key in expected)
    if endpoint.endswith("/api/ping"):
        return payload.get("pong") is True
    return True


CORE_FILE_PATTERNS = [
    "igris/core/",
    "igris/web/server.py",
    "igris/web/router_registry.py",
    "igris/core/agent_reasoning_loop.py",
    "igris/core/self_repair_supervisor.py",
    "igris/core/authorization_gate.py",
    "igris/core/identity_resolver.py",
    "igris/core/action_guard.py",
]


def _is_core_file(file_path: str) -> bool:
    """Return True if the file path matches a core file pattern."""
    from pathlib import Path
    p = str(Path(file_path))
    return any(pattern in p for pattern in CORE_FILE_PATTERNS)


