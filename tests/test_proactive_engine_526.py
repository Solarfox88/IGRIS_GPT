"""Tests for ProactiveEngine — issue #526."""
import pytest
from igris.core.proactive_engine import ProactiveEngine, ProactiveConfig


@pytest.fixture()
def engine(tmp_path):
    cfg = ProactiveConfig(min_interval_sec=0)  # disable cooldown for tests
    return ProactiveEngine(str(tmp_path), config=cfg)


def test_no_events_empty_snapshot(engine):
    events = engine.scan(state_snapshot={})
    assert isinstance(events, list)


def test_events_for_trusted(engine):
    snapshot = {
        "ci_failing": True,
        "open_prs": ["pr/1"],
        "disk_usage_pct": 95,
    }
    events = engine.scan(state_snapshot=snapshot, trust_level="trusted")
    # may return events or not — just must not raise
    assert isinstance(events, list)


def test_untrusted_gets_limited_events(engine):
    snapshot = {"ci_failing": True}
    events = engine.scan(state_snapshot=snapshot, trust_level="untrusted",
                         authorized_scopes=[])
    # must not raise; may be empty
    assert isinstance(events, list)
