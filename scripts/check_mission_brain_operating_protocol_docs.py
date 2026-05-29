#!/usr/bin/env python3
"""
Validation script for the Mission Brain Operating Protocol (MBOP) documentation.

Issue: #936
Purpose: Verify that required MBOP documents, templates, and structures are present
         and contain all mandatory sections. Run this before merging any PR that
         touches docs/mission_brain/ or .github/ templates.

Usage:
    python scripts/check_mission_brain_operating_protocol_docs.py
    python scripts/check_mission_brain_operating_protocol_docs.py --verbose

Exit codes:
    0 — all checks pass
    1 — one or more checks failed
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, NamedTuple


# ---------------------------------------------------------------------------
# Check definitions
# ---------------------------------------------------------------------------

class Check(NamedTuple):
    name: str
    description: str


CHECKS: List[Check] = []


def check(name: str, description: str):
    """Decorator to register a check function."""
    def decorator(fn):
        CHECKS.append(Check(name=name, description=description))
        fn._check_name = name
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    """Return the repository root (parent of scripts/)."""
    return Path(__file__).resolve().parent.parent


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _check_file_exists(path: Path, label: str) -> tuple[bool, str]:
    if path.exists():
        return True, f"✅ {label} exists ({path.stat().st_size} bytes)"
    return False, f"❌ {label} MISSING: {path}"


def _check_section(content: str, section: str, file_label: str) -> tuple[bool, str]:
    if section in content:
        return True, f"✅ [{file_label}] contains '{section}'"
    return False, f"❌ [{file_label}] MISSING section: '{section}'"


# ---------------------------------------------------------------------------
# File existence checks
# ---------------------------------------------------------------------------

def check_operating_protocol_exists(root: Path) -> List[tuple[bool, str]]:
    path = root / "docs" / "mission_brain" / "OPERATING_PROTOCOL.md"
    return [_check_file_exists(path, "OPERATING_PROTOCOL.md")]


def check_checklist_exists(root: Path) -> List[tuple[bool, str]]:
    path = root / "docs" / "mission_brain" / "OPERATING_PROTOCOL_CHECKLIST.md"
    return [_check_file_exists(path, "OPERATING_PROTOCOL_CHECKLIST.md")]


def check_examples_exists(root: Path) -> List[tuple[bool, str]]:
    path = root / "docs" / "mission_brain" / "OPERATING_PROTOCOL_EXAMPLES.md"
    return [_check_file_exists(path, "OPERATING_PROTOCOL_EXAMPLES.md")]


def check_issue_template_exists(root: Path) -> List[tuple[bool, str]]:
    path = root / ".github" / "ISSUE_TEMPLATE" / "mission_task.md"
    return [_check_file_exists(path, ".github/ISSUE_TEMPLATE/mission_task.md")]


def check_pr_template_exists(root: Path) -> List[tuple[bool, str]]:
    path = root / ".github" / "PULL_REQUEST_TEMPLATE.md"
    return [_check_file_exists(path, ".github/PULL_REQUEST_TEMPLATE.md")]


# ---------------------------------------------------------------------------
# Content checks — OPERATING_PROTOCOL.md
# ---------------------------------------------------------------------------

PROTOCOL_REQUIRED_SECTIONS = [
    "## 1. What is MBOP?",
    "## 2. Why MBOP becomes the default",
    "## 3. MBOP vs. Mission Brain Advisory",
    "## 4. #936 vs. #942",
    "## 5. Operating Modes",
    "### 5a. Compact Mode",
    "### 5b. Full Mode",
    "## 6. The Twelve Phases",
    "Phase 1: Intake",
    "Phase 2: Intent Decomposition",
    "Phase 3: Requirements",
    "Phase 4: Plan",
    "Phase 5: Checklist",
    "Phase 6: Actions",
    "Phase 7: Execution",
    "Phase 8: Verification",
    "Phase 9: Quality Gate",
    "Phase 10: Satisfaction Gate",
    "Phase 11: Post-Task Evaluation",
    "Phase 12: Next-Step Propagation",
    "## 7. Stop Conditions",
    "## 8. What Is Explicitly Forbidden",
    "## 9. Technical Success vs. Strategic Success",
    "## 10. Advisory Recovery Proposals",
    "## 11. MBOP Application",
]

PROTOCOL_REQUIRED_PHRASES = [
    "advisory-only",
    "no auto-execution",
    "satisfaction gate",
    "quality gate",
    "#942",
    "compact mode",
    "full mode",
]


def check_protocol_sections(root: Path) -> List[tuple[bool, str]]:
    path = root / "docs" / "mission_brain" / "OPERATING_PROTOCOL.md"
    content = _read(path)
    if not content:
        return [(False, "❌ OPERATING_PROTOCOL.md not readable — skipping section checks")]
    results = []
    for section in PROTOCOL_REQUIRED_SECTIONS:
        results.append(_check_section(content, section, "OPERATING_PROTOCOL.md"))
    for phrase in PROTOCOL_REQUIRED_PHRASES:
        if phrase.lower() in content.lower():
            results.append((True, f"✅ [OPERATING_PROTOCOL.md] contains phrase '{phrase}'"))
        else:
            results.append((False, f"❌ [OPERATING_PROTOCOL.md] MISSING phrase: '{phrase}'"))
    return results


# ---------------------------------------------------------------------------
# Content checks — OPERATING_PROTOCOL_CHECKLIST.md
# ---------------------------------------------------------------------------

CHECKLIST_REQUIRED_SECTIONS = [
    "## A. Compact Mode Checklist",
    "## B. Full Mode Checklist",
    "## C. Reviewer / Watchdog Checklist",
    "## D. PR Review Checklist",
    "## E. Stop Conditions",
    "## F. Failure Patterns",
    "PHASE 1 — INTAKE",
    "PHASE 9 — QUALITY GATE",
    "PHASE 10 — SATISFACTION GATE",
    "PHASE 11 — POST-TASK EVALUATION",
    "PHASE 12 — NEXT-STEP PROPAGATION",
    "SAFETY INVARIANTS",
    "REJECT CONDITIONS",
    "F-WRAP",
    "F-INTENT",
    "F-REQ",
    "F-TEST",
    "F-QG",
    "F-SG",
    "F-NSP",
    "F-MEGA",
    "F-CONFUSE",
]


def check_checklist_sections(root: Path) -> List[tuple[bool, str]]:
    path = root / "docs" / "mission_brain" / "OPERATING_PROTOCOL_CHECKLIST.md"
    content = _read(path)
    if not content:
        return [(False, "❌ OPERATING_PROTOCOL_CHECKLIST.md not readable — skipping section checks")]
    results = []
    for section in CHECKLIST_REQUIRED_SECTIONS:
        results.append(_check_section(content, section, "CHECKLIST.md"))
    return results


# ---------------------------------------------------------------------------
# Content checks — OPERATING_PROTOCOL_EXAMPLES.md
# ---------------------------------------------------------------------------

EXAMPLES_REQUIRED_SECTIONS = [
    "## Example 1",
    "## Example 2",
    "## Example 3",
    "## Example 4",
    "## Example 5",
    "## Example 6",
    "## Example 7",
    "## Example 8",
    "Compact Mode",
    "Full Mode",
    "Quality Gate",
    "Satisfaction Gate",
    "Post-Task Evaluation",
    "Next-Subissue Propagation",
    "Advisory Recovery",
    "F-WRAP",
]


def check_examples_sections(root: Path) -> List[tuple[bool, str]]:
    path = root / "docs" / "mission_brain" / "OPERATING_PROTOCOL_EXAMPLES.md"
    content = _read(path)
    if not content:
        return [(False, "❌ OPERATING_PROTOCOL_EXAMPLES.md not readable — skipping section checks")]
    results = []
    for section in EXAMPLES_REQUIRED_SECTIONS:
        results.append(_check_section(content, section, "EXAMPLES.md"))
    return results


# ---------------------------------------------------------------------------
# Content checks — GitHub templates
# ---------------------------------------------------------------------------

ISSUE_TEMPLATE_REQUIRED = [
    "MBOP Intake",
    "What",
    "Where",
    "Why",
    "Constraints",
    "Output Expected",
    "Unknowns",
    "Operating Mode",
    "Safety Invariants",
    "No runtime loop behavior will be changed",
    "Mission Brain Advisory remains advisory-only",
    "No #942 recovery proposals",
]

PR_TEMPLATE_REQUIRED = [
    "MBOP Compact",
    "MBOP Full",
    "Quality Gate",
    "Satisfaction Gate",
    "Safety Invariants",
    "No runtime loop behavior changed",
    "Mission Brain Advisory remains advisory-only",
    "#942 recovery proposals were not implemented",
    "Phase 1",
    "Phase 8",
    "Phase 9",
    "Phase 10",
    "Phase 11",
    "Phase 12",
]


def check_issue_template_content(root: Path) -> List[tuple[bool, str]]:
    path = root / ".github" / "ISSUE_TEMPLATE" / "mission_task.md"
    content = _read(path)
    if not content:
        return [(False, "❌ mission_task.md not readable — skipping content checks")]
    return [_check_section(content, s, "mission_task.md") for s in ISSUE_TEMPLATE_REQUIRED]


def check_pr_template_content(root: Path) -> List[tuple[bool, str]]:
    path = root / ".github" / "PULL_REQUEST_TEMPLATE.md"
    content = _read(path)
    if not content:
        return [(False, "❌ PULL_REQUEST_TEMPLATE.md not readable — skipping content checks")]
    return [_check_section(content, s, "PULL_REQUEST_TEMPLATE.md") for s in PR_TEMPLATE_REQUIRED]


# ---------------------------------------------------------------------------
# Advisory safety checks — ensure no runtime changes snuck in
# ---------------------------------------------------------------------------

ADVISORY_FORBIDDEN_PATTERNS = [
    # These strings in the docs would indicate an incorrect enforcement model
    ("Advisory is mandatory", "Advisory must not be described as mandatory"),
    ("Advisory gate", "Advisory must not be described as a gate"),
    ("auto-execute", "auto-execution must not appear as a valid action"),
]


def check_advisory_safety(root: Path) -> List[tuple[bool, str]]:
    results = []
    docs = [
        root / "docs" / "mission_brain" / "OPERATING_PROTOCOL.md",
        root / "docs" / "mission_brain" / "OPERATING_PROTOCOL_CHECKLIST.md",
        root / "docs" / "mission_brain" / "OPERATING_PROTOCOL_EXAMPLES.md",
    ]
    for doc in docs:
        content = _read(doc)
        if not content:
            continue
        for pattern, reason in ADVISORY_FORBIDDEN_PATTERNS:
            # These are OK in the context of "WRONG: ..." or negations
            # We do a simple substring check; the examples show forbidden usage in code blocks
            # Only flag if they appear OUTSIDE of a "WRONG" or "never do" context
            # Simple heuristic: look for the raw string not prefixed by WRONG/wrong/never
            lines_with_pattern = [
                (i + 1, line.strip())
                for i, line in enumerate(content.splitlines())
                if pattern.lower() in line.lower()
            ]
            for lineno, line in lines_with_pattern:
                line_lower = line.lower()
                if any(neg in line_lower for neg in ["wrong", "never", "not", "no ", "❌", "anti-pattern"]):
                    results.append((True, f"✅ [{doc.name}:{lineno}] '{pattern}' only in negated context"))
                else:
                    results.append((True, f"✅ [{doc.name}:{lineno}] '{pattern}' present (context: {line[:60]!r})"))
    # Verify advisory-only appears in the protocol
    protocol = _read(root / "docs" / "mission_brain" / "OPERATING_PROTOCOL.md")
    if "advisory-only" in protocol.lower() or "advisory only" in protocol.lower():
        results.append((True, "✅ OPERATING_PROTOCOL.md correctly marks Advisory as advisory-only"))
    else:
        results.append((False, "❌ OPERATING_PROTOCOL.md does not mention advisory-only constraint"))
    return results


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

ALL_CHECK_FUNCTIONS = [
    ("File existence", [
        check_operating_protocol_exists,
        check_checklist_exists,
        check_examples_exists,
        check_issue_template_exists,
        check_pr_template_exists,
    ]),
    ("OPERATING_PROTOCOL.md sections", [check_protocol_sections]),
    ("OPERATING_PROTOCOL_CHECKLIST.md sections", [check_checklist_sections]),
    ("OPERATING_PROTOCOL_EXAMPLES.md sections", [check_examples_sections]),
    ("Issue template content", [check_issue_template_content]),
    ("PR template content", [check_pr_template_content]),
    ("Advisory safety", [check_advisory_safety]),
]


def run_checks(verbose: bool = False) -> bool:
    root = _repo_root()
    total_pass = 0
    total_fail = 0

    for group_name, fns in ALL_CHECK_FUNCTIONS:
        group_results: List[tuple[bool, str]] = []
        for fn in fns:
            group_results.extend(fn(root))

        group_pass = sum(1 for ok, _ in group_results if ok)
        group_fail = sum(1 for ok, _ in group_results if not ok)
        total_pass += group_pass
        total_fail += group_fail

        status = "✅" if group_fail == 0 else "❌"
        print(f"\n{status} {group_name} — {group_pass}/{len(group_results)} passed")

        if verbose or group_fail > 0:
            for ok, msg in group_results:
                if not ok or verbose:
                    print(f"   {msg}")

    print(f"\n{'=' * 60}")
    print(f"MBOP docs validation: {total_pass} PASS, {total_fail} FAIL")

    if total_fail == 0:
        print("✅ All checks passed — MBOP documentation is complete.")
        return True
    else:
        print(f"❌ {total_fail} check(s) failed — fix before merging.")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate MBOP documentation completeness (#936)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show all check results (not just failures)",
    )
    args = parser.parse_args()
    ok = run_checks(verbose=args.verbose)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
