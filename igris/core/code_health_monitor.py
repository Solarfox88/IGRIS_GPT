"""CodeHealthMonitor — proactive code quality analysis for IGRIS.

Part of GitHub issue #521: feat(watchdog): Code health monitor.
Fase 2bis — Gap 4.

Runs every 10 SMW cycles and detects:
1. Coverage drops     — module coverage drops >5% vs last run
2. TODO/FIXME age     — TODO/FIXME tokens present for >30 days (via git log)
3. Coverage gaps      — modules with <40% coverage and no open proactive issue
4. Complexity growth  — files exceeding 500 LOC or growing >20% in last 30 days

Anti-spam: each finding category is keyed by (category, module_path).
A new GitHub issue is opened only when no open `igris-proactive` issue
already exists for that key.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class HealthFinding:
    category: str          # "coverage_drop" | "todo_age" | "coverage_gap" | "complexity_growth"
    module_path: str       # relative path, e.g. "igris/core/foo.py"
    title: str
    body: str
    severity: str = "medium"   # "low" | "medium" | "high"


@dataclass
class CodeHealthReport:
    findings: List[HealthFinding] = field(default_factory=list)
    issues_opened: List[str] = field(default_factory=list)   # gh issue URLs
    issues_skipped: int = 0    # anti-spam suppressed
    errors: List[str] = field(default_factory=list)
    ran_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Coverage helpers
# ---------------------------------------------------------------------------

_COVERAGE_HISTORY_FILE = ".igris/coverage_history.json"
_COVERAGE_THRESHOLD = 40.0   # below this → coverage gap issue
_COVERAGE_DROP_THRESHOLD = 5.0  # more than this % drop → issue


def _run_coverage_json(project_root: str) -> Optional[Dict[str, Any]]:
    """Run pytest --cov and return the JSON coverage report, or None on failure."""
    out = subprocess.run(
        [
            "python", "-m", "pytest", "--cov=igris", "--cov-report=json",
            "--cov-report=term-missing:skip-covered",
            "-q", "--tb=no", "-m", "not slow", "--no-header",
        ],
        capture_output=True, text=True, cwd=project_root, timeout=300,
    )
    json_path = Path(project_root) / "coverage.json"
    if json_path.exists():
        try:
            return json.loads(json_path.read_text())
        except Exception:
            pass
    return None


def _load_coverage_history(project_root: str) -> Dict[str, float]:
    path = Path(project_root) / _COVERAGE_HISTORY_FILE
    if not path.exists():
        return {}
    try:
        return dict(json.loads(path.read_text()))
    except Exception:
        return {}


def _save_coverage_history(project_root: str, data: Dict[str, float]) -> None:
    path = Path(project_root) / _COVERAGE_HISTORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _parse_coverage_json(cov_data: Dict[str, Any]) -> Dict[str, float]:
    """Return {relative_path: coverage_pct} from coverage.json format."""
    result: Dict[str, float] = {}
    files = cov_data.get("files", {})
    for fpath, fdata in files.items():
        summary = fdata.get("summary", {})
        pct = float(summary.get("percent_covered", 0.0))
        result[fpath] = pct
    return result


def _detect_coverage_drops(
    current: Dict[str, float],
    history: Dict[str, float],
) -> List[HealthFinding]:
    findings = []
    for path, pct in current.items():
        prev = history.get(path)
        if prev is None:
            continue
        drop = prev - pct
        if drop > _COVERAGE_DROP_THRESHOLD:
            findings.append(HealthFinding(
                category="coverage_drop",
                module_path=path,
                title=f"health(coverage): coverage drop {drop:.1f}% on {Path(path).name}",
                body=(
                    f"## Coverage drop detected\n\n"
                    f"**Module:** `{path}`\n"
                    f"**Previous:** {prev:.1f}%\n"
                    f"**Current:** {pct:.1f}%\n"
                    f"**Drop:** {drop:.1f}% (threshold: {_COVERAGE_DROP_THRESHOLD}%)\n\n"
                    f"This may indicate that new code was added without tests, or existing "
                    f"tests were removed.\n\n"
                    f"*Opened by IGRIS CodeHealthMonitor (issue #521)*"
                ),
                severity="high" if drop > 15 else "medium",
            ))
    return findings


def _detect_coverage_gaps(current: Dict[str, float]) -> List[HealthFinding]:
    findings = []
    for path, pct in current.items():
        if pct < _COVERAGE_THRESHOLD:
            findings.append(HealthFinding(
                category="coverage_gap",
                module_path=path,
                title=f"health(coverage): low coverage {pct:.0f}% on {Path(path).name}",
                body=(
                    f"## Low test coverage\n\n"
                    f"**Module:** `{path}`\n"
                    f"**Coverage:** {pct:.1f}% (threshold: {_COVERAGE_THRESHOLD}%)\n\n"
                    f"Consider adding tests to bring coverage above {_COVERAGE_THRESHOLD}%.\n\n"
                    f"*Opened by IGRIS CodeHealthMonitor (issue #521)*"
                ),
                severity="low",
            ))
    return findings


# ---------------------------------------------------------------------------
# TODO/FIXME age scanner
# ---------------------------------------------------------------------------

_TODO_PATTERN = re.compile(r"#\s*(TODO|FIXME)\b", re.IGNORECASE)
_TODO_MAX_AGE_DAYS = 30


def _git_blame_first_line_date(project_root: str, filepath: str, lineno: int) -> Optional[float]:
    """Return Unix timestamp when lineno was last introduced (git log -S approach)."""
    try:
        result = subprocess.run(
            ["git", "log", "--follow", "--diff-filter=A", "--format=%ct",
             "-1", f"-L{lineno},{lineno}:{filepath}"],
            capture_output=True, text=True, cwd=project_root, timeout=10,
        )
        lines = (result.stdout or "").strip().splitlines()
        for line in lines:
            line = line.strip()
            if line.isdigit():
                return float(line)
    except Exception:
        pass
    return None


def _detect_old_todos(project_root: str) -> List[HealthFinding]:
    """Find TODO/FIXME comments older than _TODO_MAX_AGE_DAYS days."""
    findings: List[HealthFinding] = []
    root = Path(project_root)
    cutoff = time.time() - _TODO_MAX_AGE_DAYS * 86400
    seen_files: set = set()

    py_files = list(root.glob("igris/**/*.py")) + list(root.glob("tests/**/*.py"))
    for pyfile in py_files[:200]:  # cap to avoid excessive git calls
        try:
            text = pyfile.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(pyfile.relative_to(root))
        for lineno, line in enumerate(text.splitlines(), 1):
            if _TODO_PATTERN.search(line):
                ts = _git_blame_first_line_date(project_root, rel, lineno)
                if ts and ts < cutoff and rel not in seen_files:
                    seen_files.add(rel)
                    age_days = int((time.time() - ts) / 86400)
                    findings.append(HealthFinding(
                        category="todo_age",
                        module_path=rel,
                        title=f"health(todo): stale TODO/FIXME (>{age_days}d) in {Path(rel).name}",
                        body=(
                            f"## Stale TODO/FIXME\n\n"
                            f"**File:** `{rel}` line {lineno}\n"
                            f"**Age:** ~{age_days} days\n"
                            f"**Content:** `{line.strip()[:120]}`\n\n"
                            f"TODOs older than {_TODO_MAX_AGE_DAYS} days should be resolved "
                            f"or converted to a tracked issue.\n\n"
                            f"*Opened by IGRIS CodeHealthMonitor (issue #521)*"
                        ),
                        severity="low",
                    ))
    return findings


# ---------------------------------------------------------------------------
# Complexity growth detector
# ---------------------------------------------------------------------------

_LOC_THRESHOLD = 500
_LOC_GROWTH_PCT = 20.0
_COMPLEXITY_HISTORY_FILE = ".igris/loc_history.json"


def _count_loc(filepath: Path) -> int:
    try:
        return len(filepath.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return 0


def _load_loc_history(project_root: str) -> Dict[str, int]:
    path = Path(project_root) / _COMPLEXITY_HISTORY_FILE
    if not path.exists():
        return {}
    try:
        return dict(json.loads(path.read_text()))
    except Exception:
        return {}


def _save_loc_history(project_root: str, data: Dict[str, int]) -> None:
    path = Path(project_root) / _COMPLEXITY_HISTORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _detect_complexity_growth(project_root: str) -> Tuple[List[HealthFinding], Dict[str, int]]:
    findings: List[HealthFinding] = []
    root = Path(project_root)
    history = _load_loc_history(project_root)
    current: Dict[str, int] = {}

    for pyfile in root.glob("igris/**/*.py"):
        rel = str(pyfile.relative_to(root))
        loc = _count_loc(pyfile)
        current[rel] = loc
        prev = history.get(rel)

        if loc >= _LOC_THRESHOLD and (prev is None or prev < _LOC_THRESHOLD):
            findings.append(HealthFinding(
                category="complexity_growth",
                module_path=rel,
                title=f"health(complexity): {Path(rel).name} exceeded {_LOC_THRESHOLD} LOC ({loc} lines)",
                body=(
                    f"## File exceeded complexity threshold\n\n"
                    f"**File:** `{rel}`\n"
                    f"**LOC:** {loc} (threshold: {_LOC_THRESHOLD})\n\n"
                    f"Consider splitting this module to reduce cognitive load and improve testability.\n\n"
                    f"*Opened by IGRIS CodeHealthMonitor (issue #521)*"
                ),
                severity="medium",
            ))
        elif prev and prev > 0:
            growth_pct = (loc - prev) / prev * 100
            if growth_pct > _LOC_GROWTH_PCT and loc > 100:
                findings.append(HealthFinding(
                    category="complexity_growth",
                    module_path=rel,
                    title=f"health(complexity): {Path(rel).name} grew {growth_pct:.0f}% ({prev}→{loc} LOC)",
                    body=(
                        f"## Rapid file growth detected\n\n"
                        f"**File:** `{rel}`\n"
                        f"**Previous LOC:** {prev}\n"
                        f"**Current LOC:** {loc}\n"
                        f"**Growth:** {growth_pct:.1f}% (threshold: {_LOC_GROWTH_PCT}%)\n\n"
                        f"*Opened by IGRIS CodeHealthMonitor (issue #521)*"
                    ),
                    severity="low",
                ))

    return findings, current


# ---------------------------------------------------------------------------
# Anti-spam: check for existing open proactive issues
# ---------------------------------------------------------------------------

def _load_open_proactive_issues(project_root: str) -> List[Dict[str, str]]:
    """Return list of open issues with label igris-proactive."""
    try:
        result = subprocess.run(
            ["gh", "issue", "list", "--state", "open", "--label", "igris-proactive",
             "--json", "number,title", "--limit", "200"],
            capture_output=True, text=True, cwd=project_root, timeout=15,
        )
        if result.returncode == 0:
            return list(json.loads(result.stdout or "[]"))
    except Exception:
        pass
    return []


def _issue_already_open(
    open_issues: List[Dict[str, str]],
    category: str,
    module_path: str,
) -> bool:
    """True if an open proactive issue for this (category, module) already exists."""
    module_name = Path(module_path).name
    cat_prefix = category.split("_")[0]  # "coverage" | "todo" | "complexity"
    for issue in open_issues:
        title = issue.get("title", "").lower()
        if cat_prefix in title and module_name.lower() in title:
            return True
    return False


# ---------------------------------------------------------------------------
# Issue opener
# ---------------------------------------------------------------------------

def _open_github_issue(project_root: str, finding: HealthFinding) -> Optional[str]:
    """Open a GitHub issue for the finding. Returns URL or None on failure."""
    try:
        result = subprocess.run(
            [
                "gh", "issue", "create",
                "--title", finding.title,
                "--body", finding.body,
                "--label", "igris-proactive,health,created-by:igris",
            ],
            capture_output=True, text=True, cwd=project_root, timeout=20,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

class CodeHealthMonitor:
    """Proactive code quality monitor for IGRIS.

    Usage (from SMW cycle, every 10 iterations)::

        monitor = CodeHealthMonitor(project_root)
        report = monitor.run()
    """

    def __init__(self, project_root: str, dry_run: bool = False) -> None:
        self._root = project_root
        self._dry_run = dry_run

    def run(self, run_coverage: bool = False) -> CodeHealthReport:
        """Execute all health checks and open issues for new findings.

        Parameters
        ----------
        run_coverage:
            If True, re-runs pytest --cov to generate fresh coverage data.
            Expensive (~5 min). Set to False in normal SMW cycles; True for
            dedicated health runs.
        """
        report = CodeHealthReport()
        all_findings: List[HealthFinding] = []

        # --- Coverage analysis ---
        try:
            cov_data: Optional[Dict[str, Any]] = None
            if run_coverage:
                cov_data = _run_coverage_json(self._root)
            else:
                json_path = Path(self._root) / "coverage.json"
                if json_path.exists():
                    try:
                        cov_data = json.loads(json_path.read_text())
                    except Exception:
                        pass

            if cov_data:
                current_cov = _parse_coverage_json(cov_data)
                history_cov = _load_coverage_history(self._root)
                all_findings.extend(_detect_coverage_drops(current_cov, history_cov))
                all_findings.extend(_detect_coverage_gaps(current_cov))
                _save_coverage_history(self._root, current_cov)
        except Exception as exc:
            report.errors.append(f"coverage analysis: {exc}")

        # --- TODO/FIXME age ---
        try:
            all_findings.extend(_detect_old_todos(self._root))
        except Exception as exc:
            report.errors.append(f"todo scanner: {exc}")

        # --- Complexity growth ---
        try:
            complexity_findings, new_loc = _detect_complexity_growth(self._root)
            all_findings.extend(complexity_findings)
            _save_loc_history(self._root, new_loc)
        except Exception as exc:
            report.errors.append(f"complexity analysis: {exc}")

        # --- Anti-spam + issue opening ---
        try:
            open_issues = _load_open_proactive_issues(self._root)
        except Exception:
            open_issues = []

        for finding in all_findings:
            if _issue_already_open(open_issues, finding.category, finding.module_path):
                report.issues_skipped += 1
                continue
            if not self._dry_run:
                url = _open_github_issue(self._root, finding)
                if url:
                    report.issues_opened.append(url)
            report.findings.append(finding)

        return report
