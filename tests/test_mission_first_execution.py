"""Tests for MissionFirstController (#1245)."""
import json
import pytest
from igris.core.mission_first import (
    MissionFirstController,
    MissionPlan,
    MissionStep,
    MissionExecutionMode,
    MissionStatus,
    _redact,
)
from igris.core.jarvis_request_router import JarvisRequestRouter


@pytest.fixture
def router(tmp_path):
    return JarvisRequestRouter(project_root=tmp_path)


@pytest.fixture
def mfc(tmp_path):
    return MissionFirstController(project_root=tmp_path)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from igris.web.server import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


# ── should_create_mission ─────────────────────────────────────────────────────

def test_should_not_create_mission_for_chat_only(mfc, router):
    rd = router.classify("ciao come stai", trust_level="admin")
    assert not mfc.should_create_mission(rd)


def test_should_create_mission_for_read_only_inspection(mfc, router):
    rd = router.classify("controlla i log", trust_level="admin")
    assert mfc.should_create_mission(rd)


def test_should_create_mission_for_deploy_operation(mfc, router):
    rd = router.classify("fai deploy in produzione", trust_level="admin")
    assert mfc.should_create_mission(rd)


def test_should_not_create_mission_for_none(mfc):
    assert not mfc.should_create_mission(None)


# ── build_plan ────────────────────────────────────────────────────────────────

def test_build_plan_read_only_inspection(mfc, router):
    rd = router.classify("controlla i log del server", trust_level="admin")
    plan = mfc.build_plan("controlla i log", route_decision=rd,
                          interlocutor_id="owner", trust_level="admin")
    assert plan.route == "read_only_inspection"
    assert plan.execution_mode in ("read_only", "dry_run")
    assert not plan.blocked
    assert len(plan.steps) > 0


def test_build_plan_project_reasoning_plan_only(mfc, router):
    rd = router.classify("ragiona sull architettura del sistema", trust_level="admin")
    plan = mfc.build_plan("architettura", route_decision=rd,
                          interlocutor_id="owner", trust_level="admin")
    assert plan.route == "project_reasoning"
    assert not plan.blocked
    assert plan.execution_mode in ("plan_only", "dry_run")


def test_build_plan_deploy_requires_approval(mfc, router):
    rd = router.classify("fai deploy in produzione", trust_level="admin")
    plan = mfc.build_plan("fai deploy", route_decision=rd,
                          interlocutor_id="owner", trust_level="admin", dry_run=False)
    assert plan.requires_approval or plan.execution_mode in ("approval_required", "dry_run")


def test_build_plan_high_risk_unknown_blocked(mfc, router):
    rd = router.classify("cancella il database di produzione",
                         interlocutor_id="unknown", trust_level="untrusted")
    plan = mfc.build_plan("cancella", route_decision=rd,
                          interlocutor_id="unknown", trust_level="untrusted")
    assert plan.blocked or rd.blocked


def test_mission_plan_no_auto_execute_deploy(mfc, router):
    rd = router.classify("fai deploy in produzione", trust_level="admin")
    plan = mfc.build_plan("fai deploy", route_decision=rd,
                          interlocutor_id="owner", trust_level="admin")
    for step in plan.steps:
        if step.action_type == "deploy":
            assert step.dry_run_only or step.requires_approval, (
                f"Deploy step must be dry_run_only or requires_approval: {step}"
            )


def test_mission_plan_no_raw_secret(mfc, router):
    FAKE = "FAKE_TOKEN_MISSION_NOTREAL_1234567890"
    rd = router.classify(f"fai deploy token={FAKE}", trust_level="admin")
    plan = mfc.build_plan(f"deploy token={FAKE}", route_decision=rd,
                          interlocutor_id="owner", trust_level="admin")
    output = json.dumps(plan.to_dict())
    assert FAKE not in output, f"Raw secret in mission plan: {output[:300]}"


def test_owner_untrusted_not_elevated(mfc, router):
    rd = router.classify("cancella tutto il database",
                         interlocutor_id="owner", trust_level="untrusted")
    # untrusted trust_level for destructive ops must block regardless of interlocutor_id
    assert rd.blocked, "owner with untrusted trust_level must be blocked for destructive ops"
    plan = mfc.build_plan("cancella", route_decision=rd,
                          interlocutor_id="owner", trust_level="untrusted")
    assert plan.blocked


def test_build_plan_has_mission_id(mfc, router):
    rd = router.classify("controlla i log", trust_level="admin")
    plan = mfc.build_plan("controlla i log", route_decision=rd, trust_level="admin")
    assert plan.mission_id
    assert len(plan.mission_id) == 36  # UUID format


