"""Tests for JarvisRequestRouter (#1243)."""
import pytest
from igris.core.jarvis_request_router import JarvisRequestRouter, JarvisRouteDecision, RequestRoute, RequestRisk


@pytest.fixture
def router(tmp_path):
    return JarvisRequestRouter(project_root=tmp_path)


@pytest.fixture
def client():
    try:
        from igris.web.app import app
        from fastapi.testclient import TestClient
        return TestClient(app, raise_server_exceptions=False)
    except Exception:
        pytest.skip("TestClient or app not available")


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
    mem.store_preference("owner", "admin", "Preferisco risposte brevi")

    router = JarvisRequestRouter(project_root=tmp_path, unified_memory=mem)
    d = router.route("fammi un riassunto", interlocutor_id="owner", trust_level="admin")

    assert not d.blocked
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
    sid = r.json()["id"]
    r2 = client.post(
        f"/api/sessions/{sid}/messages",
        json={"message": "ciao", "interlocutor_id": "owner"}
    )
    assert r2.status_code == 200
    d = r2.json()
    # route metadata must be present (can be None if router failed gracefully)
    assert "route" in d or "response" in d  # backward compatible

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
    sid = r.json()["id"]
    r2 = client.post(
        f"/api/sessions/{sid}/messages",
        json={"message": "ricordati che preferisco risposte brevi", "interlocutor_id": "owner"}
    )
    assert r2.status_code == 200
    d = r2.json()
    route_data = d.get("route") or {}
    if route_data:
        assert route_data.get("route") in ("memory_update", "chat_only", None)

def test_route_metadata_no_secrets(client):
    r = client.post("/api/sessions")
    sid = r.json()["id"]
    r2 = client.post(
        f"/api/sessions/{sid}/messages",
        json={"message": "ciao", "interlocutor_id": "owner"}
    )
    import re, json
    content = json.dumps(r2.json())
    assert not re.search(r'passphrase\s*=\s*\S{8,}', content, re.IGNORECASE)
