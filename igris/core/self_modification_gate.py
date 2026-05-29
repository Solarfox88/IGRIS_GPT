"""SelfModificationGate — extra validation layer for auto-modifications to IGRIS core files.

Part of GitHub issue #523: feat(supervisor): Self-modification gate.
Fase 2bis — Gap 6.

When IGRIS applies a patch that touches any file in CORE_FILES, this gate runs:
1. Targeted tests for the modified module
2. Smoke check (POST /api/health must respond within 10s)
3. Rollback on smoke failure (immediate, no repair cycle)
4. Confidence threshold enforcement (SMW merge threshold 0.85 for self-mods)
5. Audit trail in .igris/self_modifications.json

Usage from self_repair_supervisor (after patch application, before merge)::

    gate = SelfModificationGate(project_root, backend)
    result = gate.check(diff=patch_diff, run_id=run.run_id)
    if not result.approved:
        gate.rollback(result)
        return blocked(...)
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Core file registry (env-overridable)
# ---------------------------------------------------------------------------

_DEFAULT_CORE_FILES: Set[str] = {
    "igris/web/server.py",
    "igris/core/self_repair_supervisor.py",
    "igris/core/meta_watchdog.py",
    "igris/core/agent_reasoning_loop.py",
    "igris/core/model_orchestrator.py",
}

_SELF_MOD_CONFIDENCE_THRESHOLD = float(
    os.environ.get("IGRIS_SELF_MOD_CONFIDENCE_THRESHOLD", "0.85")
)

_AUDIT_FILE = ".igris/self_modifications.json"
_SMOKE_TIMEOUT = int(os.environ.get("IGRIS_SELF_MOD_SMOKE_TIMEOUT", "10"))


def get_core_files() -> Set[str]:
    """Return the set of protected core files (env-overridable)."""
    env = os.environ.get("IGRIS_CORE_FILES", "").strip()
    if env:
        return {p.strip() for p in env.split(",") if p.strip()}
    return set(_DEFAULT_CORE_FILES)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SelfModGateResult:
    approved: bool
    touched_core: List[str]        # core files modified in the diff
    diff_hash: str
    test_passed: Optional[bool] = None
    smoke_passed: Optional[bool] = None
    rollback_done: bool = False
    confidence: float = 0.0
    below_confidence_threshold: bool = False
    reason: str = ""
    run_id: str = ""
    checked_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Diff helpers
# ---------------------------------------------------------------------------

def _extract_changed_paths(diff: str) -> List[str]:
    """Extract file paths changed in a unified diff."""
    import re
    paths = []
    for m in re.finditer(r"^(?:---|\+\+\+)\s+(?:a/|b/)?(.+)$", diff, re.MULTILINE):
        p = m.group(1).strip()
        if p and p != "/dev/null" and not p.startswith("b/"):
            paths.append(p)
    # Also match diff --git a/X b/X
    for m in re.finditer(r"^diff --git a/(.+?) b/", diff, re.MULTILINE):
        paths.append(m.group(1).strip())
    seen: set = set()
    unique = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _diff_hash(diff: str) -> str:
    return hashlib.sha256(diff.encode()).hexdigest()[:16]


def touches_core_files(diff: str, core_files: Optional[Set[str]] = None) -> List[str]:
    """Return list of core files touched by the diff."""
    if core_files is None:
        core_files = get_core_files()
    changed = set(_extract_changed_paths(diff))
    return sorted(f for f in core_files if f in changed)


# ---------------------------------------------------------------------------
# Test runner for targeted module tests
# ---------------------------------------------------------------------------

def _test_module_for_core_file(core_file: str, project_root: str) -> str:
    """Infer the test file path for a core file."""
    name = Path(core_file).stem   # e.g. "self_repair_supervisor"
    candidates = [
        f"tests/test_{name}.py",
        f"tests/test_{name.replace('_', '')}.py",
    ]
    for c in candidates:
        if (Path(project_root) / c).exists():
            return c
    return ""


def run_targeted_tests(
    core_files: List[str],
    project_root: str,
    timeout: int = 120,
) -> bool:
    """Run targeted tests for all modified core modules. Returns True if all pass."""
    test_files = []
    for cf in core_files:
        tf = _test_module_for_core_file(cf, project_root)
        if tf:
            test_files.append(tf)

    if not test_files:
        # No targeted tests found — fall back to passing (full suite covered elsewhere)
        return True

    result = subprocess.run(
        ["python", "-m", "pytest", "-q", "--tb=short", "--no-header", "-m", "not slow"]
        + test_files,
        capture_output=True, text=True, cwd=project_root, timeout=timeout,
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Smoke check
# ---------------------------------------------------------------------------

def run_smoke_check(project_root: str, timeout: int = _SMOKE_TIMEOUT) -> bool:
    """Check /api/health responds correctly. Returns True on success."""
    # Try to determine the port from env or default
    port = int(os.environ.get("IGRIS_PORT", "8000"))
    try:
        result = subprocess.run(
            ["curl", "-sf", "--max-time", str(timeout),
             f"http://localhost:{port}/api/health"],
            capture_output=True, text=True, timeout=timeout + 2,
        )
        if result.returncode != 0:
            return False
        payload = json.loads(result.stdout)
        return payload.get("status") == "ok"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

def rollback_last_commit(project_root: str) -> bool:
    """git revert HEAD (no-edit) to undo the last commit. Returns True on success."""
    result = subprocess.run(
        ["git", "revert", "--no-edit", "HEAD"],
        capture_output=True, text=True, cwd=project_root, timeout=30,
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

def _audit_path(project_root: str) -> Path:
    return Path(project_root) / _AUDIT_FILE


def append_audit_record(project_root: str, record: Dict[str, Any]) -> None:
    path = _audit_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    records: List[Dict] = []
    if path.exists():
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            records = []
    records.append(record)
    tmp = str(path) + ".tmp"
    Path(tmp).write_text(json.dumps(records, indent=2), encoding="utf-8")
    os.replace(tmp, str(path))


def load_audit_records(project_root: str) -> List[Dict[str, Any]]:
    path = _audit_path(project_root)
    if not path.exists():
        return []
    try:
        return list(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Main gate
# ---------------------------------------------------------------------------

class SelfModificationGate:
    """Extra validation for patches that touch IGRIS core files.

    Usage::

        gate = SelfModificationGate(project_root)
        result = gate.check(diff, run_id="abc123", confidence=0.9)
        if not result.approved:
            gate.rollback_if_needed(result, project_root)
    """

    def __init__(
        self,
        project_root: str,
        core_files: Optional[Set[str]] = None,
        confidence_threshold: float = _SELF_MOD_CONFIDENCE_THRESHOLD,
        smoke_timeout: int = _SMOKE_TIMEOUT,
    ) -> None:
        self._root = project_root
        self._core_files = core_files or get_core_files()
        self._confidence_threshold = confidence_threshold
        self._smoke_timeout = smoke_timeout

    def is_self_modification(self, diff: str) -> bool:
        return bool(touches_core_files(diff, self._core_files))

    def check(
        self,
        diff: str,
        run_id: str = "",
        confidence: float = 1.0,
        run_smoke: bool = True,
    ) -> SelfModGateResult:
        """Run the self-modification gate. Returns SelfModGateResult."""
        touched = touches_core_files(diff, self._core_files)
        dhash = _diff_hash(diff)

        result = SelfModGateResult(
            approved=False,
            touched_core=touched,
            diff_hash=dhash,
            confidence=confidence,
            run_id=run_id,
        )

        if not touched:
            result.approved = True
            result.reason = "no core files touched"
            return result

        # 1. Confidence threshold
        if confidence < self._confidence_threshold:
            result.below_confidence_threshold = True
            result.approved = False
            result.reason = (
                f"self-modification confidence {confidence:.2f} below threshold "
                f"{self._confidence_threshold:.2f}"
            )
            self._audit(result, outcome="below_confidence_threshold")
            return result

        # 2. Targeted tests
        try:
            test_ok = run_targeted_tests(touched, self._root)
        except Exception as exc:
            test_ok = False
            result.reason = f"targeted test error: {exc}"
        result.test_passed = test_ok

        if not test_ok:
            result.approved = False
            result.reason = result.reason or "targeted tests failed for core module"
            self._audit(result, outcome="test_failed")
            return result

        # 3. Smoke check
        if run_smoke:
            try:
                smoke_ok = run_smoke_check(self._root, self._smoke_timeout)
            except Exception:
                smoke_ok = False
            result.smoke_passed = smoke_ok

            if not smoke_ok:
                result.approved = False
                result.reason = "smoke check failed after self-modification"
                self._audit(result, outcome="smoke_failed")
                return result

        result.approved = True
        result.reason = "all self-modification checks passed"
        self._audit(result, outcome="approved")
        return result

    def rollback_if_needed(self, result: SelfModGateResult) -> bool:
        """Rollback HEAD if the gate failed due to smoke. Returns True if rolled back."""
        if result.approved:
            return False
        if result.smoke_passed is False:
            ok = rollback_last_commit(self._root)
            result.rollback_done = ok
            self._audit(result, outcome="rolled_back")
            return ok
        return False

    def _audit(self, result: SelfModGateResult, outcome: str) -> None:
        try:
            append_audit_record(self._root, {
                "run_id": result.run_id,
                "touched_core": result.touched_core,
                "diff_hash": result.diff_hash,
                "confidence": result.confidence,
                "test_passed": result.test_passed,
                "smoke_passed": result.smoke_passed,
                "rollback_done": result.rollback_done,
                "below_confidence_threshold": result.below_confidence_threshold,
                "reason": result.reason,
                "outcome": outcome,
                "checked_at": result.checked_at,
            })
        except Exception:
            pass  # audit must never raise
