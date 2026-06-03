"""Tests for IntentResolver — issue #526."""
import pytest
from igris.core.intent_resolver import IntentResolver


@pytest.fixture()
def ir():
    return IntentResolver()


def test_clear_action_restart_server(ir):
    r = ir.resolve("Please restart the server prod01")
    assert r.action_type == "restart_server"
    assert not r.ambiguous
    assert r.confidence > 0.5


def test_clear_action_run_tests(ir):
    r = ir.resolve("run tests now")
    assert r.action_type == "run_tests"
    assert not r.ambiguous


def test_clear_target_pr(ir):
    r = ir.resolve("show me issue #42")
    assert r.action_type == "read_github"
    assert r.extracted_entities.get("issue") == "42"


def test_destructive_risk(ir):
    r = ir.resolve("delete the database")
    assert r.risk_hint == "destructive"


def test_high_risk_deploy(ir):
    r = ir.resolve("deploy to production")
    # deploy matches risk 'high'
    assert r.risk_hint in ("high", "destructive")


def test_urgency_critical(ir):
    r = ir.resolve("restart server asap")
    assert r.urgency == "critical"


def test_urgency_low(ir):
    r = ir.resolve("merge pr #5 eventually")
    assert r.urgency == "low"


def test_ambiguous_no_action(ir):
    r = ir.resolve("do the thing")
    assert r.ambiguous
    assert r.clarification_question is not None


def test_ambiguous_deploy_no_target(ir):
    r = ir.resolve("please deploy")
    assert r.action_type == "deploy"
    assert r.ambiguous  # no target


def test_implied_authorization_only_low_risk(ir):
    r = ir.resolve("run tests now")
    # run_tests + low risk + not ambiguous
    assert r.implied_authorization


def test_no_implied_authorization_destructive(ir):
    r = ir.resolve("delete everything")
    assert not r.implied_authorization
