"""Tests for JarvisCoreGauntlet — Final Acceptance Gauntlet (#1249)."""
from __future__ import annotations
import json
import pytest


# ── Init / health ─────────────────────────────────────────────────────────────

def test_gauntlet_initializes(tmp_path):
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    g = JarvisCoreGauntlet(project_root=tmp_path, output_dir=tmp_path / "reports")
    assert g is not None
    assert g.project_root == tmp_path


def test_gauntlet_healthcheck(tmp_path):
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    g = JarvisCoreGauntlet(project_root=tmp_path, output_dir=tmp_path / "reports")
    h = g.healthcheck()
    assert h["ok"] is True
    assert "project_root" in h


# ── Individual checks ─────────────────────────────────────────────────────────

def test_security_gate_check_passes(tmp_path):
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    g = JarvisCoreGauntlet(project_root=tmp_path)
    result = g.run_check("security_gate")
    assert result.passed is True, f"security_gate failed: {result.errors}"
    assert result.status == "passed"
    assert len(result.evidence) > 0


def test_memory_persistence_check_passes(tmp_path):
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    g = JarvisCoreGauntlet(project_root=tmp_path)
    result = g.run_check("memory_persistence")
    assert result.passed is True, f"memory_persistence failed: {result.errors}"
    assert result.status == "passed"


def test_request_routing_check_passes(tmp_path):
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    g = JarvisCoreGauntlet(project_root=tmp_path)
    result = g.run_check("request_routing")
    assert result.passed is True, f"request_routing failed: {result.errors}"
    assert result.status == "passed"


def test_context_aggregation_check_passes(tmp_path):
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    g = JarvisCoreGauntlet(project_root=tmp_path)
    result = g.run_check("context_aggregation")
    assert result.passed is True, f"context_aggregation failed: {result.errors}"
    assert result.status == "passed"


def test_mission_first_check_passes(tmp_path):
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    g = JarvisCoreGauntlet(project_root=tmp_path)
    result = g.run_check("mission_first")
    assert result.passed is True, f"mission_first failed: {result.errors}"
    assert result.status == "passed"


def test_verification_evidence_check_passes(tmp_path):
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    g = JarvisCoreGauntlet(project_root=tmp_path)
    result = g.run_check("verification_evidence")
    assert result.passed is True, f"verification_evidence failed: {result.errors}"
    assert result.status == "passed"


def test_reflection_learning_check_passes(tmp_path):
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    g = JarvisCoreGauntlet(project_root=tmp_path)
    result = g.run_check("reflection_learning")
    assert result.passed is True, f"reflection_learning failed: {result.errors}"
    assert result.status == "passed"


def test_ml_light_shadow_check_passes(tmp_path):
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    g = JarvisCoreGauntlet(project_root=tmp_path)
    result = g.run_check("ml_light_shadow")
    assert result.passed is True, f"ml_light_shadow failed: {result.errors}"
    assert result.status == "passed"
    # Shadow invariants via evidence
    for ev in result.evidence:
        if "ranker_changed_decision" in ev:
            assert ev["ranker_changed_decision"] is False
        if "intent_changed_decision" in ev:
            assert ev["intent_changed_decision"] is False
        if "strategy_changed_decision" in ev:
            assert ev["strategy_changed_decision"] is False
        if "coordinator_shadow_only" in ev:
            assert ev["coordinator_shadow_only"] is True
            assert ev["coordinator_changed_decision"] is False


def test_end_to_end_jarvis_flow_passes(tmp_path):
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    g = JarvisCoreGauntlet(project_root=tmp_path)
    result = g.run_check("end_to_end_jarvis_flow")
    assert result.passed is True, f"end_to_end failed: {result.errors}"
    assert result.status == "passed"
    # Shadow invariant
    for ev in result.evidence:
        if "shadow_only" in ev:
            assert ev["shadow_only"] is True
            assert ev["shadow_changed_decision"] is False


def test_secret_redaction_global(tmp_path):
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    g = JarvisCoreGauntlet(project_root=tmp_path)
    result = g.run_check("secret_redaction_global")
    assert result.passed is True, f"redaction failed: {result.errors}"
    # Verify fake secrets not in result dict
    output = json.dumps(result.to_dict())
    for fake in [
        "FAKE_TOKEN_GAUNTLET_1234567890",
        "FAKE_PASSWORD_GAUNTLET_1234567890",
        "FAKE_API_KEY_GAUNTLET_1234567890",
        "FAKE_PASSPHRASE_GAUNTLET_1234567890",
    ]:
        assert fake not in output, f"Found raw secret {fake} in check result"


# ── Full run ──────────────────────────────────────────────────────────────────

def test_run_all_passes(tmp_path):
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    g = JarvisCoreGauntlet(project_root=tmp_path, output_dir=tmp_path / "reports")
    report = g.run_all()
    assert report.passed is True, (
        f"Gauntlet failed. Status: {report.status}\n"
        f"Failed checks: {[c.check_id for c in report.checks if not c.passed]}\n"
        f"Errors: {report.errors}"
    )
    assert report.status == "passed"
    assert report.metrics["total_checks"] == 14  # 13 previous + memory_cross_session (#1294)
    assert report.metrics["passed_checks"] == 14


