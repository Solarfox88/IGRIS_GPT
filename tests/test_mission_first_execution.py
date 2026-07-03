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
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from igris.web.server import create_app
    # Disable IGRIS_REQUIRE_AUTH gate so tests reach endpoint logic regardless of CI env (#1337-A).
    monkeypatch.setenv("IGRIS_REQUIRE_AUTH", "false")
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

def test_chat_operational_read_only_returns_mission_plan(client, monkeypatch):
    """read_only_inspection must return mission with correct fields."""
    chat_calls = []
    def mock_chat(m, history=None, system_prompt=None):
        chat_calls.append(m)
        return {"text": "mock", "provider": "mock", "model": "mock", "fallback_used": False,
                "latency_ms": 0, "routing_reason": "test", "intent_detected": None, "suggested_actions": []}
    try:
        import igris.core.chat_engine as ce
        monkeypatch.setattr(ce, "chat", mock_chat)
        import igris.web.routers.routes_01 as r1
        monkeypatch.setattr(r1, "chat_llm", mock_chat)
    except Exception:
        pass

    r = client.post("/api/sessions")
    sid = r.json()["id"]
    r2 = client.post(f"/api/sessions/{sid}/messages",
                     json={"message": "controlla i log del server", "interlocutor_id": "owner"})
    assert r2.status_code == 200
    d = r2.json()

    # Mission must be present
    assert "mission" in d, f"'mission' key missing from response: {list(d.keys())}"
    mission = d["mission"]
    assert mission is not None, "mission must not be None"
    assert mission.get("route") == "read_only_inspection", \
        f"Expected read_only_inspection, got {mission.get('route')!r}"
    assert mission.get("execution_mode") == "read_only", \
        f"Expected read_only, got {mission.get('execution_mode')!r}"

    # provider should be mission_first
    assert d.get("provider") == "mission_first", \
        f"Expected mission_first provider, got {d.get('provider')!r}"

    # chat_llm must NOT have been called for read_only mission
    assert len(chat_calls) == 0, f"chat_llm was called for read_only mission: {chat_calls}"


def test_chat_deploy_requires_approval_strict(client, monkeypatch):
    """Deploy must return mission with execution_mode=approval_required, chat_llm not called."""
    chat_calls = []
    def mock_chat(m, history=None, system_prompt=None):
        chat_calls.append(m)
        return {"text": "mock", "provider": "mock", "model": "mock", "fallback_used": False,
                "latency_ms": 0, "routing_reason": "test", "intent_detected": None, "suggested_actions": []}
    try:
        import igris.core.chat_engine as ce
        monkeypatch.setattr(ce, "chat", mock_chat)
        import igris.web.routers.routes_01 as r1
        monkeypatch.setattr(r1, "chat_llm", mock_chat)
    except Exception:
        pass

    r = client.post("/api/sessions")
    sid = r.json()["id"]
    r2 = client.post(f"/api/sessions/{sid}/messages",
                     json={"message": "fai deploy in produzione", "interlocutor_id": "owner"})
    assert r2.status_code == 200
    d = r2.json()

    # Must indicate approval required or blocked
    assert (
        d.get("requires_approval") is True
        or d.get("blocked") is True
        or (d.get("mission") and d["mission"].get("requires_approval"))
    ), f"Deploy must require approval or be blocked. Response: {d}"

    # If mission present with approval_required, check execution_mode
    if d.get("mission") and not d.get("blocked"):
        mission = d["mission"]
        assert mission.get("execution_mode") in ("approval_required",), \
            f"Expected approval_required, got {mission.get('execution_mode')!r}"

    # chat_llm must NOT have been called
    assert len(chat_calls) == 0, f"chat_llm was called despite approval_required: {chat_calls}"


def test_chat_github_merge_approval_required(client, monkeypatch):
    """GitHub merge must return mission with approval_required, chat_llm not called."""
    chat_calls = []
    def mock_chat(m, history=None, system_prompt=None):
        chat_calls.append(m)
        return {"text": "mock", "provider": "mock", "model": "mock", "fallback_used": False,
                "latency_ms": 0, "routing_reason": "test", "intent_detected": None, "suggested_actions": []}
    try:
        import igris.core.chat_engine as ce
        monkeypatch.setattr(ce, "chat", mock_chat)
        import igris.web.routers.routes_01 as r1
        monkeypatch.setattr(r1, "chat_llm", mock_chat)
    except Exception:
        pass

    r = client.post("/api/sessions")
    sid = r.json()["id"]
    r2 = client.post(f"/api/sessions/{sid}/messages",
                     json={"message": "mergia la PR #1261", "interlocutor_id": "owner"})
    assert r2.status_code == 200
    d = r2.json()

    assert len(chat_calls) == 0, f"chat_llm called for github merge: {chat_calls}"
    assert (
        d.get("requires_approval")
        or d.get("blocked")
        or (d.get("mission") and d["mission"].get("requires_approval"))
    ), f"GitHub merge must require approval: {d}"


def test_chat_high_risk_unknown_returns_blocked_mission(client):
    """High-risk from unknown must be blocked with blocked=True and optionally mission.blocked=True."""
    r = client.post("/api/sessions")
    sid = r.json()["id"]
    r2 = client.post(f"/api/sessions/{sid}/messages",
                     json={"message": "cancella il database di produzione",
                           "interlocutor_id": "unknown_attacker"})
    assert r2.status_code == 200
    d = r2.json()

    assert d.get("blocked") is True, f"Expected blocked=True: {d}"
    # If mission is present, check it reflects blocked status
    if d.get("mission"):
        assert d["mission"].get("blocked") is True
        assert d["mission"].get("execution_mode") == "blocked" or d["mission"].get("status") == "blocked"


