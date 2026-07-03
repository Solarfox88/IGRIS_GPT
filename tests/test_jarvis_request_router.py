"""Tests for JarvisRequestRouter (#1243)."""
import pytest
from igris.core.jarvis_request_router import JarvisRequestRouter, JarvisRouteDecision, RequestRoute, RequestRisk


@pytest.fixture
def router(tmp_path):
    return JarvisRequestRouter(project_root=tmp_path)


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from igris.web.server import create_app
    # Disable IGRIS_REQUIRE_AUTH gate so tests reach endpoint logic regardless of CI env (#1337-A).
    monkeypatch.setenv("IGRIS_REQUIRE_AUTH", "false")
    return TestClient(create_app(), raise_server_exceptions=False)


# ── Classification tests ───────────────────────────────────────────────────────

def test_classifies_chat_only(router):
    d = router.classify("spiegami questa funzione", interlocutor_id="owner", trust_level="admin")
    assert d.route == RequestRoute.CHAT_ONLY
    assert d.risk == RequestRisk.LOW
    assert not d.blocked

def test_classifies_memory_update_preference(router):
    d = router.classify("ricordati che preferisco risposte brevi", trust_level="admin")
    assert d.route == RequestRoute.MEMORY_UPDATE
    assert d.memory_mode == "store"

def test_classifies_memory_update_correction(router):
    d = router.classify("questa correzione è importante: usa sempre worktree", trust_level="admin")
    assert d.route == RequestRoute.MEMORY_UPDATE

def test_classifies_read_only_inspection_logs(router):
    d = router.classify("controlla i log del server", trust_level="admin")
    assert d.route == RequestRoute.READ_ONLY_INSPECTION
    assert not d.blocked

def test_classifies_project_reasoning(router):
    d = router.classify("ragiona sull'architettura del progetto", trust_level="admin")
    assert d.route == RequestRoute.PROJECT_REASONING

def test_classifies_code_change(router):
    d = router.classify("modifica il codice per fixare il bug", trust_level="admin")
    assert d.route == RequestRoute.CODE_CHANGE

def test_classifies_github_merge_pr(router):
    d = router.classify("mergia la PR #1259", trust_level="admin")
    assert d.route == RequestRoute.GITHUB_OPERATION
    assert d.requires_approval

def test_classifies_github_close_issue(router):
    d = router.classify("chiudi la issue #500", trust_level="admin")
    assert d.route == RequestRoute.GITHUB_OPERATION

def test_classifies_server_restart_high_risk(router):
    d = router.classify("riavvia il server nginx", trust_level="admin")
    assert d.route == RequestRoute.SERVER_OPERATION
    assert d.risk in (RequestRisk.HIGH, "high")

def test_classifies_deploy_high_risk(router):
    d = router.classify("fai deploy in produzione", trust_level="admin")
    assert d.route == RequestRoute.DEPLOY_OPERATION
    assert d.risk in (RequestRisk.HIGH, "high")
    assert d.requires_approval

def test_classifies_destructive_delete_blocked_for_untrusted(router):
    d = router.classify("cancella il database di produzione", interlocutor_id="unknown", trust_level="untrusted")
    assert d.blocked
    assert d.route == RequestRoute.BLOCKED

def test_ambiguous_request_requires_clarification(router):
    d = router.classify("fallo", trust_level="admin")
    assert d.requires_clarification
    assert d.route == RequestRoute.UNKNOWN_REQUIRES_CLARIFICATION


# ── Trust / security tests ─────────────────────────────────────────────────────

def test_owner_untrusted_not_auto_elevated(router):
    """owner interlocutor_id with untrusted trust_level must not get elevated."""
    d = router.classify("cancella il database", interlocutor_id="owner", trust_level="untrusted")
    assert d.blocked, "owner with untrusted trust_level must be blocked for destructive ops"

def test_unknown_sensitive_blocked(router):
    d = router.classify("elimina tutti i file", interlocutor_id="unknown_xyz", trust_level="untrusted")
    assert d.blocked

def test_preflight_blocked_propagates_to_route_blocked(router):
    class FakePreflight:
        blocked = True
        block_reason = "test preflight block"
        intent_action = "delete"
        intent_risk = "high"
        advisory = None
    d = router.classify("qualcosa", preflight=FakePreflight(), trust_level="admin")
    assert d.blocked
    assert "test preflight block" in d.reason

