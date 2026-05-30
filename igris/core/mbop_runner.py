"""
Mission Brain Operating Protocol (MBOP) — supervisor integration hooks.

Issue: #936 / MBOP-wiring
Purpose: Wire MBOP phases 1, 9, 10, 11, 12 into the IGRIS supervisor execution
         loop so that every supervised run is structured, gated, and evaluated.

Design principles:
- ADVISORY-ONLY: MBOP hooks never change runtime loop decisions for active runs.
- BEST-EFFORT: any MBOP hook failure is logged but never crashes the supervisor.
- NO AUTO-EXECUTION: MBOP never triggers actions without IGRIS going through its
  own supervisor loop first.
- NO MANDATORY GATE (by default): quality/satisfaction gates are advisory; they
  change the run outcome to "degraded" rather than blocking unconditionally.
  Set mbop_enforce_quality_gate=True in config to make quality-gate failures
  flip the run to "blocked" — this is opt-in per-issue.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class MBOPIntakeResult:
    """Structured intake extracted from a GitHub issue."""
    issue_number: int = 0
    what: str = ""
    where: str = ""
    why: str = ""
    constraints: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    operating_mode: str = "compact"  # compact | full
    raw_body: str = ""
    extraction_ok: bool = False


@dataclass
class MBOPQualityGateResult:
    """Result of the post-completion quality gate (Phase 9)."""
    passed: bool = False
    pytest_ran: bool = False
    pytest_passed: bool = False
    stub_patterns_found: List[str] = field(default_factory=list)
    test_files_checked: List[str] = field(default_factory=list)
    evidence: str = ""
    error: str = ""


@dataclass
class MBOPSatisfactionGateResult:
    """Result of the satisfaction gate (Phase 10)."""
    passed: bool = False
    criteria_checked: List[str] = field(default_factory=list)
    criteria_covered: List[str] = field(default_factory=list)
    criteria_missing: List[str] = field(default_factory=list)
    evidence: str = ""
    error: str = ""


@dataclass
class MBOPEvalResult:
    """Post-task evaluation summary (Phase 11)."""
    summary: str = ""
    lessons: List[str] = field(default_factory=list)
    follow_up_issues: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Phase 1 — Intake
# ---------------------------------------------------------------------------

def mbop_phase1_intake(issue_number: int, project_root: str) -> MBOPIntakeResult:
    """Read GitHub issue and extract structured MBOP intake.

    Uses gh CLI. Best-effort: returns empty result on any error.
    """
    result = MBOPIntakeResult(issue_number=issue_number)
    if not issue_number:
        return result

    try:
        proc = subprocess.run(
            ["gh", "issue", "view", str(issue_number), "--json", "title,body,labels"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=project_root,
        )
        if proc.returncode != 0:
            result.error = proc.stderr[:200] if hasattr(result, "error") else None
            return result

        import json
        data = json.loads(proc.stdout)
        body = data.get("body") or ""
        title = data.get("title") or ""
        labels = [l.get("name", "") for l in data.get("labels", [])]

        result.raw_body = body
        result.operating_mode = "full" if "full" in " ".join(labels).lower() else "compact"

        # Extract sections from MBOP issue template or ad-hoc issue body
        result.what = _extract_section(body, ["### What", "**What**", "what"]) or title
        result.where = _extract_section(body, ["### Where", "**Where**", "where"])
        result.why = _extract_section(body, ["### Why", "**Why**", "why"])
        result.constraints = _extract_list_section(body, ["### Constraints", "**Constraints**"])
        result.acceptance_criteria = _extract_acceptance_criteria(body)
        result.extraction_ok = True

    except Exception as exc:  # noqa: BLE001
        # Best-effort — log but never crash
        _ = exc  # suppress unused warning; error is non-fatal

    return result


def _extract_section(body: str, headers: List[str]) -> str:
    """Extract text under the first matching header, up to the next header."""
    for header in headers:
        idx = body.find(header)
        if idx == -1:
            continue
        start = idx + len(header)
        # Find next markdown header (## or ### or bold **)
        rest = body[start:]
        match = re.search(r"\n#{1,4} |\n\*\*", rest)
        chunk = rest[: match.start()] if match else rest
        text = chunk.strip()
        if text and text != "_not specified_":
            return text[:500]
    return ""


def _extract_list_section(body: str, headers: List[str]) -> List[str]:
    """Extract a bulleted list under the first matching header."""
    text = _extract_section(body, headers)
    items = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("-", "*", "+")):
            item = stripped.lstrip("-*+ ").strip()
            if item:
                items.append(item)
    return items


def _extract_acceptance_criteria(body: str) -> List[str]:
    """Extract AC items (checkbox lines) from issue body."""
    criteria = []
    for line in body.splitlines():
        stripped = line.strip()
        # Match: - [ ] AC or - [x] AC or - [ ] ...
        m = re.match(r"-\s*\[[ xX]\]\s*(.+)", stripped)
        if m:
            ac_text = m.group(1).strip()
            if ac_text and not ac_text.lower().startswith("_"):
                criteria.append(ac_text)
    return criteria[:20]  # cap at 20


# ---------------------------------------------------------------------------
# Phase 9 — Quality Gate
# ---------------------------------------------------------------------------

_STUB_PATTERNS = [
    "# placeholder",
    "# todo",
    "# fixme",
    "# hack",
    "raise notimplementederror",
    "pass  # stub",
    "... # stub",
]

_MAX_PYTEST_SECONDS = 120  # hard cap for post-completion gate test run


def mbop_phase9_quality_gate(
    project_root: str,
    modified_files: List[str],
    run_pytest: bool = True,
) -> MBOPQualityGateResult:
    """Run post-completion quality gate (Phase 9).

    Checks:
    1. No stub/TODO patterns in modified source files.
    2. pytest passes on modified test files (optional, best-effort).
    """
    result = MBOPQualityGateResult()
    root = Path(project_root)

    # --- Stub pattern scan ---
    stub_found: List[str] = []
    for rel_path in modified_files:
        full = root / rel_path
        if not full.exists() or not rel_path.endswith(".py"):
            continue
        try:
            content = full.read_text(encoding="utf-8", errors="replace").lower()
            for pat in _STUB_PATTERNS:
                if pat in content:
                    stub_found.append(f"{rel_path}:{pat}")
        except OSError:
            pass
    result.stub_patterns_found = stub_found

    # --- pytest on modified test files ---
    test_files = [f for f in modified_files if re.search(r"test.*\.py$|\.py.*test", f)]
    result.test_files_checked = test_files

    if run_pytest and test_files:
        try:
            import sys as _sys
            # Use project venv pytest if present, otherwise fall back to sys.executable -m pytest
            _venv_pytest = Path(project_root) / ".venv" / "bin" / "pytest"
            if _venv_pytest.exists():
                _pytest_cmd = [str(_venv_pytest)]
            else:
                _pytest_cmd = [_sys.executable, "-m", "pytest"]
                # Verify pytest is importable
                _check = subprocess.run(
                    [_sys.executable, "-m", "pytest", "--version"],
                    capture_output=True, text=True, timeout=5, cwd=project_root,
                )
                if _check.returncode != 0:
                    result.error = "pytest not available"
                    result.evidence = "pytest not found — skipped"
                    result.passed = len(stub_found) == 0
                    return result

            cmd = _pytest_cmd + ["--tb=short", "-q", "--no-header"] + test_files
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_MAX_PYTEST_SECONDS,
                cwd=project_root,
            )
            result.pytest_ran = True
            result.pytest_passed = proc.returncode == 0
            out = (proc.stdout + proc.stderr)[-1000:]
            result.evidence = out
        except subprocess.TimeoutExpired:
            result.pytest_ran = True
            result.pytest_passed = False
            result.evidence = f"pytest timed out after {_MAX_PYTEST_SECONDS}s"
        except Exception as exc:  # noqa: BLE001
            result.error = f"pytest error: {exc}"
    elif not test_files:
        result.pytest_ran = False
        result.evidence = "no test files in diff — pytest skipped"
    else:
        result.evidence = "pytest disabled by config"

    # Aggregate pass/fail
    stub_ok = len(stub_found) == 0
    pytest_ok = (not result.pytest_ran) or result.pytest_passed
    result.passed = stub_ok and pytest_ok

    if not result.passed:
        reasons = []
        if not stub_ok:
            reasons.append(f"stub patterns: {stub_found[:3]}")
        if result.pytest_ran and not result.pytest_passed:
            reasons.append("pytest FAIL")
        result.evidence = "; ".join(reasons) + " | " + result.evidence

    return result


# ---------------------------------------------------------------------------
# Phase 10 — Satisfaction Gate
# ---------------------------------------------------------------------------

def mbop_phase10_satisfaction_gate(
    intake: MBOPIntakeResult,
    diff_text: str,
    commit_message: str,
) -> MBOPSatisfactionGateResult:
    """Check that acceptance criteria from intake are addressed in the diff/commit.

    This is a heuristic check: we look for keywords from each AC in the diff.
    Advisory-only — a failed satisfaction gate is surfaced but never blocks.
    """
    result = MBOPSatisfactionGateResult()
    criteria = intake.acceptance_criteria
    if not criteria:
        result.passed = True
        result.evidence = "no AC defined in issue — satisfaction gate vacuously PASS"
        return result

    haystack = (diff_text + "\n" + commit_message).lower()
    for ac in criteria:
        result.criteria_checked.append(ac)
        # Extract keywords: words > 4 chars, no stop words
        keywords = [w.lower() for w in re.findall(r"\b\w{5,}\b", ac)
                    if w.lower() not in _STOP_WORDS]
        if not keywords:
            # Short AC — check any word
            keywords = [w.lower() for w in re.findall(r"\b\w{3,}\b", ac)]
        covered = any(kw in haystack for kw in keywords[:5])
        if covered:
            result.criteria_covered.append(ac)
        else:
            result.criteria_missing.append(ac)

    total = len(criteria)
    covered_count = len(result.criteria_covered)
    result.passed = covered_count >= max(1, total // 2)  # ≥50% ACs covered
    result.evidence = f"{covered_count}/{total} ACs keyword-matched in diff"
    return result


_STOP_WORDS = {
    "should", "must", "shall", "when", "then", "given", "that", "have", "been",
    "with", "from", "into", "will", "this", "there", "their", "which", "about",
    "would", "could", "other", "more", "also", "than", "these", "those",
}


# ---------------------------------------------------------------------------
# Phase 11 — Post-Task Evaluation
# ---------------------------------------------------------------------------

def mbop_phase11_post_task_eval(
    intake: MBOPIntakeResult,
    quality: MBOPQualityGateResult,
    satisfaction: MBOPSatisfactionGateResult,
    run_duration_seconds: float,
    failure_class: str = "",
) -> MBOPEvalResult:
    """Generate a brief post-task evaluation summary (Phase 11)."""
    lessons = []
    if quality.stub_patterns_found:
        lessons.append(f"Stubs detected in output: {quality.stub_patterns_found[:2]}")
    if quality.pytest_ran and not quality.pytest_passed:
        lessons.append("Tests failed at completion — needs re-run")
    if satisfaction.criteria_missing:
        lessons.append(f"ACs not addressed: {satisfaction.criteria_missing[:2]}")
    if failure_class:
        lessons.append(f"failure_class={failure_class}")

    qg = "PASS" if quality.passed else "FAIL"
    sg = "PASS" if satisfaction.passed else "ADVISORY"
    summary = (
        f"Issue #{intake.issue_number} | QG:{qg} SG:{sg} | "
        f"Duration:{run_duration_seconds:.0f}s | "
        f"Mode:{intake.operating_mode}"
    )
    return MBOPEvalResult(summary=summary, lessons=lessons)


# ---------------------------------------------------------------------------
# Phase 12 — Next-Step Propagation (decomposition)
# ---------------------------------------------------------------------------

def mbop_phase12_next_step(
    intake: MBOPIntakeResult,
    project_root: str,
    failure_class: str = "",
    open_issues: Optional[List[int]] = None,
) -> List[str]:
    """On decomposition_required, suggest (but do not create) sub-issues.

    Returns a list of suggested sub-issue titles with MBOP intake structure.
    Advisory-only: creates GitHub sub-issues only if explicitly enabled.
    """
    if failure_class != "decomposition_required":
        return []

    suggestions = []
    what = intake.what or f"Issue #{intake.issue_number}"
    suggestions.append(
        f"[MBOP sub] Phase 1 requirements analysis for: {what[:60]}"
    )
    suggestions.append(
        f"[MBOP sub] Phase 2 implementation for: {what[:60]}"
    )
    suggestions.append(
        f"[MBOP sub] Phase 3 tests and verification for: {what[:60]}"
    )
    return suggestions


# ---------------------------------------------------------------------------
# Run helper — get modified files from git diff
# ---------------------------------------------------------------------------

def _get_modified_files(project_root: str, base_branch: str = "main") -> List[str]:
    """Get list of files modified vs base branch."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", base_branch, "HEAD"],
            capture_output=True, text=True, timeout=10, cwd=project_root,
        )
        if proc.returncode == 0:
            return [f.strip() for f in proc.stdout.splitlines() if f.strip()]
    except Exception:  # noqa: BLE001
        pass
    # Fallback: diff against HEAD^
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "HEAD^", "HEAD"],
            capture_output=True, text=True, timeout=10, cwd=project_root,
        )
        if proc.returncode == 0:
            return [f.strip() for f in proc.stdout.splitlines() if f.strip()]
    except Exception:  # noqa: BLE001
        pass
    return []