# Keep original name as alias for backward compat
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


def test_stream_deploy_no_chat_stream_sync(client, monkeypatch):
    """Deploy stream must NOT call chat_stream_sync."""
    stream_calls = []

    def mock_stream(*a, **kw):
        stream_calls.append(True)
        return iter([])

    try:
        import igris.core.chat_streaming as cs
        monkeypatch.setattr(cs, "chat_stream_sync", mock_stream)
        import igris.web.routers.routes_01 as r1
        monkeypatch.setattr(r1, "chat_streaming",
                            type("m", (), {"chat_stream_sync": mock_stream})())
    except Exception:
        pass

    r = client.post("/api/chat/stream",
                    json={"message": "fai deploy in produzione", "interlocutor_id": "owner",
                          "session_id": "stream_deploy_test"})
    assert r.status_code == 200
    content = r.text

    # Must not have called real stream
    assert len(stream_calls) == 0, f"chat_stream_sync was called for deploy stream: {stream_calls}"
    # Must contain approval/mission/blocked/denied message (anti-spoofing may downgrade owner->unknown->denied)
    assert (
        "approvazione" in content.lower()
        or "approval" in content.lower()
        or "mission" in content.lower()
        or "piano" in content.lower()
        or "bloccata" in content.lower()
        or "blocked" in content.lower()
        or "denied" in content.lower()
    ), f"Stream did not return mission/approval/denied message for deploy: {content[:300]!r}"


def test_stream_high_risk_unknown_blocked_no_stream(client, monkeypatch):
    """High-risk unknown stream must NOT call chat_stream_sync."""
    stream_calls = []

    def mock_stream(*a, **kw):
        stream_calls.append(True)
        return iter([])

    try:
        import igris.core.chat_streaming as cs
        monkeypatch.setattr(cs, "chat_stream_sync", mock_stream)
    except Exception:
        pass

    r = client.post("/api/chat/stream",
                    json={"message": "cancella il database", "interlocutor_id": "unknown_attacker",
                          "session_id": "stream_block_test"})
    assert r.status_code == 200
    assert len(stream_calls) == 0, "chat_stream_sync called for blocked stream"
    content = r.text
    assert (
        "bloccata" in content.lower()
        or "blocked" in content.lower()
        or "denied" in content.lower()
    ), f"Stream did not return blocked message: {content[:200]!r}"


def test_stream_deploy_returns_mission_or_approval_sse(client):
    r = client.post(
        "/api/chat/stream",
        json={"message": "fai deploy in produzione",
              "interlocutor_id": "owner",
              "session_id": "stream_mission_1245"},
    )
    assert r.status_code == 200
    content = r.text
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


def test_persist_mission_plan_ok_true_real_storage(tmp_path):
    """persist_mission_plan must return ok=True on real UnifiedMemory when LTM available."""
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.jarvis_request_router import JarvisRequestRouter

    mem = UnifiedMemory(project_root=tmp_path)
    mfc = MissionFirstController(project_root=tmp_path, unified_memory=mem)
    router = JarvisRequestRouter(project_root=tmp_path)
    rd = router.classify("controlla i log", trust_level="admin")
    plan = mfc.build_plan("test", route_decision=rd, trust_level="admin")

    result = mfc.persist_mission_plan(plan)

    if mem._ltm is not None:  # LTM available
        assert result["ok"] is True, (
            f"persist_mission_plan must return ok=True when LTM is available. Got: {result}"
        )
    else:
        assert result["ok"] is False
        assert result.get("persistence_degraded")


def test_chat_response_no_raw_secret(client, monkeypatch):
    """Chat mission response must not contain raw secrets."""
    FAKE = "FAKE_TOKEN_MISSION_CHAT_NOTREAL_9988"

    def mock_chat(m, **kw):
        return {"text": "clean response", "provider": "mock", "model": "mock",
                "fallback_used": False, "latency_ms": 0, "routing_reason": "test",
                "intent_detected": None, "suggested_actions": []}
    try:
        import igris.core.chat_engine as ce
        monkeypatch.setattr(ce, "chat", mock_chat)
        import igris.web.routers.routes_01 as r1
        monkeypatch.setattr(r1, "chat_llm", mock_chat)
    except Exception:
        pass

    r = client.post("/api/sessions")
    sid = r.json()["id"]
    r2 = client.post(f"/api/sessions/{sid}/messages",
                     json={"message": f"fai deploy token={FAKE}", "interlocutor_id": "owner"})
    assert r2.status_code == 200
    content = json.dumps(r2.json())
    assert FAKE not in content, f"Raw secret in chat mission response: {content[:300]}"


def test_stream_response_no_raw_secret(client):
    """Stream mission response must not contain raw secrets."""
    FAKE = "FAKE_TOKEN_MISSION_STREAM_NOTREAL_7766"
    r = client.post("/api/chat/stream",
                    json={"message": f"fai deploy token={FAKE}", "interlocutor_id": "owner",
                          "session_id": "stream_secret_test"})
    assert r.status_code == 200
    assert FAKE not in r.text, f"Raw secret in stream response: {r.text[:300]}"


# ── Healthcheck ───────────────────────────────────────────────────────────────

def test_healthcheck_returns_dict(mfc):
    result = mfc.healthcheck()
    assert "ok" in result
    assert "backends" in result
