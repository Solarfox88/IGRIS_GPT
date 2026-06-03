"""Tests for AdaptiveResponse v2 — issue #526."""
import tempfile, pytest
from igris.core.adaptive_response import AdaptiveResponse
from igris.core.identity_resolver import IdentityResolver


@pytest.fixture()
def root(tmp_path):
    return str(tmp_path)


@pytest.fixture()
def ar(tmp_path, root):
    audit_path = str(tmp_path / "audit.jsonl")
    return AdaptiveResponse(root, audit_path=audit_path)


def _setup_trusted(root, scopes=None):
    ir = IdentityResolver(root)
    ir.create("alice", "Alice", trust_level="trusted",
               authorized_scopes=scopes or ["read_github", "run_tests"])


def test_allowed_path(root, ar):
    _setup_trusted(root, ["run_tests"])
    result = ar.process("alice", "run tests", action_type="run_tests", target_resource="run_tests")
    assert result.allowed
    assert not result.blocked
    assert result.audit_event_id


def test_denied_path_untrusted(root, ar):
    result = ar.process("stranger", "deploy", action_type="deploy", target_resource="deploy")
    assert result.blocked
    assert not result.allowed
    assert result.audit_event_id


def test_clarification_path(root, ar):
    result = ar.process("alice", "do the thing")  # no action_type given, ambiguous message
    assert result.needs_clarification
    assert result.intent is not None
    assert result.intent.clarification_question is not None


def test_advisory_on_allowed(root, ar):
    from igris.core.judgment_layer import OperationalContext
    _setup_trusted(root, ["restart_server"])
    # needs ci_running to trigger requires_confirmation for trusted user
    result = ar.process("alice", "restart the server", action_type="restart_server",
                        target_resource="restart_server",
                        operational_context=OperationalContext(ci_running=True))
    assert result.allowed
    assert result.advisory is not None
    assert result.requires_confirmation  # restart_server + ci_running → requires confirmation


def test_to_dict_safe(root, ar):
    _setup_trusted(root)
    result = ar.process("alice", "run tests", action_type="run_tests", target_resource="run_tests")
    d = result.to_dict()
    assert "passphrase" not in str(d)
    assert "profile_id" in d
    assert "allowed" in d


def test_proactive_events(root, ar):
    _setup_trusted(root)
    result = ar.process(
        "alice", "run tests", action_type="run_tests", target_resource="run_tests",
        state_snapshot={"ci_failing": True}
    )
    assert isinstance(result.proactive_events, list)


def test_admin_bypass(root, ar):
    ir = IdentityResolver(root)
    ir.create("admin_user", "Admin", trust_level="admin")
    result = ar.process("admin_user", "delete branch main",
                        action_type="delete_branch", target_resource="main")
    assert result.allowed
