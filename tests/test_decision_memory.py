"""Tests for igris.core.decision_memory."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from igris.core.decision_memory import (
    DecisionEvent,
    explain_memory_constraints,
    get_blocked_families_from_memory,
    get_recent_decisions,
    get_recent_failures,
    get_saturated_families,
    record_decision,
    record_failure,
    record_remediation_attempt,
    record_saturation,
    should_avoid_family,
)


@pytest.fixture
def project_dir(tmp_path: Path) -> str:
    (tmp_path / ".igris" / "memory").mkdir(parents=True)
    return str(tmp_path)


# ---- Record & retrieve ----


class TestRecordDecision:
    def test_record_and_retrieve(self, project_dir: str) -> None:
        record_decision("Chose approach A", family="code", outcome="success", project_root=project_dir)
        events = get_recent_decisions(limit=10, project_root=project_dir)
        assert len(events) == 1
        assert events[0]["title"] == "Chose approach A"
        assert events[0]["family"] == "code"
        assert events[0]["outcome"] == "success"

    def test_multiple_decisions(self, project_dir: str) -> None:
        record_decision("D1", project_root=project_dir)
        record_decision("D2", project_root=project_dir)
        record_decision("D3", project_root=project_dir)
        events = get_recent_decisions(limit=10, project_root=project_dir)
        assert len(events) == 3

    def test_limit(self, project_dir: str) -> None:
        for i in range(10):
            record_decision(f"D{i}", project_root=project_dir)
        events = get_recent_decisions(limit=3, project_root=project_dir)
        assert len(events) == 3
        assert events[0]["title"] == "D7"


class TestRecordFailure:
    def test_record_and_retrieve(self, project_dir: str) -> None:
        record_failure("Test failed", family="test", reason="assertion error", project_root=project_dir)
        events = get_recent_failures(limit=10, project_root=project_dir)
        assert len(events) == 1
        assert events[0]["title"] == "Test failed"
        assert events[0]["outcome"] == "failure"

    def test_failure_persists(self, project_dir: str) -> None:
        record_failure("F1", family="code", project_root=project_dir)
        path = Path(project_dir) / ".igris" / "memory" / "failures.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert len(data) == 1


class TestRecordSaturation:
    def test_record_saturation(self, project_dir: str) -> None:
        record_saturation("testing", reason="too many test tasks", project_root=project_dir)
        families = get_saturated_families(project_root=project_dir)
        assert "testing" in families

    def test_multiple_families(self, project_dir: str) -> None:
        record_saturation("testing", project_root=project_dir)
        record_saturation("code", project_root=project_dir)
        families = get_saturated_families(project_root=project_dir)
        assert "testing" in families
        assert "code" in families


class TestRecordRemediation:
    def test_record_remediation(self, project_dir: str) -> None:
        e = record_remediation_attempt("Fix approach", family="fix", outcome="pending", project_root=project_dir)
        assert e.event_type == "remediation"
        assert e.outcome == "pending"


# ---- should_avoid_family ----


class TestShouldAvoidFamily:
    def test_saturated_family_avoided(self, project_dir: str) -> None:
        record_saturation("testing", project_root=project_dir)
        assert should_avoid_family("testing", project_root=project_dir) is True

    def test_unsaturated_family_allowed(self, project_dir: str) -> None:
        assert should_avoid_family("code", project_root=project_dir) is False

    def test_repeated_failures_avoided(self, project_dir: str) -> None:
        for _ in range(3):
            record_failure("fail", family="code", project_root=project_dir)
        assert should_avoid_family("code", project_root=project_dir) is True

    def test_few_failures_allowed(self, project_dir: str) -> None:
        record_failure("fail", family="code", project_root=project_dir)
        assert should_avoid_family("code", project_root=project_dir) is False


# ---- explain_memory_constraints ----


class TestExplainMemoryConstraints:
    def test_no_constraints(self, project_dir: str) -> None:
        constraints = explain_memory_constraints(project_root=project_dir)
        assert constraints["avoid_families"] == []
        assert "No constraints" in constraints["recommendation"]

    def test_with_saturation(self, project_dir: str) -> None:
        record_saturation("testing", project_root=project_dir)
        constraints = explain_memory_constraints(project_root=project_dir)
        assert "testing" in constraints["avoid_families"]
        assert "testing" in constraints["recommendation"]

    def test_with_failures(self, project_dir: str) -> None:
        for _ in range(3):
            record_failure("fail", family="code", project_root=project_dir)
        constraints = explain_memory_constraints(project_root=project_dir)
        assert "code" in constraints["avoid_families"]

    def test_counts(self, project_dir: str) -> None:
        record_decision("D1", project_root=project_dir)
        record_failure("F1", project_root=project_dir)
        record_remediation_attempt("R1", project_root=project_dir)
        constraints = explain_memory_constraints(project_root=project_dir)
        assert constraints["recent_decision_count"] == 1
        assert constraints["recent_failure_count"] == 1
        assert constraints["remediation_count"] == 1


# ---- Secret redaction ----


class TestSecretRedaction:
    def test_title_redacted(self, project_dir: str) -> None:
        record_decision("API_KEY=sk-abc123 decision", project_root=project_dir)
        events = get_recent_decisions(project_root=project_dir)
        assert "sk-abc123" not in events[0]["title"]

    def test_description_redacted(self, project_dir: str) -> None:
        record_failure("fail", description="token=ghp_1234567890abcdef", project_root=project_dir)
        events = get_recent_failures(project_root=project_dir)
        assert "ghp_1234567890abcdef" not in events[0]["description"]

    def test_reason_redacted(self, project_dir: str) -> None:
        record_failure("fail", reason="password=mysecret123", project_root=project_dir)
        events = get_recent_failures(project_root=project_dir)
        assert "mysecret123" not in events[0]["reason"]


# ---- DecisionEvent model ----


class TestDecisionEventModel:
    def test_to_dict(self) -> None:
        e = DecisionEvent(title="T", family="code", outcome="success")
        d = e.to_dict()
        assert d["title"] == "T"
        assert d["event_type"] == "decision"

    def test_from_dict(self) -> None:
        e = DecisionEvent.from_dict({"title": "X", "family": "test", "outcome": "failure"})
        assert e.title == "X"
        assert e.outcome == "failure"

    def test_roundtrip(self) -> None:
        e = DecisionEvent(title="RT", family="fix", reason="because")
        d = e.to_dict()
        e2 = DecisionEvent.from_dict(d)
        assert e2.title == e.title
        assert e2.family == e.family


# ---- Integration with blocked families ----


class TestBlockedFamiliesIntegration:
    def test_get_blocked_families_empty(self, project_dir: str) -> None:
        blocked = get_blocked_families_from_memory(project_root=project_dir)
        assert blocked == []

    def test_get_blocked_families_with_saturation(self, project_dir: str) -> None:
        record_saturation("testing", project_root=project_dir)
        blocked = get_blocked_families_from_memory(project_root=project_dir)
        assert "testing" in blocked

    def test_get_blocked_families_with_failures(self, project_dir: str) -> None:
        for _ in range(3):
            record_failure("f", family="code", project_root=project_dir)
        blocked = get_blocked_families_from_memory(project_root=project_dir)
        assert "code" in blocked
