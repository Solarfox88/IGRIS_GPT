"""Focused hardening tests for decomposition validator evidence and borderline cases."""

from __future__ import annotations

import json
from typing import Any, Dict

from igris.core.decomposition_validator import DecompositionValidator
from igris.core.self_repair_supervisor import RankSupervisorConfig, SelfRepairSupervisor, SupervisorRun


def _sub(title: str, goal: str, *, criteria=None, tests=None, scopes=None, deps=None) -> Dict[str, Any]:
    return {
        "title": title,
        "goal": goal,
        "risk_level": "medium",
        "acceptance_criteria": criteria if criteria is not None else [
            "All tests pass without regressions",
            "Implementation matches the stated goal",
            "No new lint or import errors are introduced",
        ],
        "tests": tests if tests is not None else ["tests/test_dummy.py"],
        "allowed_file_scopes": scopes if scopes is not None else ["igris/core/dummy.py"],
        "dependencies": deps if deps is not None else [],
    }


def test_report_diagnostics_are_readable_and_serializable():
    report = DecompositionValidator(parent_goal="Refine decomposition quality").validate([
        _sub(
            "Core: harden decomposition report",
            "Improve decomposition evidence and report structure",
        ),
    ])

    diag = report.to_diagnostics()
    assert diag["summary"].startswith("accepted=")
    assert diag["valid"] in {True, False}
    assert diag["counts"]["accepted"] == 1
    assert diag["accepted_titles"] == ["Core: harden decomposition report"]
    assert diag["handoff"]["accepted_items"][0]["success_signal"]
    assert diag["handoff"]["accepted_items"][0]["failure_fallback"]
    json.dumps(diag)


def test_exact_duplicate_is_rejected_while_near_duplicate_is_preserved():
    report = DecompositionValidator(parent_goal="Refine decomposition quality").validate([
        _sub(
            "Core: implement cache invalidation",
            "Implement cache invalidation for memory writes",
        ),
        _sub(
            "Core: implement cache invalidation",
            "Implement cache invalidation for memory writes",
        ),
        _sub(
            "Core: implement cache invalidation for cache warming",
            "Implement cache invalidation for cache warming",
        ),
    ])

    assert len(report.accepted) == 2
    assert len(report.rejected) == 1
    assert any(issue.code in {"TITLE", "DEDUP", "GOAL"} for issue in report.issues)


def test_missing_handoff_fields_are_normalized_in_accepted_submission():
    report = DecompositionValidator(parent_goal="Refine decomposition quality").validate([
        {
            "title": "Core: normalize handoff fields",
            "goal": "Normalize the decomposition handoff payload",
            "risk_level": "low",
            "acceptance_criteria": ["AC one", "AC two", "AC three"],
            "tests": [],
            "allowed_file_scopes": [],
            "dependencies": [],
        },
    ])

    assert report.ok
    sm = report.accepted[0]
    payload = sm.to_dict()
    for field in (
        "title",
        "goal",
        "risk_level",
        "acceptance_criteria",
        "allowed_file_scopes",
        "tests",
        "dependencies",
        "out_of_scope",
        "success_signal",
        "failure_fallback",
    ):
        assert field in payload
    assert payload["success_signal"]
    assert payload["failure_fallback"]


def test_supervisor_embeds_validation_summary_into_decomposition():
    class _Backend:
        def run_reasoning(self, goal, max_steps, initial_context, timeout=300, task_type="code_reasoning", preferred_profile=None):
            return {
                "status": "finished",
                "stop_reason": "finish",
                "final_summary": json.dumps({
                    "why_too_large": "Goal spans multiple files and requires decomposition.",
                    "sub_missions": [
                        {
                            "title": "Core: isolate validation report",
                            "goal": "Isolate decomposition validation report handling",
                            "risk_level": "low",
                            "acceptance_criteria": [
                                "Validator report is captured",
                                "The summary is serializable",
                                "No regressions are introduced",
                            ],
                            "allowed_file_scopes": ["igris/core/decomposition_validator.py"],
                            "tests": ["tests/test_decomposition_validator.py"],
                            "dependencies": [],
                        }
                    ],
                    "first_sub_mission": "Core: isolate validation report",
                    "human_approval_required": False,
                }),
            }

    supervisor = SelfRepairSupervisor("/tmp/project", backend=_Backend())
    run = SupervisorRun(run_id="decomp-summary", rank_id="rank-test")
    config = RankSupervisorConfig(goal="Refine decomposition quality and evidence summary")

    decomposition = supervisor._ask_igris_decompose(run, config)

    assert "_validation_summary" in decomposition
    summary = decomposition["_validation_summary"]
    assert summary["counts"]["accepted"] == 1
    assert summary["handoff"]["accepted_items"][0]["title"] == "Core: isolate validation report"
    assert run.events[-1].phase == "decomposition_quality"
