"""Tests for subprocess bypass audit (#1322 Phase 1)."""
from igris.core.subprocess_audit_1322 import (
    AUTHORIZED_MODULES,
    CLASSIFICATION,
    AuditSummary,
    run_audit,
)


class TestSubprocessAudit:
    """Tests for the subprocess audit classification."""

    def test_audit_runs_without_error(self) -> None:
        """run_audit() should return a valid AuditSummary."""
        summary = run_audit()
        assert isinstance(summary, AuditSummary)
        assert summary.total_calls > 0

    def test_authorized_modules_defined(self) -> None:
        """AUTHORIZED_MODULES should contain the 4 authorized modules."""
        assert "tool_runtime.py" in AUTHORIZED_MODULES
        assert "safe_commands.py" in AUTHORIZED_MODULES
        assert "devops_manager.py" in AUTHORIZED_MODULES
        assert "supervisor_backend.py" in AUTHORIZED_MODULES

    def test_all_calls_classified(self) -> None:
        """Every call in CLASSIFICATION should have a classification."""
        for filename, calls in CLASSIFICATION.items():
            for call in calls:
                assert "classification" in call, f"Missing classification in {filename} line {call.get('line')}"
                assert call["classification"] in ("INFRASTRUCTURE", "MIGRATE", "WRAPPER"), \
                    f"Invalid classification '{call['classification']}' in {filename}"

    def test_infrastructure_calls_present(self) -> None:
        """There should be infrastructure-classified calls (git, file system)."""
        summary = run_audit()
        assert summary.infrastructure_calls > 0
        # Git operations should be the majority of infrastructure calls
        assert summary.infrastructure_calls > summary.migrate_calls

    def test_migrate_calls_identified(self) -> None:
        """There should be calls identified for migration to ToolRuntime."""
        summary = run_audit()
        assert summary.migrate_calls > 0
        # mbop_runner and smw_actions should have migrate calls
        migrate_files = [
            f for f, calls in CLASSIFICATION.items()
            if any(c["classification"] == "MIGRATE" for c in calls)
        ]
        assert "mbop_runner.py" in migrate_files
        assert "smw_actions.py" in migrate_files

    def test_no_unclassified_calls(self) -> None:
        """All calls should be classified (no UNCLASSIFIED)."""
        summary = run_audit()
        assert summary.unclassified_calls == 0

    def test_delivery_workflow_is_infrastructure(self) -> None:
        """delivery_workflow.py calls should all be INFRASTRUCTURE (git ops)."""
        calls = CLASSIFICATION.get("delivery_workflow.py", [])
        assert len(calls) == 20
        for call in calls:
            assert call["classification"] == "INFRASTRUCTURE", \
                f"delivery_workflow line {call['line']} should be INFRASTRUCTURE"

    def test_ci_repair_loop_is_infrastructure(self) -> None:
        """ci_repair_loop.py calls should all be INFRASTRUCTURE (CI/devops)."""
        calls = CLASSIFICATION.get("ci_repair_loop.py", [])
        assert len(calls) == 11
        for call in calls:
            assert call["classification"] == "INFRASTRUCTURE"

    def test_audit_summary_totals(self) -> None:
        """Audit summary totals should be consistent."""
        summary = run_audit()
        assert summary.total_calls == summary.infrastructure_calls + summary.migrate_calls + summary.wrapper_calls
        assert summary.total_calls == 73  # 79 total - 6 authorized = 73 unauthorized

    def test_each_call_has_purpose(self) -> None:
        """Every classified call should have a purpose description."""
        for filename, calls in CLASSIFICATION.items():
            for call in calls:
                assert "purpose" in call, f"Missing purpose in {filename} line {call.get('line')}"
                assert len(call["purpose"]) > 0