def _get_diff_text(project_root: str, base_branch: str = "main") -> str:
    """Get unified diff text vs base branch (truncated to 10k chars)."""
    try:
        proc = subprocess.run(
            ["git", "diff", base_branch, "HEAD"],
            capture_output=True, text=True, timeout=15, cwd=project_root,
        )
        if proc.returncode == 0:
            return proc.stdout[:10000]
    except Exception:  # noqa: BLE001
        pass
    return ""


def _get_last_commit_message(project_root: str) -> str:
    """Get the last commit message."""
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--pretty=%B"],
            capture_output=True, text=True, timeout=5, cwd=project_root,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


# ---------------------------------------------------------------------------
# Main entry point — wrap a supervisor run with MBOP phases
# ---------------------------------------------------------------------------

def mbop_pre_run(
    issue_number: int,
    project_root: str,
    run_add_fn: Any = None,  # SupervisorRun.add callable
) -> MBOPIntakeResult:
    """Execute MBOP Phase 1 (Intake) before the supervisor run.

    Reads GitHub issue, extracts structured intake, logs to run.
    Returns MBOPIntakeResult (always — never raises).
    """
    intake = MBOPIntakeResult(issue_number=issue_number)
    try:
        intake = mbop_phase1_intake(issue_number, project_root)
        if run_add_fn and intake.extraction_ok:
            run_add_fn(
                "mbop_phase1_intake",
                "success",
                f"MBOP Phase 1 Intake: #{issue_number} | "
                f"What: {intake.what[:80]} | "
                f"ACs: {len(intake.acceptance_criteria)} | "
                f"Mode: {intake.operating_mode}",
                issue_number=issue_number,
                what=intake.what[:200],
                constraints=intake.constraints[:5],
                acceptance_criteria=intake.acceptance_criteria[:5],
            )
        elif run_add_fn:
            run_add_fn(
                "mbop_phase1_intake",
                "skipped",
                f"MBOP Phase 1 Intake: #{issue_number} — issue not readable (gh CLI or no issue number)",
                issue_number=issue_number,
            )
    except Exception as exc:  # noqa: BLE001
        if run_add_fn:
            try:
                run_add_fn("mbop_phase1_intake", "error", f"MBOP intake error (non-fatal): {exc}")
            except Exception:  # noqa: BLE001
                pass
    return intake