# ── write_report ──────────────────────────────────────────────────────────────

def test_write_report_json_and_markdown(tmp_path):
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    g = JarvisCoreGauntlet(project_root=tmp_path, output_dir=tmp_path / "reports")
    report = g.run_all()
    write_r = g.write_report(report)
    assert write_r["ok"] is True

    json_path = tmp_path / "reports" / "jarvis_core_gauntlet_report.json"
    md_path = tmp_path / "reports" / "jarvis_core_gauntlet_report.md"
    assert json_path.exists(), "JSON report not written"
    assert md_path.exists(), "Markdown report not written"

    # JSON is valid
    data = json.loads(json_path.read_text())
    assert data["target"] == "jarvis-core-ready"
    assert "checks" in data
    assert "metrics" in data
    assert "status" in data

    # Markdown contains expected sections
    md = md_path.read_text()
    assert "# Jarvis Core Final Acceptance Gauntlet" in md
    assert "jarvis-core-ready" in md
    assert "## Checks" in md


def test_report_no_raw_secret_in_json(tmp_path):
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    g = JarvisCoreGauntlet(project_root=tmp_path, output_dir=tmp_path / "reports")
    report = g.run_all()
    g.write_report(report)

    json_path = tmp_path / "reports" / "jarvis_core_gauntlet_report.json"
    content = json_path.read_text()
    for fake in [
        "FAKE_TOKEN_GAUNTLET_1234567890",
        "FAKE_PASSWORD_GAUNTLET_1234567890",
    ]:
        assert fake not in content, f"Raw secret {fake} found in JSON report"


# ── Failure behaviour ─────────────────────────────────────────────────────────

def test_report_failed_if_mandatory_check_fails(tmp_path):
    import unittest.mock as mock
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet, GauntletStatus
    g = JarvisCoreGauntlet(project_root=tmp_path, output_dir=tmp_path / "reports")

    # Patch one mandatory check to fail
    def _failing(r):
        r.passed = False
        r.status = GauntletStatus.FAILED.value
        r.errors.append("simulated_failure")
        r.summary = "Simulated check failure"

    with mock.patch.object(g, "_check_security_gate", _failing):
        report = g.run_all()

    assert report.passed is False
    assert report.status == "failed"
    failed_ids = [c.check_id for c in report.checks if not c.passed]
    assert "security_gate" in failed_ids


def test_no_silent_except_behavior(tmp_path):
    """Gauntlet must NOT swallow exceptions silently — they appear in check errors."""
    import unittest.mock as mock
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    g = JarvisCoreGauntlet(project_root=tmp_path, output_dir=tmp_path / "reports")

    def _boom(r):
        raise RuntimeError("unexpected_crash")

    with mock.patch.object(g, "_check_security_gate", _boom):
        result = g.run_check("security_gate")

    assert result.passed is False
    assert any("unexpected_crash" in e for e in result.errors)
    assert result.status == "failed"


# ── Data class contracts ──────────────────────────────────────────────────────

def test_gauntlet_check_result_to_dict():
    from igris.core.jarvis_core_gauntlet import GauntletCheckResult, GauntletStatus
    c = GauntletCheckResult(
        check_id="test", name="Test Check",
        status=GauntletStatus.PASSED.value, passed=True,
        summary="all good"
    )
    d = c.to_dict()
    for key in ("check_id", "name", "status", "passed", "summary",
                 "evidence", "warnings", "errors", "duration_ms"):
        assert key in d


def test_gauntlet_report_markdown_contains_required_sections(tmp_path):
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    g = JarvisCoreGauntlet(project_root=tmp_path, output_dir=tmp_path / "reports")
    report = g.run_all()
    md = report.markdown()
    for section in ["# Jarvis Core Final Acceptance Gauntlet", "## Checks",
                     "## Summary", "## Next Steps", "jarvis-core-ready"]:
        assert section in md, f"Missing section: {section}"


# ── auth_enrollment_login_flow (#1272 PR5) ────────────────────────────────────

def test_gauntlet_auth_flow_passes(tmp_path):
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    g = JarvisCoreGauntlet(project_root=tmp_path)
    result = g.run_check("auth_enrollment_login_flow")
    assert result.passed is True, f"auth flow failed: {result.errors}"


def test_gauntlet_auth_flow_no_raw_password_or_token(tmp_path):
    """Ensure gauntlet check output contains no raw password or session token."""
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    g = JarvisCoreGauntlet(project_root=tmp_path)
    result = g.run_check("auth_enrollment_login_flow")
    output = json.dumps(result.to_dict())
    # The FAKE_PW used internally in the check must not appear in the serialised result
    assert "FAKE_PASSWORD_GAUNTLET_AUTH" not in output, \
        "Raw fake password found in gauntlet check result"


def test_gauntlet_includes_auth_check_in_mandatory():
    from igris.core.jarvis_core_gauntlet import JarvisCoreGauntlet
    assert "auth_enrollment_login_flow" in JarvisCoreGauntlet.MANDATORY_CHECKS
