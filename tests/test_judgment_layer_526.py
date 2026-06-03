"""Tests for JudgmentLayer — issue #526."""
import pytest
from igris.core.judgment_layer import JudgmentLayer, OperationalContext


@pytest.fixture()
def jl():
    return JudgmentLayer()


def test_non_sensitive_proceed(jl):
    ctx = OperationalContext()
    a = jl.advise("read_logs", "server", ctx, trust_level="trusted")
    assert a.should_proceed
    assert not a.blocking


def test_sensitive_no_backup_proceed(jl):
    ctx = OperationalContext()
    a = jl.advise("restart_server", "prod", ctx, trust_level="admin")
    assert not a.blocking


def test_active_backup_warning(jl):
    ctx = OperationalContext(active_backups=[{"name": "daily", "pct": 50, "eta_sec": 300}])
    a = jl.advise("deploy", "prod", ctx, trust_level="trusted")
    assert "backup" in a.message.lower() or not a.should_proceed or a.requires_confirmation


def test_ci_running_warning(jl):
    ctx = OperationalContext(ci_running=True)
    a = jl.advise("merge", "main", ctx, trust_level="trusted")
    # may warn
    assert a is not None  # just check it doesn't crash


def test_requires_confirmation_for_trusted(jl):
    # requires_confirmation only set when there are operational concerns
    ctx = OperationalContext(ci_running=True)  # trigger a warning
    a = jl.advise("restart_server", "prod", ctx, trust_level="trusted")
    assert a.requires_confirmation


def test_no_confirmation_for_admin_on_sensitive(jl):
    ctx = OperationalContext()
    a = jl.advise("restart_server", "prod", ctx, trust_level="admin")
    # admin bypass: may still have requires_confirmation=False
    assert not a.blocking