def test_preflight_advisory_preserved(router):
    class FakePreflight:
        blocked = False
        intent_action = "deploy"
        intent_risk = "high"
        advisory = "CI is running — consider waiting"
    d = router.classify("fai deploy", preflight=FakePreflight(), trust_level="admin")
    assert any("advisory" in w or "CI is running" in w for w in d.warnings)

def test_high_risk_requires_approval(router):
    d = router.classify("fai deploy in produzione", interlocutor_id="owner", trust_level="admin")
    assert d.requires_approval

def test_untrusted_memory_update_allowed_as_decision(router):
    """Memory update for untrusted produces route decision but with warning."""
    d = router.classify("ricordati che preferisco risposte brevi", trust_level="untrusted")
    # Not blocked (memory update is low risk) but has warning
    assert not d.blocked
    assert d.route == RequestRoute.MEMORY_UPDATE
    # Warning about untrusted memory update
    assert any("untrusted" in w.lower() for w in d.warnings)


# ── Italian patterns ───────────────────────────────────────────────────────────

def test_italian_cancella_classified_destructive(router):
    d = router.classify("cancella il database di produzione", trust_level="untrusted")
    assert d.blocked or d.risk in (RequestRisk.HIGH, RequestRisk.DESTRUCTIVE, "high", "destructive")

def test_italian_riavvia_classified_server_operation_high(router):
    d = router.classify("riavvia il server", trust_level="admin")
    assert d.route == RequestRoute.SERVER_OPERATION

def test_italian_mergia_classified_github_operation(router):
    d = router.classify("mergia la PR #123", trust_level="admin")
    assert d.route == RequestRoute.GITHUB_OPERATION

def test_italian_fai_deploy_classified_deploy_operation(router):
    d = router.classify("fai deploy", trust_level="admin")
    assert d.route == RequestRoute.DEPLOY_OPERATION

def test_italian_ricordati_classified_memory_update(router):
    d = router.classify("ricordati che preferisco risposte brevi", trust_level="admin")
    assert d.route == RequestRoute.MEMORY_UPDATE

def test_italian_controlla_log_classified_read_only(router):
    d = router.classify("controlla i log del sistema", trust_level="admin")
    assert d.route == RequestRoute.READ_ONLY_INSPECTION


# ── UnifiedMemory integration ──────────────────────────────────────────────────

def test_router_uses_unified_memory_for_chat_retrieval(tmp_path, monkeypatch):
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.jarvis_request_router import JarvisRequestRouter

    mem = UnifiedMemory(project_root=tmp_path)
    # Store a preference so retrieval has something to find
    mem.store_preference("owner", "admin", "Preferisco sempre risposte brevi e dirette")

    retrieve_calls = []
    original_retrieve = mem.retrieve_for_chat
    def tracking_retrieve(query, interlocutor_id, trust_level, **kwargs):
        retrieve_calls.append((query, interlocutor_id, trust_level))
        return original_retrieve(query=query, interlocutor_id=interlocutor_id, trust_level=trust_level, **kwargs)
    mem.retrieve_for_chat = tracking_retrieve

    router = JarvisRequestRouter(project_root=tmp_path, unified_memory=mem)
    d = router.route("fammi un riassunto", interlocutor_id="owner", trust_level="admin")

    assert not d.blocked
    # Verify retrieve_for_chat was called
    assert len(retrieve_calls) > 0, (
        "retrieve_for_chat was NOT called by router.route() for chat context. "
        "Router must call UnifiedMemory.retrieve_for_chat() for retrieve routes."
    )
    assert retrieve_calls[0][1] == "owner"  # correct interlocutor_id

    # Verify memory context is safe (no raw secrets in metadata)
    import json, re
    meta_str = json.dumps(d.metadata)
    assert not re.search(r'passphrase\s*=\s*\S{8,}', meta_str, re.IGNORECASE)
    # Memory context should be injected if available
    assert isinstance(d.metadata, dict)

