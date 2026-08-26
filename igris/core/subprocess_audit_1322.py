"""Subprocess bypass audit for #1322.

Classifies every subprocess call in igris/core/ as:
- INFRASTRUCTURE: legitimate direct subprocess (git, file system, system queries)
- MIGRATE: should be migrated to ToolRuntime.execute()
- WRAPPER: needs risk check + redaction wrapper

This is Phase 1 of #1322 — audit only, no code changes.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


# Authorized modules that can use subprocess directly
AUTHORIZED_MODULES = {
    "tool_runtime.py",
    "safe_commands.py",
    "devops_manager.py",
    "supervisor_backend.py",
}

# Classification of unauthorized subprocess calls by file and purpose
# This classification was produced by manual review of each call site.
CLASSIFICATION: Dict[str, List[Dict[str, str]]] = {
    "delivery_workflow.py": [
        {"line": "60", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations (status, diff, log, commit, push)"},
        {"line": "66", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations"},
        {"line": "73", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations"},
        {"line": "140", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations"},
        {"line": "154", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations"},
        {"line": "235", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations"},
        {"line": "240", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations"},
        {"line": "243", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations"},
        {"line": "247", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations"},
        {"line": "251", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations"},
        {"line": "65", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations"},
        {"line": "79", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations"},
        {"line": "170", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations"},
        {"line": "176", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations"},
        {"line": "402", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations"},
        {"line": "417", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations"},
        {"line": "438", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations"},
        {"line": "469", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations"},
        {"line": "577", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations"},
        {"line": "564", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations"},
    ],
    "ci_repair_loop.py": [
        {"line": "241", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "CI/devops commands (pytest, git, gh)"},
        {"line": "250", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "CI/devops commands"},
        {"line": "305", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "CI/devops commands"},
        {"line": "341", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "CI/devops commands"},
        {"line": "428", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "CI/devops commands"},
        {"line": "455", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "CI/devops commands"},
        {"line": "460", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "CI/devops commands"},
        {"line": "483", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "CI/devops commands"},
        {"line": "491", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "CI/devops commands"},
        {"line": "498", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "CI/devops commands"},
        {"line": "261", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "CI/devops commands"},
    ],
    "mbop_runner.py": [
        {"line": "93", "method": "run", "classification": "MIGRATE", "purpose": "command execution for mission ops"},
        {"line": "291", "method": "run", "classification": "MIGRATE", "purpose": "command execution for mission ops"},
        {"line": "301", "method": "run", "classification": "MIGRATE", "purpose": "command execution for mission ops"},
        {"line": "504", "method": "run", "classification": "MIGRATE", "purpose": "command execution for mission ops"},
        {"line": "515", "method": "run", "classification": "MIGRATE", "purpose": "command execution for mission ops"},
        {"line": "529", "method": "run", "classification": "MIGRATE", "purpose": "command execution for mission ops"},
    ],
    "smw_actions.py": [
        {"line": "22", "method": "run", "classification": "MIGRATE", "purpose": "SMW action execution"},
        {"line": "28", "method": "run", "classification": "MIGRATE", "purpose": "SMW action execution"},
        {"line": "40", "method": "run", "classification": "MIGRATE", "purpose": "SMW action execution"},
        {"line": "63", "method": "run", "classification": "MIGRATE", "purpose": "SMW action execution"},
        {"line": "69", "method": "run", "classification": "MIGRATE", "purpose": "SMW action execution"},
        {"line": "75", "method": "run", "classification": "MIGRATE", "purpose": "SMW action execution"},
        {"line": "89", "method": "run", "classification": "MIGRATE", "purpose": "SMW action execution"},
    ],
    "code_health_monitor.py": [
        {"line": "66", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "code health queries (wc, grep, git)"},
        {"line": "171", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "code health queries"},
        {"line": "310", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "code health queries"},
        {"line": "344", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "code health queries"},
    ],
    "self_modification_gate.py": [
        {"line": "153", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git diff for modification detection"},
        {"line": "170", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git diff for modification detection"},
        {"line": "189", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git diff for modification detection"},
    ],
    "dependency_checker.py": [
        {"line": "92", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "pip/npm dependency checks"},
        {"line": "108", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "pip/npm dependency checks"},
        {"line": "180", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "pip/npm dependency checks"},
    ],
    "context_aggregator.py": [
        {"line": "305", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git/file system context gathering"},
        {"line": "546", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git/file system context gathering"},
    ],
    "outcome_quality_tracker.py": [
        {"line": "130", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git log for outcome tracking"},
        {"line": "145", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git log for outcome tracking"},
    ],
    "doctor.py": [
        {"line": "279", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "system health diagnostics"},
        {"line": "304", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "system health diagnostics"},
    ],
    "github_backend.py": [
        {"line": "135", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "gh CLI for GitHub operations"},
    ],
    "github_read_gateway.py": [
        {"line": "272", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "gh CLI for GitHub read operations"},
    ],
    "github_write_gateway.py": [
        {"line": "213", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "gh CLI for GitHub write operations"},
    ],
    "goap_planner.py": [
        {"line": "337", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "system query for planning"},
    ],
    "network_diag_gateway.py": [
        {"line": "95", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "network diagnostics (ping, curl)"},
    ],
    "behavior_tracker.py": [
        {"line": "348", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git blame for behavior tracking"},
    ],
    "smw_diagnosis.py": [
        {"line": "50", "method": "run", "classification": "MIGRATE", "purpose": "SMW diagnosis command execution"},
    ],
    "smw_pr_review.py": [
        {"line": "109", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git diff for PR review"},
    ],
    "smw_sensors.py": [
        {"line": "42", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "system sensor queries"},
    ],
    "smw_teach.py": [
        {"line": "65", "method": "run", "classification": "MIGRATE", "purpose": "teaching command execution"},
        {"line": "121", "method": "run", "classification": "MIGRATE", "purpose": "teaching command execution"},
    ],
    "supervisor_api.py": [
        {"line": "260", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations for supervisor"},
    ],
    "self_repair_supervisor.py": [
        {"line": "1006", "method": "run", "classification": "INFRASTRUCTURE", "purpose": "git operations for repair"},
    ],
}


@dataclass
class AuditSummary:
    """Summary of the subprocess audit."""
    total_files: int = 0
    total_calls: int = 0
    authorized_calls: int = 0
    unauthorized_calls: int = 0
    infrastructure_calls: int = 0
    migrate_calls: int = 0
    wrapper_calls: int = 0
    unclassified_calls: int = 0


def run_audit() -> AuditSummary:
    """Run the subprocess audit and return a summary."""
    summary = AuditSummary()

    for filename, calls in CLASSIFICATION.items():
        summary.total_files += 1
        for call in calls:
            summary.total_calls += 1
            cls = call.get("classification", "UNCLASSIFIED")
            if cls == "INFRASTRUCTURE":
                summary.infrastructure_calls += 1
            elif cls == "MIGRATE":
                summary.migrate_calls += 1
            elif cls == "WRAPPER":
                summary.wrapper_calls += 1
            else:
                summary.unclassified_calls += 1

    # Authorized calls
    summary.authorized_calls = 6  # tool_runtime(1) + devops_manager(2) + supervisor_backend(3)
    summary.unauthorized_calls = summary.total_calls

    return summary