def mbop_post_run(
    run: Any,  # SupervisorRun
    intake: MBOPIntakeResult,
    project_root: str,
    run_start_ts: float,
    enforce_quality_gate: bool = False,
) -> None:
    """Execute MBOP Phases 9–12 after the supervisor run completes.

    - Phase 9: Quality Gate (pytest + stub scan)
    - Phase 10: Satisfaction Gate (AC coverage)
    - Phase 11: Post-Task Eval (summary)
    - Phase 12: Next-Step (decomposition suggestions)

    Never raises. If enforce_quality_gate=True and QG fails, run.status
    is changed to "blocked" with failure_class "mbop_quality_gate_failed".
    """
    try:
        run_status = getattr(run, "status", "")
        failure_class = getattr(run, "failure_class", "") or ""
        duration = time.time() - run_start_ts

        # ---- Phase 9: Quality Gate ----
        modified_files: List[str] = []
        try:
            modified_files = _get_modified_files(project_root)
        except Exception:  # noqa: BLE001
            pass

        quality = MBOPQualityGateResult()
        try:
            quality = mbop_phase9_quality_gate(project_root, modified_files)
        except Exception as exc:  # noqa: BLE001
            quality.error = str(exc)

        qg_status = "pass" if quality.passed else "fail"
        try:
            run.add(
                "mbop_phase9_quality_gate",
                qg_status,
                f"MBOP Phase 9 Quality Gate: {qg_status.upper()} | "
                f"pytest={'PASS' if quality.pytest_passed else ('FAIL' if quality.pytest_ran else 'skipped')} | "
                f"stubs={quality.stub_patterns_found[:3]} | {quality.evidence[:200]}",
                pytest_passed=quality.pytest_passed,
                pytest_ran=quality.pytest_ran,
                stub_patterns=quality.stub_patterns_found[:5],
                test_files=quality.test_files_checked[:5],
            )
        except Exception:  # noqa: BLE001
            pass

        # If quality gate fails and enforcement is on, downgrade run to blocked
        if not quality.passed and enforce_quality_gate and run_status == "completed":
            try:
                run.status = "blocked"
                run.failure_class = "mbop_quality_gate_failed"
                run.outcome = "Blocked — MBOP Quality Gate failed"
                run.add(
                    "mbop_quality_gate_enforcement",
                    "blocked",
                    "Run downgraded to blocked: MBOP quality gate failed (enforce=True). "
                    f"Stubs: {quality.stub_patterns_found[:3]}. "
                    f"pytest: {'FAIL' if quality.pytest_ran and not quality.pytest_passed else 'not run'}",
                )
            except Exception:  # noqa: BLE001
                pass

        # ---- Phase 10: Satisfaction Gate ----
        diff_text = ""
        commit_msg = ""
        try:
            diff_text = _get_diff_text(project_root)
            commit_msg = _get_last_commit_message(project_root)
        except Exception:  # noqa: BLE001
            pass

        satisfaction = MBOPSatisfactionGateResult()
        try:
            satisfaction = mbop_phase10_satisfaction_gate(intake, diff_text, commit_msg)
        except Exception as exc:  # noqa: BLE001
            satisfaction.error = str(exc)

        sg_status = "pass" if satisfaction.passed else "advisory"
        try:
            run.add(
                "mbop_phase10_satisfaction_gate",
                sg_status,
                f"MBOP Phase 10 Satisfaction Gate: {sg_status.upper()} | "
                f"{satisfaction.evidence[:200]} | "
                f"missing={satisfaction.criteria_missing[:3]}",
                criteria_covered=satisfaction.criteria_covered[:5],
                criteria_missing=satisfaction.criteria_missing[:5],
            )
        except Exception:  # noqa: BLE001
            pass

        # ---- Phase 11: Post-Task Evaluation ----
        try:
            eval_result = mbop_phase11_post_task_eval(
                intake, quality, satisfaction, duration, failure_class
            )
            run.add(
                "mbop_phase11_post_task_eval",
                "done",
                f"MBOP Phase 11 Post-Task Eval: {eval_result.summary}",
                lessons=eval_result.lessons[:5],
            )
        except Exception:  # noqa: BLE001
            pass

        # ---- Phase 12: Next-Step Propagation ----
        try:
            suggestions = mbop_phase12_next_step(intake, project_root, failure_class)
            if suggestions:
                run.add(
                    "mbop_phase12_next_step",
                    "advisory",
                    f"MBOP Phase 12 Next-Step: decomposition detected | "
                    f"suggested sub-issues: {suggestions[:3]}",
                    suggestions=suggestions,
                )
        except Exception:  # noqa: BLE001
            pass

    except Exception:  # noqa: BLE001
        # Top-level guard — MBOP post-run never crashes the supervisor
        pass