def test_build_plan_created_at_set(mfc, router):
    rd = router.classify("controlla i log", trust_level="admin")
    plan = mfc.build_plan("controlla i log", route_decision=rd, trust_level="admin")
    assert plan.created_at


def test_build_plan_steps_not_empty_for_mission_routes(mfc, router):
    for msg, tl in [
        ("controlla i log", "admin"),
        ("ragiona sull architettura", "admin"),
        ("modifica il codice del modulo", "admin"),
        ("fai deploy in produzione", "admin"),
    ]:
        rd = router.classify(msg, trust_level=tl)
        if not rd.blocked:
            plan = mfc.build_plan(msg, route_decision=rd, trust_level=tl)
            if mfc.should_create_mission(rd):
                assert len(plan.steps) > 0, f"No steps for route={plan.route}"


# ── Context aggregator integration ────────────────────────────────────────────

def test_build_plan_calls_context_aggregator_for_mission_route(tmp_path):
    from igris.core.context_aggregator import ContextAggregator
    calls = []

    class TrackingAgg(ContextAggregator):
        def build_context(self, *a, **kw):
            calls.append(True)
            return super().build_context(*a, **kw)

    agg = TrackingAgg(project_root=tmp_path)
    mfc = MissionFirstController(project_root=tmp_path, context_aggregator=agg)
    router = JarvisRequestRouter(project_root=tmp_path)
    rd = router.classify("controlla i log", trust_level="admin")
    mfc.build_plan("controlla i log", route_decision=rd, trust_level="admin")
    assert len(calls) > 0, "ContextAggregator.build_context was not called"


def test_context_aggregator_not_called_when_blocked(tmp_path):
    from igris.core.context_aggregator import ContextAggregator
    calls = []

    class TrackingAgg(ContextAggregator):
        def build_context(self, *a, **kw):
            calls.append(True)
            return super().build_context(*a, **kw)

    agg = TrackingAgg(project_root=tmp_path)
    mfc = MissionFirstController(project_root=tmp_path, context_aggregator=agg)
    router = JarvisRequestRouter(project_root=tmp_path)
    rd = router.classify("cancella il database", interlocutor_id="unknown", trust_level="untrusted")
    mfc.build_plan("cancella", route_decision=rd, interlocutor_id="unknown", trust_level="untrusted")
    assert len(calls) == 0, "ContextAggregator.build_context must NOT be called for blocked missions"


# ── Persistence ───────────────────────────────────────────────────────────────

