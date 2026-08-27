#!/usr/bin/env python3
"""Subprocess governance lint rule for #1322 Phase 3.

AST-based check that prevents unauthorized subprocess imports/calls
outside an explicit allowlist. This enforces the governance policy
established by #1322.

Policy:
- Only allowlisted modules may import subprocess.
- The 4 migrated modules (mbop_runner, smw_actions, smw_diagnosis, smw_teach)
  are explicitly FORBIDDEN from importing subprocess.
- Any new file that imports subprocess outside the allowlist fails.
- Allowlisted INFRASTRUCTURE modules are documented with rationale.

Usage:
    python scripts/check_subprocess_governance.py
    python scripts/check_subprocess_governance.py --json
    python scripts/check_subprocess_governance.py --root /path/to/igris

Exit codes:
    0 = all subprocess usage is governed
    1 = unauthorized subprocess usage detected
    2 = internal error
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple


# =====================================================================
# Governance policy
# =====================================================================

# Modules that are always allowed to import subprocess.
# These are the authorized execution gateways per #1322 acceptance criteria.
ALWAYS_ALLOWED: Dict[str, str] = {
    "igris/core/tool_runtime.py": "Authorized executor — governed_run() and ToolRuntime",
    "igris/core/devops_manager.py": "Authorized DevOps command runner",
    "igris/core/supervisor_backend.py": "Authorized supervisor execution backend",
}

# Modules explicitly FORBIDDEN from importing subprocess.
# These were migrated in Phase 2 to use governed_run().
FORBIDDEN_MODULES: Set[str] = {
    "igris/core/mbop_runner.py",
    "igris/core/smw_actions.py",
    "igris/core/smw_diagnosis.py",
    "igris/core/smw_teach.py",
}

# INFRASTRUCTURE modules allowlisted with rationale.
# These modules use subprocess for legitimate infrastructure commands
# (git, gh, system queries) that are not user-facing tool execution.
# They are allowlisted pending Phase 4 evaluation/migration.
INFRASTRUCTURE_ALLOWED: Dict[str, str] = {
    "igris/core/agent_reasoning_loop.py": "Imports subprocess for TimeoutExpired exception handling only",
    "igris/core/behavior_tracker.py": "System behavior monitoring commands",
    "igris/core/benchmark_ping.py": "Benchmark infrastructure — imports for exception handling",
    "igris/core/chat_context.py": "Chat context infrastructure — imports for exception handling",
    "igris/core/ci_repair_loop.py": "CI repair commands (git, pytest) — infrastructure",
    "igris/core/code_health_monitor.py": "Code health monitoring commands (git, grep, wc)",
    "igris/core/context_aggregator.py": "Context aggregation infrastructure commands",
    "igris/core/delivery_workflow.py": "Git operations for delivery workflow — infrastructure",
    "igris/core/dependency_checker.py": "Dependency checking commands (pip, apt)",
    "igris/core/doctor.py": "System doctor diagnostic commands",
    "igris/core/github_backend.py": "GitHub CLI (gh) infrastructure commands",
    "igris/core/github_read_gateway.py": "GitHub read gateway — gh CLI commands",
    "igris/core/github_write_gateway.py": "GitHub write gateway — gh CLI commands",
    "igris/core/goap_planner.py": "GOAP planner infrastructure commands",
    "igris/core/network_diag_gateway.py": "Network diagnostic commands (ss, ping)",
    "igris/core/outcome_quality_tracker.py": "Outcome quality tracking commands",
    "igris/core/self_modification_gate.py": "Self-modification gate validation commands",
    "igris/core/self_repair_supervisor.py": "Self-repair supervisor infrastructure",
    "igris/core/smw_pr_review.py": "SMW PR review — gh CLI commands",
    "igris/core/smw_sensors.py": "SMW sensors — system monitoring commands",
    "igris/core/supervisor_analysis.py": "Supervisor analysis — imports for exception handling",
    "igris/core/supervisor_api.py": "Supervisor API infrastructure commands",
    "igris/core/supervisor_models.py": "Supervisor models — imports for exception handling",
    "igris/core/supervisor_repair_helpers.py": "Supervisor repair helpers — imports for exception handling",
    "igris/core/supervisor_subissues.py": "Supervisor subissue management — imports for exception handling",
}

# Combined allowlist
ALLOWED_MODULES: Dict[str, str] = {**ALWAYS_ALLOWED, **INFRASTRUCTURE_ALLOWED}

# Subprocess symbols that are governed
SUBPROCESS_CALL_METHODS = {"run", "Popen", "check_call", "check_output", "call"}


# =====================================================================
# Violation dataclass
# =====================================================================

@dataclass
class Violation:
    """A subprocess governance violation."""
    file: str
    line: int
    symbol: str
    reason: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "file": self.file,
            "line": str(self.line),
            "symbol": self.symbol,
            "reason": self.reason,
        }


# =====================================================================
# AST-based checker
# =====================================================================

def check_file(path: Path, root: Path) -> List[Violation]:
    """Check a single Python file for subprocess governance violations.

    Args:
        path: Absolute path to the .py file
        root: Root directory for computing relative paths

    Returns:
        List of Violation objects (empty if compliant)
    """
    rel = str(path)
    violations: List[Violation] = []

    # Check forbidden modules first
    if rel in FORBIDDEN_MODULES:
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return violations  # Syntax errors handled elsewhere

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "subprocess":
                        violations.append(Violation(
                            file=rel, line=node.lineno,
                            symbol=f"import subprocess",
                            reason=f"FORBIDDEN: {rel} was migrated to governed_run() in Phase 2 and must not import subprocess",
                        ))
            elif isinstance(node, ast.ImportFrom):
                if node.module == "subprocess":
                    violations.append(Violation(
                        file=rel, line=node.lineno,
                        symbol=f"from subprocess import ...",
                        reason=f"FORBIDDEN: {rel} was migrated to governed_run() in Phase 2 and must not import subprocess",
                    ))
        return violations

    # If module is allowlisted, no violations
    if rel in ALLOWED_MODULES:
        return violations

    # Check for unauthorized imports
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return violations  # Syntax errors handled elsewhere

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    violations.append(Violation(
                        file=rel, line=node.lineno,
                        symbol=f"import subprocess",
                        reason=f"UNAUTHORIZED: {rel} is not in the subprocess allowlist. Use governed_run() from igris.core.tool_runtime instead.",
                    ))
        elif isinstance(node, ast.ImportFrom):
            if node.module == "subprocess":
                imported_names = ", ".join(a.name for a in node.names)
                violations.append(Violation(
                    file=rel, line=node.lineno,
                    symbol=f"from subprocess import {imported_names}",
                    reason=f"UNAUTHORIZED: {rel} is not in the subprocess allowlist. Use governed_run() from igris.core.tool_runtime instead.",
                ))

    return violations


def check_directory(root: Path) -> Tuple[List[Violation], Dict[str, int]]:
    """Check all Python files in a directory for subprocess governance.

    Args:
        root: Root directory to check (e.g., Path("igris/core"))

    Returns:
        Tuple of (violations, stats)
    """
    violations: List[Violation] = []
    stats = {
        "files_checked": 0,
        "files_with_subprocess": 0,
        "allowed_modules": 0,
        "forbidden_modules": 0,
        "unauthorized_modules": 0,
    }

    for path in sorted(root.rglob("*.py")):
        stats["files_checked"] += 1
        rel = str(path)

        # Quick check if file references subprocess at all
        text = path.read_text(encoding="utf-8", errors="replace")
        if "subprocess" not in text:
            continue

        stats["files_with_subprocess"] += 1

        if rel in FORBIDDEN_MODULES:
            stats["forbidden_modules"] += 1
        elif rel in ALLOWED_MODULES:
            stats["allowed_modules"] += 1
        else:
            stats["unauthorized_modules"] += 1

        file_violations = check_file(path, root)
        violations.extend(file_violations)

    return violations, stats


# =====================================================================
# Main
# =====================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="Subprocess governance lint rule (#1322 Phase 3)")
    parser.add_argument("--root", default="igris/core", help="Root directory to check")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--list-allowed", action="store_true", help="List allowed modules and exit")
    args = parser.parse_args()

    if args.list_allowed:
        print("=== ALWAYS ALLOWED (authorized executors) ===")
        for mod, reason in sorted(ALWAYS_ALLOWED.items()):
            print(f"  {mod}: {reason}")
        print()
        print("=== INFRASTRUCTURE ALLOWED (with rationale) ===")
        for mod, reason in sorted(INFRASTRUCTURE_ALLOWED.items()):
            print(f"  {mod}: {reason}")
        print()
        print("=== FORBIDDEN (migrated in Phase 2) ===")
        for mod in sorted(FORBIDDEN_MODULES):
            print(f"  {mod}")
        return 0

    root = Path(args.root)
    if not root.exists():
        print(f"ERROR: root directory {root} does not exist", file=sys.stderr)
        return 2

    violations, stats = check_directory(root)

    if args.json:
        output = {
            "violations": [v.to_dict() for v in violations],
            "stats": stats,
            "policy": {
                "always_allowed": ALWAYS_ALLOWED,
                "infrastructure_allowed": INFRASTRUCTURE_ALLOWED,
                "forbidden": sorted(FORBIDDEN_MODULES),
            },
        }
        print(json.dumps(output, indent=2))
        return 0 if not violations else 1
    else:
        print("=== Subprocess Governance Check (#1322 Phase 3) ===")
        print()
        print(f"Files checked: {stats['files_checked']}")
        print(f"Files with subprocess: {stats['files_with_subprocess']}")
        print(f"Allowed modules: {stats['allowed_modules']}")
        print(f"Forbidden modules (migrated): {stats['forbidden_modules']}")
        print(f"Unauthorized modules: {stats['unauthorized_modules']}")
        print()

        if violations:
            print(f"VIOLATIONS ({len(violations)}):")
            for v in violations:
                print(f"  {v.file}:{v.line} — {v.symbol}")
                print(f"    {v.reason}")
            print()
            print("FAILED: subprocess governance violations detected.")
            return 1
        else:
            print("PASSED: all subprocess usage is governed.")
            print()
            print("Policy:")
            print(f"  Always allowed: {len(ALWAYS_ALLOWED)} modules")
            print(f"  Infrastructure allowed: {len(INFRASTRUCTURE_ALLOWED)} modules")
            print(f"  Forbidden (migrated): {len(FORBIDDEN_MODULES)} modules")
            return 0


if __name__ == "__main__":
    sys.exit(main())