def test_router_does_not_expose_memory_to_untrusted(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.jarvis_request_router import JarvisRequestRouter

    mem = UnifiedMemory(project_root=tmp_path)
    mem.store_preference("owner", "admin", "preferisco token=OWNER_SECRET risposte")

    router = JarvisRequestRouter(project_root=tmp_path, unified_memory=mem)
    d = router.route("fammi un riassunto", interlocutor_id="unknown_xyz", trust_level="untrusted")

    # untrusted chat_only is low risk — memory retrieval happens but trust filter applies
    ctx = d.metadata.get("memory_context", "")
    assert "OWNER_SECRET" not in ctx

def test_router_memory_update_does_not_store_secret_raw(tmp_path):
    from igris.core.jarvis_request_router import JarvisRequestRouter
    FAKE = "FAKE_SECRET_ROUTER_TEST_9988"
    router = JarvisRequestRouter(project_root=tmp_path)
    d = router.classify(f"ricordati token={FAKE}", trust_level="admin")
    assert d.route == RequestRoute.MEMORY_UPDATE
    # Router classify doesn't store — it produces a decision
    # Verify no secret in decision serialization
    import json
    output = json.dumps(d.to_dict())
    assert FAKE not in output, f"Secret in route decision: {output}"

def test_router_degraded_memory_does_not_crash(tmp_path, monkeypatch):
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.jarvis_request_router import JarvisRequestRouter

    def broken_retrieve(*a, **kw):
        raise RuntimeError("memory down")

    mem = UnifiedMemory(project_root=tmp_path)
    monkeypatch.setattr(mem, "retrieve_for_chat", broken_retrieve)

    router = JarvisRequestRouter(project_root=tmp_path, unified_memory=mem)
    d = router.route("spiegami questa funzione", interlocutor_id="owner", trust_level="admin")

    assert not d.blocked  # must not crash
    assert isinstance(d, JarvisRouteDecision)


# ── Chat endpoint integration ─────────────────────────────────────────────────

def test_chat_returns_route_metadata(client):
    r = client.post("/api/sessions")
    assert r.status_code == 200
    sid = r.json()["id"]
    r2 = client.post(
        f"/api/sessions/{sid}/messages",
        json={"message": "ciao come stai", "interlocutor_id": "owner"}
    )
    assert r2.status_code == 200
    d = r2.json()
    # route MUST be present and non-None
    assert "route" in d, f"route key missing from response: {list(d.keys())}"
    assert d["route"] is not None, "route must not be None"
    route_data = d["route"]
    assert isinstance(route_data, dict), f"route must be dict, got {type(route_data)}"
    assert "route" in route_data, f"route.route missing: {route_data}"
    assert route_data["route"] == "chat_only", (
        f"Expected route=chat_only for innocuous message, got {route_data['route']!r}"
    )

def test_chat_innocua_unknown_allowed(client):
    r = client.post("/api/sessions")
    sid = r.json()["id"]
    r2 = client.post(
        f"/api/sessions/{sid}/messages",
        json={"message": "ciao, come stai?", "interlocutor_id": "unknown_test"}
    )
    assert r2.status_code == 200
    assert "response" in r2.json()
    assert not r2.json().get("blocked", False)

def test_chat_sensitive_unknown_blocked(client):
    r = client.post("/api/sessions")
    sid = r.json()["id"]
    r2 = client.post(
        f"/api/sessions/{sid}/messages",
        json={"message": "cancella il database di produzione", "interlocutor_id": "unknown_attacker"}
    )
    assert r2.status_code == 200
    # Must be blocked
    assert r2.json().get("blocked") is True

def test_chat_memory_update_owner_classified(client):
    r = client.post("/api/sessions")
    assert r.status_code == 200
    sid = r.json()["id"]
    r2 = client.post(
        f"/api/sessions/{sid}/messages",
        json={"message": "ricordati che preferisco risposte brevi", "interlocutor_id": "owner"}
    )
    assert r2.status_code == 200
    d = r2.json()
    assert "route" in d, "route key missing"
    route_data = d["route"]
    assert route_data is not None, "route must not be None"
    assert route_data["route"] == "memory_update", (
        f"Expected memory_update for 'ricordati', got {route_data['route']!r}"
    )
    assert route_data.get("memory_mode") == "store", (
        f"Expected memory_mode=store, got {route_data.get('memory_mode')!r}"
    )

def test_route_metadata_no_secrets(client):
    r = client.post("/api/sessions")
    sid = r.json()["id"]
    r2 = client.post(
        f"/api/sessions/{sid}/messages",
        json={"message": "ciao", "interlocutor_id": "owner"}
    )
    import re, json
    content = json.dumps(r2.json())
    assert not re.search(r'passphrase\s*=\s*\S{8,}', content, re.IGNORECASE), \
        "Raw secret in route metadata"


def test_chat_high_risk_deploy_returns_approval_required(client, monkeypatch):
    """High-risk operations must not call chat_llm — must return requires_approval."""
    called = []

    def mock_chat(message, history=None, system_prompt=None):
        called.append(message)
        return {"text": "mock", "provider": "mock", "model": "mock",
                "fallback_used": False, "latency_ms": 0, "routing_reason": "test",
                "intent_detected": None, "suggested_actions": []}

    import igris.web.routers.routes_01 as _r
    monkeypatch.setattr(_r, "chat_llm", mock_chat)

    # Monkeypatch preflight to simulate a trusted local admin request
    # (TestClient requests are non-local so 'owner' gets downgraded to 'unknown' by anti-spoofing)
    from igris.core.chat_interlocutor_preflight import PreflightResult
    def mock_preflight(message, interlocutor_id=None, project_root=None,
                       is_new_session=False, is_local_request=False, payload=None, session_token=None):
        return PreflightResult(
            interlocutor_id="owner",
            trust_level="admin",
            response_mode={},
            intent_action="deploy",
            intent_risk="high",
            block_reason=None,
            blocked=False,
            requires_clarification=False,
            clarification_question=None,
            advisory=None,
            system_prompt_enrichment="",
        )
    import igris.core.chat_interlocutor_preflight as _pf_mod
    monkeypatch.setattr(_pf_mod, "run_preflight", mock_preflight)
    import igris.web.routers.routes_01 as _r2
    monkeypatch.setattr(_r2, "run_preflight", mock_preflight, raising=False)

    r = client.post("/api/sessions")
    sid = r.json()["id"]
    r2 = client.post(
        f"/api/sessions/{sid}/messages",
        json={"message": "fai deploy in produzione", "interlocutor_id": "owner"}
    )
    assert r2.status_code == 200
    d = r2.json()

    # chat_llm must NOT have been called
    assert len(called) == 0, f"chat_llm was called despite requires_approval: {called}"
    # Response must indicate approval required
    assert d.get("requires_approval") is True, (
        f"Expected requires_approval=True, got: {d}"
    )
    route_data = d.get("route") or {}
    assert route_data.get("requires_approval") is True


def test_stream_high_risk_returns_approval_not_stream(client, monkeypatch):
    """Stream endpoint must not stream real response for high-risk — return approval message."""
    # Monkeypatch preflight to simulate trusted local admin (anti-spoofing bypassed)
    from igris.core.chat_interlocutor_preflight import PreflightResult
    def mock_preflight(message, interlocutor_id=None, project_root=None,
                       is_new_session=False, is_local_request=False, payload=None, session_token=None):
        return PreflightResult(
            interlocutor_id="owner",
            trust_level="admin",
            response_mode={},
            intent_action="deploy",
            intent_risk="high",
            block_reason=None,
            blocked=False,
            requires_clarification=False,
            clarification_question=None,
            advisory=None,
            system_prompt_enrichment="",
        )
    import igris.core.chat_interlocutor_preflight as _pf_mod
    monkeypatch.setattr(_pf_mod, "run_preflight", mock_preflight)
    import igris.web.routers.routes_01 as _r2
    monkeypatch.setattr(_r2, "run_preflight", mock_preflight, raising=False)

    r = client.post(
        "/api/chat/stream",
        json={"message": "fai deploy in produzione", "interlocutor_id": "owner",
              "session_id": "stream_approval_test"}
    )
    assert r.status_code == 200
    content = r.text
    assert "approvazione" in content.lower() or "approval" in content.lower() or \
           "requires_approval" in content.lower() or "richiede" in content.lower(), (
        f"Stream did not return approval message for deploy. Got: {content[:300]!r}"
    )


def test_unknown_destructive_blocked_in_endpoint(client):
    r = client.post("/api/sessions")
    sid = r.json()["id"]
    r2 = client.post(
        f"/api/sessions/{sid}/messages",
        json={"message": "cancella il database di produzione", "interlocutor_id": "unknown_attacker"}
    )
    assert r2.status_code == 200
    d = r2.json()
    assert d.get("blocked") is True, f"Expected blocked=True, got: {d}"