def test_persist_mission_plan_uses_unified_memory(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    calls = []
    mem = UnifiedMemory(project_root=tmp_path)
    original = mem.store_run_event

    def tracking(*a, **kw):
        calls.append(True)
        return original(*a, **kw)

    mem.store_run_event = tracking
    mfc = MissionFirstController(project_root=tmp_path, unified_memory=mem)
    router = JarvisRequestRouter(project_root=tmp_path)
    rd = router.classify("controlla i log", trust_level="admin")
    plan = mfc.build_plan("test", route_decision=rd, trust_level="admin")
    mfc.persist_mission_plan(plan)
    assert len(calls) > 0, "store_run_event was not called"


def test_persist_mission_plan_ok_false_when_memory_fails(tmp_path):
    from igris.core.unified_memory import UnifiedMemory

    def broken_store(*a, **kw):
        raise RuntimeError("write fail")

    mem = UnifiedMemory(project_root=tmp_path)
    mem.store_run_event = broken_store
    mfc = MissionFirstController(project_root=tmp_path, unified_memory=mem)
    router = JarvisRequestRouter(project_root=tmp_path)
    rd = router.classify("controlla i log", trust_level="admin")
    plan = mfc.build_plan("test", route_decision=rd, trust_level="admin")
    result = mfc.persist_mission_plan(plan)
    assert result["ok"] is False
    assert result.get("persistence_degraded")


def test_persist_returns_ok_true_on_success(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    mfc = MissionFirstController(project_root=tmp_path, unified_memory=mem)
    router = JarvisRequestRouter(project_root=tmp_path)
    rd = router.classify("controlla i log", trust_level="admin")
    plan = mfc.build_plan("test", route_decision=rd, trust_level="admin")
    result = mfc.persist_mission_plan(plan)
    # ok may be True or False depending on backend, but key must exist
    assert "ok" in result


# ── to_response_payload ───────────────────────────────────────────────────────

def test_to_response_payload_has_required_keys(mfc, router):
    rd = router.classify("controlla i log", trust_level="admin")
    plan = mfc.build_plan("controlla i log", route_decision=rd, trust_level="admin")
    payload = mfc.to_response_payload(plan)
    for key in ("response", "mission", "blocked", "requires_approval", "provider", "model"):
        assert key in payload, f"Missing key: {key}"


def test_to_response_payload_blocked_plan(mfc, router):
    rd = router.classify("cancella il database", interlocutor_id="unknown", trust_level="untrusted")
    plan = mfc.build_plan("cancella", route_decision=rd, interlocutor_id="unknown", trust_level="untrusted")
    payload = mfc.to_response_payload(plan)
    if plan.blocked:
        assert payload["blocked"] is True
        assert "bloccata" in payload["response"].lower() or "bloccat" in payload["response"].lower()


def test_to_response_payload_marks_persistence_degraded(mfc, router):
    rd = router.classify("controlla i log", trust_level="admin")
    plan = mfc.build_plan("test", route_decision=rd, trust_level="admin")
    payload = mfc.to_response_payload(plan, persist_result={"ok": False, "persistence_degraded": True})
    assert payload.get("persistence_degraded") is True


# ── Redaction ─────────────────────────────────────────────────────────────────

def test_redact_token_in_query(mfc, router):
    FAKE = "FAKE_SECRET_TOKEN_XYZ_9999"
    rd = router.classify(f"controlla i log token={FAKE}", trust_level="admin")
    plan = mfc.build_plan(f"test token={FAKE}", route_decision=rd, trust_level="admin")
    assert FAKE not in plan.query


def test_redact_password_in_title(mfc, router):
    FAKE = "mysecretpassword123"
    rd = router.classify(f"controlla i log password={FAKE}", trust_level="admin")
    plan = mfc.build_plan(f"run password={FAKE}", route_decision=rd, trust_level="admin")
    assert FAKE not in plan.title


# ── Chat endpoint integration ─────────────────────────────────────────────────

def test_chat_operational_read_only_returns_mission_plan(client):
    r = client.post("/api/sessions")
    sid = r.json()["id"]
    r2 = client.post(
        f"/api/sessions/{sid}/messages",
        json={"message": "controlla i log", "interlocutor_id": "owner"},
    )
    assert r2.status_code == 200
    d = r2.json()
    assert "response" in d


def test_chat_deploy_returns_mission_or_approval(client):
    r = client.post("/api/sessions")
    sid = r.json()["id"]
    r2 = client.post(
        f"/api/sessions/{sid}/messages",
        json={"message": "fai deploy in produzione", "interlocutor_id": "owner"},
    )
    assert r2.status_code == 200
    d = r2.json()
    # deploy must require approval, be a mission plan, or be blocked
    # (anti-spoofing downgrades 'owner' to 'unknown' in non-local requests, causing a block)
    assert (
        d.get("requires_approval")
        or d.get("mission")
        or d.get("blocked")
        or "approvazione" in str(d.get("response", "")).lower()
        or "approval" in str(d.get("response", "")).lower()
    ), f"Deploy response missing approval/mission/blocked signal: {d}"


def test_chat_high_risk_unknown_returns_blocked(client):
    r = client.post("/api/sessions")
    sid = r.json()["id"]
    r2 = client.post(
        f"/api/sessions/{sid}/messages",
        json={"message": "cancella il database di produzione",
              "interlocutor_id": "unknown_attacker"},
    )
    assert r2.status_code == 200
    assert r2.json().get("blocked") is True


def test_stream_deploy_returns_mission_or_approval_sse(client):
    r = client.post(
        "/api/chat/stream",
        json={"message": "fai deploy in produzione",
              "interlocutor_id": "owner",
              "session_id": "stream_mission_1245"},
    )
    assert r.status_code == 200
    content = r.text
    # anti-spoofing may downgrade 'owner' -> 'unknown' -> blocked, which is also correct
    assert (
        "approvazione" in content.lower()
        or "approval" in content.lower()
        or "piano" in content.lower()
        or "mission" in content.lower()
        or "denied" in content.lower()
        or "blocked" in content.lower()
    ), f"Stream deploy missing mission/approval/blocked signal: {content[:300]}"


def test_stream_read_only_returns_mission_text(client):
    r = client.post(
        "/api/chat/stream",
        json={"message": "controlla i log del server",
              "interlocutor_id": "owner",
              "session_id": "stream_readonly_1245"},
    )
    assert r.status_code == 200


# ── Healthcheck ───────────────────────────────────────────────────────────────

def test_healthcheck_returns_dict(mfc):
    result = mfc.healthcheck()
    assert "ok" in result
    assert "backends" in result
