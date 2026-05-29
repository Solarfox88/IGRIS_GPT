"""Tests for igris/core/proactive_engine.py (issue #526)."""
from __future__ import annotations

import time

import pytest

from igris.core.proactive_engine import ProactiveConfig, ProactiveEngine


def _engine(tmp_path, **kwargs):
    config = ProactiveConfig(**kwargs) if kwargs else ProactiveConfig()
    return ProactiveEngine(str(tmp_path), config=config)


class TestProactiveEngine:
    def test_disabled_returns_empty(self, tmp_path):
        engine = _engine(tmp_path, enabled=False)
        events = engine.scan(
            {"run_failed": {"issue": "540", "reason": "timeout"}},
            authorized_scopes=["*"],
            trust_level="admin",
        )
        assert events == []

    def test_untrusted_gets_nothing(self, tmp_path):
        engine = _engine(tmp_path)
        events = engine.scan(
            {"ci_broken": True, "branch": "main"},
            authorized_scopes=["*"],
            trust_level="untrusted",
        )
        assert events == []

    def test_run_failed_emitted_for_admin(self, tmp_path):
        engine = _engine(tmp_path, min_urgency=0.0, min_interval_sec=0)
        events = engine.scan(
            {"run_failed": {"issue": "540", "reason": "timeout"}},
            authorized_scopes=["*"],
            trust_level="admin",
        )
        types = [e.event_type for e in events]
        assert "run_failed" in types

    def test_ci_broken_emitted(self, tmp_path):
        engine = _engine(tmp_path, min_urgency=0.0, min_interval_sec=0)
        events = engine.scan(
            {"ci_broken": True, "branch": "feature"},
            authorized_scopes=["*"],
            trust_level="trusted",
        )
        types = [e.event_type for e in events]
        assert "ci_broken" in types

    def test_resource_degraded_emitted(self, tmp_path):
        engine = _engine(tmp_path, min_urgency=0.0, min_interval_sec=0)
        events = engine.scan(
            {"degraded_resources": [{"name": "server_1", "reason": "healthcheck failed"}]},
            authorized_scopes=["*"],
            trust_level="trusted",
        )
        types = [e.event_type for e in events]
        assert "resource_degraded" in types

    def test_scope_filter_excludes_unauthorized_resource(self, tmp_path):
        engine = _engine(tmp_path, min_urgency=0.0, min_interval_sec=0)
        events = engine.scan(
            {"run_failed": {"issue": "server_2", "reason": "crash"}},
            authorized_scopes=["server_1"],
            trust_level="trusted",
        )
        types = [e.event_type for e in events]
        assert "run_failed" not in types

    def test_cooldown_prevents_duplicate_events(self, tmp_path):
        engine = _engine(tmp_path, min_urgency=0.0, min_interval_sec=3600)
        state = {"ci_broken": True, "branch": "main"}
        events1 = engine.scan(state, authorized_scopes=["*"], trust_level="admin")
        events2 = engine.scan(state, authorized_scopes=["*"], trust_level="admin")
        assert len(events1) >= 1
        types2 = [e.event_type for e in events2]
        assert "ci_broken" not in types2

    def test_urgency_filter_suppresses_low_urgency(self, tmp_path):
        engine = _engine(tmp_path, min_urgency=0.5, min_interval_sec=0)
        events = engine.scan(
            {"session_start_ts": time.time() - 5 * 3600},
            authorized_scopes=["*"],
            trust_level="admin",
        )
        types = [e.event_type for e in events]
        assert "session_long" not in types

    def test_long_session_emitted_at_low_urgency_threshold(self, tmp_path):
        engine = _engine(tmp_path, min_urgency=0.1, min_interval_sec=0)
        events = engine.scan(
            {"session_start_ts": time.time() - 5 * 3600},
            authorized_scopes=["*"],
            trust_level="admin",
        )
        types = [e.event_type for e in events]
        assert "session_long" in types

    def test_wildcard_scope_sees_all_resources(self, tmp_path):
        engine = _engine(tmp_path, min_urgency=0.0, min_interval_sec=0)
        events = engine.scan(
            {"degraded_resources": [{"name": "any_server", "reason": "down"}]},
            authorized_scopes=["*"],
            trust_level="admin",
        )
        assert any(e.event_type == "resource_degraded" for e in events)

    def test_no_scope_restriction_sees_all(self, tmp_path):
        engine = _engine(tmp_path, min_urgency=0.0, min_interval_sec=0)
        events = engine.scan(
            {"run_failed": {"issue": "any_issue", "reason": "crash"}},
            authorized_scopes=None,
            trust_level="admin",
        )
        assert any(e.event_type == "run_failed" for e in events)
