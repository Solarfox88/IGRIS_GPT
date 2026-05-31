"""Pre-commit safety gate — PR 1 DeliveryWorkflow hardening.

Scans files staged for commit / in a diff for:
  - Secrets and credentials (regex patterns)
  - Runtime artifacts (.env, .venv, __pycache__, .pytest_cache, etc.)
  - IGRIS internal runtime files (.igris/locks, .igris/runs, logs)
  - Private keys and certificate files
  - Scope violations (files outside allowed_scopes)

Usage:
    gate = CommitSafetyGate(project_root="/repo")
    report = gate.scan(changed_files=["src/foo.py", ".env"])
    if not report.ok:
        raise RuntimeError(report.summary)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Files that must NEVER be committed
_BLOCKED_FILENAMES: frozenset = frozenset({
    ".env", ".env.local", ".env.production", ".env.staging",
    ".env.test", ".envrc",
    "credentials.json", "credentials.yml", "credentials.yaml",
    "secrets.json", "secrets.yml", "secrets.yaml",
    ".netrc",
})

_BLOCKED_EXTENSIONS: frozenset = frozenset({
    ".pem", ".key", ".p12", ".pfx", ".cer", ".crt",
    ".ppk",  # PuTTY private key
})

# Path prefixes that must NOT appear in commits
_BLOCKED_PATH_PREFIXES = (
    ".venv/", "venv/", ".tox/", ".eggs/",
    "__pycache__/", ".pytest_cache/", ".mypy_cache/",
    ".ruff_cache/", ".hypothesis/",
    "igris_gpt.egg-info/", "*.egg-info/",
    ".igris/locks/", ".igris/runs/", ".igris/supervisor_runs",
    "logs/", "tmp/", ".tmp/",
    "node_modules/",
)

# Regex patterns that indicate secret-like content in file PATHS
_SECRET_PATH_RE = re.compile(
    r"(?i)(id_rsa|id_ecdsa|id_ed25519|id_dsa|\.pem|\.key|_private|secret|credential)",
)

# Regex patterns inside file CONTENT (used when scanning diff hunks)
_SECRET_CONTENT_RE = re.compile(
    r"(?i)(api[_-]?key|api[_-]?secret|access[_-]?token|private[_-]?key|"
    r"password|passwd|auth[_-]?token|bearer\s+[a-z0-9]{10,}|"
    r"aws[_-]?(access|secret)|ghp_[a-z0-9]{36}|sk-[a-z0-9]{32,})\s*[=:]\s*\S+",
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class FileRisk:
    """Risk assessment for a single file."""
    path: str
    blocked: bool
    reasons: List[str] = field(default_factory=list)


@dataclass
class SafetyReport:
    """Result of a pre-commit safety scan."""
    ok: bool
    blocked_files: List[FileRisk] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    scope_violations: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.ok:
            return "pre-commit safety gate: PASSED"
        lines = ["pre-commit safety gate: BLOCKED"]
        for fr in self.blocked_files:
            lines.append(f"  BLOCKED {fr.path}: {'; '.join(fr.reasons)}")
        for v in self.scope_violations:
            lines.append(f"  SCOPE VIOLATION: {v}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Diff scope result
# ---------------------------------------------------------------------------

@dataclass
class DiffScopeResult:
    """Result of validate_diff_scope()."""
    ok: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    file_count: int = 0

    @property
    def summary(self) -> str:
        if self.ok:
            return f"diff scope: ok ({self.file_count} file(s))"
        return "diff scope: VIOLATIONS\n" + "\n".join(f"  {v}" for v in self.violations)


# ---------------------------------------------------------------------------
# Main gate
# ---------------------------------------------------------------------------

class CommitSafetyGate:
    """Scans a list of file paths for pre-commit safety issues.

    Checks:
    1. Blocked filenames (.env, credentials.json, private keys)
    2. Blocked extensions (.pem, .key, .p12)
    3. Runtime artifacts (.venv, __pycache__, .pytest_cache, .igris/locks)
    4. Secret-like path segments (id_rsa, _private, etc.)
    5. Scope violations (files outside allowed_scopes, if provided)
    """

    def __init__(self, project_root: str) -> None:
        self.project_root = Path(project_root)

    def scan(
        self,
        changed_files: List[str],
        allowed_scopes: Optional[List[str]] = None,
    ) -> SafetyReport:
        """Scan *changed_files* and return a SafetyReport.

        Args:
            changed_files: file paths relative to project root (or absolute)
            allowed_scopes: if provided, files outside these prefixes are flagged
                            as scope violations (warning, not block by default)

        Returns:
            SafetyReport with ok=True only if no blocked files found.
        """
        blocked: List[FileRisk] = []
        warnings: List[str] = []
        scope_violations: List[str] = []

        for raw_path in changed_files:
            path = raw_path.strip()
            norm = Path(path).as_posix()
            name = Path(path).name
            ext = Path(path).suffix.lower()

            reasons: List[str] = []

            # 1. Blocked filename
            if name in _BLOCKED_FILENAMES:
                reasons.append(f"blocked filename: {name}")

            # 2. Blocked extension
            if ext in _BLOCKED_EXTENSIONS:
                reasons.append(f"blocked extension: {ext}")

            # 3. Runtime artifact path prefix
            for prefix in _BLOCKED_PATH_PREFIXES:
                clean_prefix = prefix.rstrip("*").rstrip("/") + "/"
                # Match at path start OR anywhere inside (e.g. igris/core/__pycache__/...)
                if (norm.startswith(clean_prefix)
                        or norm.startswith("." + clean_prefix)
                        or ("/" + clean_prefix) in norm):
                    reasons.append(f"runtime artifact: {prefix}")
                    break

            # 4. Secret-like path segment
            if _SECRET_PATH_RE.search(norm) and not reasons:
                reasons.append(f"secret-like path: {norm}")

            # 5. Hidden files that look dangerous
            if name.startswith(".") and name not in {".gitignore", ".gitattributes",
                                                       ".github", ".flake8",
                                                       ".pre-commit-config.yaml",
                                                       ".ruff.toml"}:
                if ext in (".env", ".secret", ".key", ".pem") or name in _BLOCKED_FILENAMES:
                    if not any("blocked" in r for r in reasons):
                        reasons.append(f"hidden potentially-sensitive file: {name}")

            if reasons:
                blocked.append(FileRisk(path=path, blocked=True, reasons=reasons))
            elif allowed_scopes is not None:
                # Scope check — warn if file outside allowed scopes
                in_scope = any(norm.startswith(s.rstrip("/") + "/") or norm == s
                               for s in allowed_scopes)
                if not in_scope:
                    scope_violations.append(
                        f"{path} is outside allowed scopes: {allowed_scopes[:3]}"
                    )

        ok = len(blocked) == 0
        return SafetyReport(
            ok=ok,
            blocked_files=blocked,
            warnings=warnings,
            scope_violations=scope_violations,
        )

    def scan_diff_content(self, diff_text: str) -> List[str]:
        """Scan a diff text for secret-like content in added lines (+).

        Returns a list of warning messages for suspicious lines.
        """
        warnings: List[str] = []
        for i, line in enumerate(diff_text.splitlines(), 1):
            if not line.startswith("+") or line.startswith("+++"):
                continue
            content = line[1:]  # strip leading +
            m = _SECRET_CONTENT_RE.search(content)
            if m:
                warnings.append(
                    f"line {i}: possible secret in added line — "
                    f"pattern '{m.group(0)[:40]}...'"
                )
        return warnings


# ---------------------------------------------------------------------------
# Diff scope validator
# ---------------------------------------------------------------------------

def validate_diff_scope(
    changed_files: List[str],
    allowed_scopes: Optional[List[str]],
    issue_goal: str = "",
    max_files: int = 50,
) -> DiffScopeResult:
    """Validate that the changed files are within allowed scope.

    Checks:
    1. File count (warn if > max_files)
    2. Each file must match at least one allowed_scope prefix (if scopes given)
    3. No .env / secrets (hard block)
    4. No .venv / __pycache__ runtime artifacts
    5. No CI/workflow changes if goal doesn't mention CI

    Args:
        changed_files: list of relative file paths
        allowed_scopes: list of path prefixes that are in scope (None = no check)
        issue_goal: original mission goal string for context
        max_files: warn if more files than this are changed

    Returns:
        DiffScopeResult with ok=True when no hard violations found.
    """
    violations: List[str] = []
    warnings: List[str] = []

    if not changed_files:
        return DiffScopeResult(ok=True, file_count=0)

    # 1. File count
    count = len(changed_files)
    if count > max_files:
        violations.append(
            f"too many files changed: {count} > max_files={max_files}"
        )
    elif count > max(max_files // 2, 10):
        warnings.append(f"large diff: {count} files changed")

    # 2. Blocked files (secrets/artifacts)
    gate = CommitSafetyGate(project_root=".")
    safety = gate.scan(changed_files)
    for fr in safety.blocked_files:
        violations.append(f"blocked file in diff: {fr.path} ({'; '.join(fr.reasons)})")

    # 3. Scope check
    if allowed_scopes:
        for raw_path in changed_files:
            norm = Path(raw_path.strip()).as_posix()
            in_scope = any(
                norm.startswith(s.rstrip("/") + "/") or norm == s
                for s in allowed_scopes
            )
            if not in_scope:
                violations.append(
                    f"out-of-scope file: {raw_path} (allowed: {allowed_scopes[:3]})"
                )

    # 4. CI workflow changes — warn unless goal mentions CI
    goal_lower = issue_goal.lower()
    ci_mentions = ("ci", "workflow", ".github", "github actions", "pipeline")
    for path in changed_files:
        norm = Path(path.strip()).as_posix()
        if ".github/workflows/" in norm or norm.startswith(".github/"):
            if not any(kw in goal_lower for kw in ci_mentions):
                warnings.append(
                    f"CI/workflow file modified without CI in goal: {path}"
                )

    ok = len(violations) == 0
    return DiffScopeResult(
        ok=ok,
        violations=violations,
        warnings=warnings,
        file_count=count,
    )
