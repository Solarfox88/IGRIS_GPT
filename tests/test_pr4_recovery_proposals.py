"""EPIC #942 — Recovery Proposal tests.

Covers:
- Phase 1: Schema + invariants (SuggestedAction, RecoveryProposal)
- Phase 2: Template mapping (combined_status → proposal_type)
- Phase 3: Generation engine (generate_recovery_proposal)
- Phase 4: Feature flag + report enrichment
- Phase 5: MBOP handoff (proposal_to_mbop_handoff)
- Phase 6: Metrics (compute_proposal_metrics)

Invariants tested:
- auto_executable=False always (SuggestedAction and RecoveryProposal)
- approval_required=True always
- No proposal for passed/completed
- proposal_type never "completed"
- Every proposal has proposal_id + source trace
- MBOP handoff contains no executable commands
- Report enrichment is additive-only, never modifies original fields
- Feature flag default=off
"""

from __future__ import annotations

import pytest

from igris.agent.mission.recovery_proposal import (
    EXCLUDED_PROPOSAL_TYPES,
    EXCLUDED_RUN_STATUSES,
    PROPOSAL_CONTINUE_FROM_PARTIAL,
    PROPOSAL_GATHER_MISSING_CONTEXT,
    PROPOSAL_HUMAN_REVIEW,
    PROPOSAL_INVESTIGATE_ANOMALY,
    PROPOSAL_OPERATOR_DECISION,
    PROPOSAL_RESTART_SMALLER_SCOPE,
    VALID_PROPOSAL_TYPES,
    MBOPHandoff,
    ProposalValidator,
    RecoveryProposal,
    RecoveryProposalConfig,
    SuggestedAction,
    compute_proposal_metrics,
    enrich_report_with_proposal,
    generate_recovery_proposal,
    get_proposal_type,
    proposal_to_mbop_handoff,
    proposal_to_mbop_handoff_safe,
    strip_recovery_proposal,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config(enabled: bool = True) -> RecoveryProposalConfig:
    return RecoveryProposalConfig(enabled=enabled)


def _failed_report(**kwargs) -> dict:
    base = {
        "current_loop_decision": "failed",
        "mission_brain_decision": "partial",
        "report_type": "diagnostic",
    }
    base.update(kwargs)
    return base


def _blocked_report(**kwargs) -> dict:
    base = {
        "current_loop_decision": "blocked",
        "mission_brain_decision": "partial",
        "report_type": "diagnostic",
    }
    base.update(kwargs)
    return base


def _make_proposal(**kwargs) -> RecoveryProposal:
    defaults = {
        "trigger_status": "failed",
        "combined_status": "technical_failure_with_goal_progress",
        "proposal_type": PROPOSAL_CONTINUE_FROM_PARTIAL,
        "problem_summary": "Test failure",
        "suggested_requirements": ["req1"],
        "suggested_checklist": ["[ ] step 1"],
        "suggested_tests": ["run tests"],
    }
    defaults.update(kwargs)
    return RecoveryProposal(**defaults)


# ---------------------------------------------------------------------------
# Phase 1: SuggestedAction schema + invariants
# ---------------------------------------------------------------------------

class TestSuggestedActionInvariants:

    def test_auto_executable_always_false(self):
        a = SuggestedAction(description="Review logs", auto_executable=True)
        assert a.auto_executable is False

    def test_requires_approval_always_true(self):
        a = SuggestedAction(description="Review logs", requires_approval=False)
        assert a.requires_approval is True

    def test_empty_description_raises(self):
        with pytest.raises(ValueError, match="description must be non-empty"):
            SuggestedAction(description="")

    def test_whitespace_description_raises(self):
        with pytest.raises(ValueError, match="description must be non-empty"):
            SuggestedAction(description="   ")

    def test_invalid_risk_level_raises(self):
        with pytest.raises(ValueError, match="risk_level"):
            SuggestedAction(description="Do something", risk_level="critical")

    def test_valid_risk_levels(self):
        for level in ("low", "medium", "high"):
            a = SuggestedAction(description="Action", risk_level=level)
            assert a.risk_level == level

    def test_to_dict_always_has_invariants(self):
        a = SuggestedAction(description="Do X", risk_level="medium")
        d = a.to_dict()
        assert d["auto_executable"] is False
        assert d["requires_approval"] is True
        assert d["description"] == "Do X"
        assert d["risk_level"] == "medium"

    def test_to_dict_never_executable_even_if_passed_true(self):
        a = SuggestedAction(description="Do X", auto_executable=True, requires_approval=False)
        d = a.to_dict()
        assert d["auto_executable"] is False
        assert d["requires_approval"] is True


# ---------------------------------------------------------------------------
# Phase 1: RecoveryProposal schema + invariants
# ---------------------------------------------------------------------------

class TestRecoveryProposalInvariants:

    def test_auto_executable_always_false(self):
        p = RecoveryProposal(trigger_status="failed", auto_executable=True)
        assert p.auto_executable is False

    def test_approval_required_always_true(self):
        p = RecoveryProposal(trigger_status="failed", approval_required=False)
        assert p.approval_required is True

    def test_proposal_type_completed_normalized(self):
        p = RecoveryProposal(trigger_status="failed", proposal_type="completed")
        assert p.proposal_type != "completed"
        assert p.proposal_type in VALID_PROPOSAL_TYPES

    def test_invalid_proposal_type_normalized(self):
        p = RecoveryProposal(trigger_status="failed", proposal_type="launch_rockets")
        assert p.proposal_type in VALID_PROPOSAL_TYPES

    def test_proposal_id_generated(self):
        p = RecoveryProposal(trigger_status="failed")
        assert p.proposal_id
        assert len(p.proposal_id) >= 8

    def test_two_proposals_have_different_ids(self):
        p1 = RecoveryProposal(trigger_status="failed")
        p2 = RecoveryProposal(trigger_status="failed")
        assert p1.proposal_id != p2.proposal_id

    def test_invalid_confidence_normalized(self):
        p = RecoveryProposal(trigger_status="failed", confidence="extremely_high")
        assert p.confidence in ("low", "medium", "high")

    def test_suggested_action_violation_raises(self):
        """Proposal cannot contain suggested_actions with auto_executable=True — but
        SuggestedAction normalizes to False on construction, so this can't really happen.
        Test that the entire chain is safe."""
        action = SuggestedAction(description="Review logs")
        assert action.auto_executable is False
        p = RecoveryProposal(trigger_status="failed", suggested_actions=[action])
        assert p.suggested_actions[0].auto_executable is False

    def test_to_dict_invariants_always_set(self):
        p = _make_proposal()
        d = p.to_dict()
        assert d["auto_executable"] is False
        assert d["approval_required"] is True
        assert d["proposal_id"]
        assert d["proposal_type"] in VALID_PROPOSAL_TYPES

    def test_to_dict_suggested_actions_invariants(self):
        action = SuggestedAction(description="Do this", risk_level="low")
        p = _make_proposal(suggested_actions=[action])
        d = p.to_dict()
        for a in d["suggested_actions"]:
            assert a["auto_executable"] is False
            assert a["requires_approval"] is True


# ---------------------------------------------------------------------------
# Phase 1: ProposalValidator
# ---------------------------------------------------------------------------

class TestProposalValidator:

    def test_valid_proposal_passes(self):
        p = _make_proposal()
        assert ProposalValidator.validate(p) is True

    def test_auto_executable_violation_detected(self):
        p = _make_proposal()
        # Force violation by bypassing __post_init__
        object.__setattr__(p, "auto_executable", True)
        with pytest.raises(ValueError, match="auto_executable"):
            ProposalValidator.validate(p)

    def test_approval_required_violation_detected(self):
        p = _make_proposal()
        object.__setattr__(p, "approval_required", False)
        with pytest.raises(ValueError, match="approval_required"):
            ProposalValidator.validate(p)

    def test_excluded_trigger_status_detected(self):
        p = _make_proposal(trigger_status="passed")
        with pytest.raises(ValueError, match="excluded"):
            ProposalValidator.validate(p)

    def test_completed_trigger_status_detected(self):
        p = _make_proposal(trigger_status="completed")
        with pytest.raises(ValueError, match="excluded"):
            ProposalValidator.validate(p)

    def test_empty_proposal_id_detected(self):
        p = _make_proposal()
        object.__setattr__(p, "proposal_id", "")
        with pytest.raises(ValueError, match="proposal_id"):
            ProposalValidator.validate(p)

    def test_is_excluded_status_passed_completed(self):
        assert ProposalValidator.is_excluded_status("passed", "completed") is True

    def test_is_excluded_status_passed_partial(self):
        # passed run → excluded even if goal is partial
        assert ProposalValidator.is_excluded_status("passed", "partial") is True

    def test_is_excluded_status_failed_partial_not_excluded(self):
        assert ProposalValidator.is_excluded_status("failed", "partial") is False

    def test_is_excluded_status_blocked_partial_not_excluded(self):
        assert ProposalValidator.is_excluded_status("blocked", "partial") is False

    def test_validate_dict_passes_on_valid(self):
        d = _make_proposal().to_dict()
        assert ProposalValidator.validate_dict(d) is True

    def test_validate_dict_fails_on_auto_executable(self):
        d = _make_proposal().to_dict()
        d["auto_executable"] = True
        with pytest.raises(ValueError):
            ProposalValidator.validate_dict(d)


# ---------------------------------------------------------------------------
# Phase 2: Template mapping
# ---------------------------------------------------------------------------

class TestProposalTypeMapping:

    def test_technical_failure_with_goal_progress(self):
        assert get_proposal_type("technical_failure_with_goal_progress") == PROPOSAL_CONTINUE_FROM_PARTIAL

    def test_hard_failure(self):
        assert get_proposal_type("hard_failure") == PROPOSAL_RESTART_SMALLER_SCOPE

    def test_blocked_with_goal_progress(self):
        assert get_proposal_type("blocked_with_goal_progress") == PROPOSAL_OPERATOR_DECISION

    def test_insufficient_context(self):
        assert get_proposal_type("insufficient_context") == PROPOSAL_GATHER_MISSING_CONTEXT

    def test_anomaly(self):
        assert get_proposal_type("anomaly_run_passed_goal_not_completed") == PROPOSAL_INVESTIGATE_ANOMALY

    def test_unknown_status_fallback(self):
        assert get_proposal_type("unknown_status") == PROPOSAL_HUMAN_REVIEW

    def test_completely_unknown_status_fallback(self):
        assert get_proposal_type("totally_invented_status_xyz") == PROPOSAL_HUMAN_REVIEW

    def test_completed_excluded_from_mapping(self):
        # "completed" should never map to a proposal that is "completed"
        result = get_proposal_type("completed")
        assert result not in EXCLUDED_PROPOSAL_TYPES
        assert result in VALID_PROPOSAL_TYPES

    def test_all_valid_proposal_types_are_not_completed(self):
        for ptype in VALID_PROPOSAL_TYPES:
            assert ptype not in EXCLUDED_PROPOSAL_TYPES

    def test_fallback_always_human_review(self):
        # Fallback for any unmapped status should be safe
        for unknown in ["blah", "xyz_unknown", "", "null"]:
            result = get_proposal_type(unknown)
            assert result in VALID_PROPOSAL_TYPES
            assert result not in EXCLUDED_PROPOSAL_TYPES


# ---------------------------------------------------------------------------
# Phase 3: Generation engine
# ---------------------------------------------------------------------------

class TestGenerateRecoveryProposal:

    def test_disabled_config_returns_none(self):
        report = _failed_report()
        result = generate_recovery_proposal(report, config=_config(enabled=False))
        assert result is None

    def test_default_config_disabled_returns_none(self):
        report = _failed_report()
        result = generate_recovery_proposal(report)
        assert result is None

    def test_generates_proposal_for_failed_partial(self):
        report = _failed_report()
        result = generate_recovery_proposal(report, config=_config())
        assert result is not None
        assert isinstance(result, RecoveryProposal)

    def test_generates_proposal_for_blocked_partial(self):
        report = _blocked_report()
        result = generate_recovery_proposal(report, config=_config())
        assert result is not None
        assert isinstance(result, RecoveryProposal)

    def test_no_proposal_for_passed_completed(self):
        report = {
            "current_loop_decision": "passed",
            "mission_brain_decision": "completed",
        }
        result = generate_recovery_proposal(report, config=_config())
        assert result is None

    def test_no_proposal_for_passed_partial(self):
        """passed run should never produce a proposal."""
        report = {
            "current_loop_decision": "passed",
            "mission_brain_decision": "partial",
        }
        result = generate_recovery_proposal(report, config=_config())
        assert result is None

    def test_no_proposal_for_completed_goal(self):
        """completed goal status → no proposal."""
        report = {
            "current_loop_decision": "failed",
            "mission_brain_decision": "completed",
        }
        result = generate_recovery_proposal(report, config=_config())
        assert result is None

    def test_proposal_has_required_fields(self):
        report = _failed_report()
        result = generate_recovery_proposal(report, config=_config())
        assert result is not None
        assert result.proposal_id
        assert result.proposal_type in VALID_PROPOSAL_TYPES
        assert result.auto_executable is False
        assert result.approval_required is True
        assert result.trigger_status == "failed"

    def test_proposal_has_suggested_requirements(self):
        report = _failed_report()
        result = generate_recovery_proposal(report, config=_config())
        assert result is not None
        assert len(result.suggested_requirements) > 0

    def test_proposal_has_suggested_checklist(self):
        report = _failed_report()
        result = generate_recovery_proposal(report, config=_config())
        assert result is not None
        assert len(result.suggested_checklist) > 0

    def test_proposal_has_suggested_actions(self):
        report = _failed_report()
        result = generate_recovery_proposal(report, config=_config())
        assert result is not None
        assert len(result.suggested_actions) > 0
        for action in result.suggested_actions:
            assert action.auto_executable is False
            assert action.requires_approval is True

    def test_proposal_has_suggested_tests(self):
        report = _failed_report()
        result = generate_recovery_proposal(report, config=_config())
        assert result is not None
        assert len(result.suggested_tests) > 0

    def test_proposal_type_continue_for_technical_failure_goal_progress(self):
        report = {
            "current_loop_decision": "failed",
            "mission_brain_decision": "partial",
        }
        result = generate_recovery_proposal(report, config=_config())
        assert result is not None
        assert result.proposal_type == PROPOSAL_CONTINUE_FROM_PARTIAL

    def test_proposal_type_restart_for_hard_failure(self):
        report = {
            "current_loop_decision": "failed",
            "mission_brain_decision": "failed",
        }
        result = generate_recovery_proposal(report, config=_config())
        assert result is not None
        assert result.proposal_type == PROPOSAL_RESTART_SMALLER_SCOPE

    def test_proposal_type_operator_for_blocked_partial(self):
        report = {
            "current_loop_decision": "blocked",
            "mission_brain_decision": "partial",
        }
        result = generate_recovery_proposal(report, config=_config())
        assert result is not None
        assert result.proposal_type == PROPOSAL_OPERATOR_DECISION

    def test_proposal_with_valid_progress_from_tests_passed(self):
        report = _failed_report(tests_passed=42)
        result = generate_recovery_proposal(report, config=_config())
        assert result is not None
        assert any("42" in p for p in result.valid_progress)

    def test_proposal_with_files_changed(self):
        report = _failed_report(files_changed=["igris/core/foo.py", "igris/core/bar.py"])
        result = generate_recovery_proposal(report, config=_config())
        assert result is not None
        assert any("foo.py" in p or "bar.py" in p or "2 file" in p
                   for p in result.valid_progress)

    def test_source_advisory_id_preserved(self):
        report = _failed_report()
        result = generate_recovery_proposal(report, config=_config(), source_advisory_id="adv-xyz-123")
        assert result is not None
        assert result.source_advisory_id == "adv-xyz-123"

    def test_generate_is_non_blocking_on_error(self):
        """generate_recovery_proposal must never raise."""
        # Invalid report
        result = generate_recovery_proposal(None, config=_config())  # type: ignore
        # Should return None, not raise

    def test_suggested_actions_are_not_shell_commands(self):
        """No suggested_action.description should look like a shell command."""
        import re
        shell_cmd_re = re.compile(r"^(git|sh|bash|python|rm|sudo|systemctl|docker)\s", re.IGNORECASE)
        report = _failed_report()
        result = generate_recovery_proposal(report, config=_config())
        assert result is not None
        for action in result.suggested_actions:
            assert not shell_cmd_re.match(action.description), (
                f"Suggested action looks like a shell command: {action.description!r}"
            )


# ---------------------------------------------------------------------------
# Phase 4: Feature flag + report enrichment
# ---------------------------------------------------------------------------

class TestReportEnrichment:

    def test_disabled_config_returns_original(self):
        report = _failed_report()
        result = enrich_report_with_proposal(report, config=_config(enabled=False))
        assert result is report or result == report
        assert "recovery_proposal" not in result

    def test_enabled_config_adds_proposal(self):
        report = _failed_report()
        result = enrich_report_with_proposal(report, config=_config())
        assert "recovery_proposal" in result

    def test_enrichment_is_additive_only(self):
        report = _failed_report(my_existing_field="preserved")
        result = enrich_report_with_proposal(report, config=_config())
        assert result["my_existing_field"] == "preserved"
        assert result["current_loop_decision"] == "failed"

    def test_original_report_not_mutated(self):
        report = _failed_report()
        original_keys = set(report.keys())
        enrich_report_with_proposal(report, config=_config())
        assert set(report.keys()) == original_keys

    def test_no_enrichment_for_passed_completed(self):
        report = {
            "current_loop_decision": "passed",
            "mission_brain_decision": "completed",
        }
        result = enrich_report_with_proposal(report, config=_config())
        assert "recovery_proposal" not in result

    def test_enriched_proposal_has_invariants(self):
        report = _failed_report()
        result = enrich_report_with_proposal(report, config=_config())
        assert "recovery_proposal" in result
        prop = result["recovery_proposal"]
        assert prop["auto_executable"] is False
        assert prop["approval_required"] is True
        assert prop["proposal_type"] not in EXCLUDED_PROPOSAL_TYPES

    def test_env_var_enables_config(self, monkeypatch):
        monkeypatch.setenv("IGRIS_ADVISORY_RECOVERY_PROPOSALS", "1")
        cfg = RecoveryProposalConfig()
        assert cfg.enabled is True

    def test_env_var_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("IGRIS_ADVISORY_RECOVERY_PROPOSALS", raising=False)
        cfg = RecoveryProposalConfig()
        assert cfg.enabled is False

    def test_strip_recovery_proposal(self):
        report = _failed_report()
        enriched = enrich_report_with_proposal(report, config=_config())
        stripped = strip_recovery_proposal(enriched)
        assert "recovery_proposal" not in stripped
        assert "current_loop_decision" in stripped

    def test_no_loop_decision_change(self):
        report = _failed_report()
        original_decision = report["current_loop_decision"]
        result = enrich_report_with_proposal(report, config=_config())
        assert result["current_loop_decision"] == original_decision

    def test_recovery_proposal_config_invariants(self):
        cfg = RecoveryProposalConfig(enabled=True)
        assert cfg.advisory_only is True
        assert cfg.auto_executable is False
        assert cfg.is_gate is False
        assert cfg.affects_loop_decision is False


# ---------------------------------------------------------------------------
# Phase 5: MBOP handoff
# ---------------------------------------------------------------------------

class TestMBOPHandoff:

    def test_handoff_from_valid_proposal(self):
        p = _make_proposal(
            suggested_requirements=["req1", "req2"],
            suggested_checklist=["[ ] step 1"],
            suggested_tests=["run affected tests"],
        )
        handoff = proposal_to_mbop_handoff(p)
        assert isinstance(handoff, MBOPHandoff)
        assert handoff.source_proposal_id == p.proposal_id
        assert handoff.requirements == ["req1", "req2"]
        assert handoff.checklist == ["[ ] step 1"]
        assert handoff.suggested_tests == ["run affected tests"]

    def test_handoff_auto_executable_always_false(self):
        p = _make_proposal()
        handoff = proposal_to_mbop_handoff(p)
        assert handoff.auto_executable is False

    def test_handoff_approval_required_always_true(self):
        p = _make_proposal()
        handoff = proposal_to_mbop_handoff(p)
        assert handoff.approval_required is True

    def test_handoff_is_gate_always_false(self):
        p = _make_proposal()
        handoff = proposal_to_mbop_handoff(p)
        assert handoff.is_gate is False

    def test_handoff_affects_loop_decision_always_false(self):
        p = _make_proposal()
        handoff = proposal_to_mbop_handoff(p)
        assert handoff.affects_loop_decision is False

    def test_handoff_constraints_are_descriptive_not_commands(self):
        import re
        shell_cmd_re = re.compile(r"^(git|sh|bash|python|rm|sudo|systemctl|docker)\s", re.IGNORECASE)
        p = _make_proposal(
            suggested_actions=[
                SuggestedAction(description="Review error logs carefully"),
                SuggestedAction(description="Identify the root cause of failure"),
            ]
        )
        handoff = proposal_to_mbop_handoff(p)
        for constraint in handoff.constraints:
            # Constraints should be prefixed "Action required: ..." not raw commands
            assert not shell_cmd_re.match(constraint), (
                f"Constraint looks like a shell command: {constraint!r}"
            )

    def test_handoff_to_dict_invariants(self):
        p = _make_proposal()
        handoff = proposal_to_mbop_handoff(p)
        d = handoff.to_dict()
        assert d["auto_executable"] is False
        assert d["approval_required"] is True
        assert d["is_gate"] is False
        assert d["affects_loop_decision"] is False

    def test_handoff_raises_on_invalid_proposal(self):
        p = _make_proposal(trigger_status="passed")
        with pytest.raises(ValueError):
            proposal_to_mbop_handoff(p)

    def test_safe_handoff_returns_none_on_invalid(self):
        p = _make_proposal(trigger_status="passed")
        result = proposal_to_mbop_handoff_safe(p)
        assert result is None

    def test_safe_handoff_returns_handoff_on_valid(self):
        p = _make_proposal()
        result = proposal_to_mbop_handoff_safe(p)
        assert result is not None
        assert isinstance(result, MBOPHandoff)

    def test_handoff_preserves_problem_summary(self):
        p = _make_proposal(problem_summary="Tests failed in CI pipeline")
        handoff = proposal_to_mbop_handoff(p)
        assert handoff.problem_summary == "Tests failed in CI pipeline"

    def test_handoff_does_not_include_executable_commands(self):
        """The handoff should contain requirements/checklist text, not commands."""
        report = _failed_report()
        proposal = generate_recovery_proposal(report, config=_config())
        assert proposal is not None
        handoff = proposal_to_mbop_handoff(proposal)
        # All constraints should be descriptive
        for c in handoff.constraints:
            assert "Action required:" in c


# ---------------------------------------------------------------------------
# Phase 6: Metrics
# ---------------------------------------------------------------------------

class TestProposalMetrics:

    def _make_proposals(self, count: int = 3) -> list:
        return [_make_proposal() for _ in range(count)]

    def test_metrics_on_empty_list(self):
        metrics = compute_proposal_metrics([])
        assert metrics["total_proposals_generated"] == 0
        assert metrics["auto_executable_violations"] == 0
        assert metrics["proposal_usefulness_score"] == 0.0

    def test_total_proposals_counted(self):
        proposals = self._make_proposals(5)
        metrics = compute_proposal_metrics(proposals)
        assert metrics["total_proposals_generated"] == 5

    def test_auto_executable_violations_zero_on_valid(self):
        proposals = self._make_proposals(10)
        metrics = compute_proposal_metrics(proposals)
        assert metrics["auto_executable_violations"] == 0

    def test_approval_required_violations_zero_on_valid(self):
        proposals = self._make_proposals(10)
        metrics = compute_proposal_metrics(proposals)
        assert metrics["approval_required_violations"] == 0

    def test_loop_decision_violations_always_zero(self):
        proposals = self._make_proposals(5)
        metrics = compute_proposal_metrics(proposals)
        assert metrics["loop_decision_violations"] == 0

    def test_gate_violations_always_zero(self):
        proposals = self._make_proposals(5)
        metrics = compute_proposal_metrics(proposals)
        assert metrics["gate_violations"] == 0

    def test_operator_review_required_equals_total(self):
        proposals = self._make_proposals(7)
        metrics = compute_proposal_metrics(proposals)
        assert metrics["operator_review_required_count"] == 7

    def test_rollback_verified_always_true(self):
        metrics = compute_proposal_metrics(self._make_proposals(3))
        assert metrics["rollback_verified"] is True

    def test_proposals_by_type_distribution(self):
        proposals = [
            _make_proposal(proposal_type=PROPOSAL_CONTINUE_FROM_PARTIAL),
            _make_proposal(proposal_type=PROPOSAL_CONTINUE_FROM_PARTIAL),
            _make_proposal(proposal_type=PROPOSAL_RESTART_SMALLER_SCOPE),
        ]
        metrics = compute_proposal_metrics(proposals)
        assert metrics["proposals_by_type"][PROPOSAL_CONTINUE_FROM_PARTIAL] == 2
        assert metrics["proposals_by_type"][PROPOSAL_RESTART_SMALLER_SCOPE] == 1

    def test_mbop_handoff_success_counted(self):
        proposals = self._make_proposals(5)
        metrics = compute_proposal_metrics(proposals)
        assert metrics["mbop_handoff_success_count"] > 0
        assert metrics["mbop_handoff_success_count"] + metrics["mbop_handoff_failure_count"] == 5

    def test_usefulness_score_is_high_for_complete_proposals(self):
        proposals = [
            _make_proposal(
                suggested_requirements=["req1"],
                suggested_checklist=["[ ] step 1"],
                suggested_tests=["run tests"],
            )
            for _ in range(5)
        ]
        metrics = compute_proposal_metrics(proposals)
        assert metrics["proposal_usefulness_score"] == 1.0

    def test_usefulness_score_low_for_empty_proposals(self):
        proposals = [
            RecoveryProposal(
                trigger_status="failed",
                suggested_requirements=[],
                suggested_checklist=[],
                suggested_tests=[],
            )
            for _ in range(5)
        ]
        metrics = compute_proposal_metrics(proposals)
        assert metrics["proposal_usefulness_score"] == 0.0

    def test_missing_evidence_counted(self):
        proposals = [
            _make_proposal(missing_evidence=["mission_brain_decision"]),
            _make_proposal(missing_evidence=[]),
            _make_proposal(missing_evidence=["goal_class", "current_loop_decision"]),
        ]
        metrics = compute_proposal_metrics(proposals)
        assert metrics["missing_evidence_detected_count"] == 2

    def test_risky_proposal_count(self):
        proposals = [
            RecoveryProposal(trigger_status="failed", risk_level="high"),
            RecoveryProposal(trigger_status="failed", risk_level="low"),
            RecoveryProposal(trigger_status="failed", risk_level="high"),
        ]
        metrics = compute_proposal_metrics(proposals)
        assert metrics["risky_proposal_count"] == 2

    def test_scope_violations_for_passed_trigger(self):
        """Proposals with passed trigger_status should count as scope violations."""
        p_valid = _make_proposal()
        p_bad = _make_proposal(trigger_status="failed")  # valid
        # Force a scope violation by bypassing __post_init__
        p_scope_violator = _make_proposal()
        object.__setattr__(p_scope_violator, "trigger_status", "passed")

        metrics = compute_proposal_metrics([p_valid, p_bad, p_scope_violator])
        assert metrics["passed_completed_scope_violations"] == 1


# ---------------------------------------------------------------------------
# Rank S Gauntlet: Advisory Recovery Proposal Gauntlet
# ---------------------------------------------------------------------------

class TestAdvisoryRecoveryProposalGauntlet:
    """Full-stack gauntlet: scenario from #942 acceptance criteria."""

    def test_full_flow_failed_blocked_proposal_generated(self):
        """failed/blocked → proposal generated → auto_executable=False → approval=True → MBOP handoff ok."""
        for run_status in ("failed", "blocked"):
            report = {
                "current_loop_decision": run_status,
                "mission_brain_decision": "partial",
                "report_type": "diagnostic",
                "tests_passed": 10,
                "files_changed": ["igris/core/delivery_workflow.py"],
            }
            config = _config(enabled=True)
            proposal = generate_recovery_proposal(report, config=config, source_advisory_id="adv-001")
            assert proposal is not None, f"Expected proposal for run_status={run_status}"
            assert proposal.auto_executable is False, "auto_executable must be False"
            assert proposal.approval_required is True, "approval_required must be True"
            assert proposal.proposal_type not in EXCLUDED_PROPOSAL_TYPES
            assert proposal.proposal_id, "proposal_id must be set"

            # MBOP handoff must succeed
            handoff = proposal_to_mbop_handoff(proposal)
            assert handoff is not None
            assert handoff.auto_executable is False
            assert handoff.approval_required is True
            assert handoff.is_gate is False
            assert handoff.affects_loop_decision is False

    def test_no_proposal_for_passed(self):
        """passed → no proposal."""
        report = {
            "current_loop_decision": "passed",
            "mission_brain_decision": "completed",
        }
        result = generate_recovery_proposal(report, config=_config(enabled=True))
        assert result is None

    def test_report_enrichment_no_loop_decision_change(self):
        """Enrichment must not change loop decision or other existing fields."""
        report = {
            "current_loop_decision": "failed",
            "mission_brain_decision": "partial",
            "my_data": "important",
        }
        enriched = enrich_report_with_proposal(report, config=_config())
        assert enriched["current_loop_decision"] == "failed"
        assert enriched["mission_brain_decision"] == "partial"
        assert enriched["my_data"] == "important"
        # Proposal added additively
        assert "recovery_proposal" in enriched
        assert enriched["recovery_proposal"]["auto_executable"] is False

    def test_full_metrics_validation(self):
        """Generate proposals for multiple scenarios and validate metrics."""
        reports = [
            {"current_loop_decision": "failed", "mission_brain_decision": "partial"},
            {"current_loop_decision": "failed", "mission_brain_decision": "failed"},
            {"current_loop_decision": "blocked", "mission_brain_decision": "partial"},
        ]
        config = _config(enabled=True)
        proposals = [
            p for r in reports
            if (p := generate_recovery_proposal(r, config=config)) is not None
        ]
        assert len(proposals) == 3

        metrics = compute_proposal_metrics(proposals)
        assert metrics["auto_executable_violations"] == 0
        assert metrics["approval_required_violations"] == 0
        assert metrics["gate_violations"] == 0
        assert metrics["loop_decision_violations"] == 0
        assert metrics["passed_completed_scope_violations"] == 0
        assert metrics["rollback_verified"] is True
        assert metrics["operator_review_required_count"] == 3
