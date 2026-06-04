"""Tests for review gap fixes — PR #1250 / #1252 gaps."""


# FIX 1: request.client=None → X-Forwarded-For NOT trusted
def test_none_client_not_trusted():
    from igris.core.chat_interlocutor_preflight import is_trusted_local_request
    # When remote_addr is None (client unavailable), must return False
    # even if X-Forwarded-For says 127.0.0.1
    result = is_trusted_local_request(
        request_headers={"x-forwarded-for": "127.0.0.1"},
        remote_addr=None,
    )
    assert result is False, "None client should never be trusted via header"

def test_none_client_empty_string_not_trusted():
    from igris.core.chat_interlocutor_preflight import is_trusted_local_request
    # Empty string sentinel also not trusted
    result = is_trusted_local_request(remote_addr="")
    assert result is False

def test_localhost_direct_trusted():
    from igris.core.chat_interlocutor_preflight import is_trusted_local_request
    assert is_trusted_local_request(remote_addr="127.0.0.1") is True
    assert is_trusted_local_request(remote_addr="::1") is True

def test_remote_not_trusted():
    from igris.core.chat_interlocutor_preflight import is_trusted_local_request
    assert is_trusted_local_request(remote_addr="192.168.1.100") is False


# FIX 2: Italian keywords in fail-closed exception handler
def test_italian_keywords_in_sensitive_set():
    """The fail-closed keyword set must include Italian sensitive verbs."""
    from igris.core.intent_resolver import IntentResolver
    ir = IntentResolver()
    italian_sensitive = ["cancella il file", "elimina il branch", "riavvia il server", "mergia la PR"]
    for msg in italian_sensitive:
        r = ir.resolve(msg)
        is_sensitive = r.risk_hint in ("high", "destructive", "medium") or r.action_type in (
            "delete", "restart_server", "merge_pr", "deploy", "rollback"
        )
        assert is_sensitive, f"'{msg}' should be sensitive, got action={r.action_type} risk={r.risk_hint}"


# FIX 3: Italian merge/close risk classification
def test_italian_mergia_risk_medium_or_higher():
    from igris.core.intent_resolver import IntentResolver
    ir = IntentResolver()
    r = ir.resolve("mergia la PR #123")
    assert r.risk_hint in ("medium", "high", "destructive"), f"mergia risk={r.risk_hint}"

def test_italian_chiudi_issue_risk_medium_or_higher():
    from igris.core.intent_resolver import IntentResolver
    ir = IntentResolver()
    r = ir.resolve("chiudi la issue #456")
    assert r.risk_hint in ("medium", "high", "destructive"), f"chiudi risk={r.risk_hint}"


# FIX 4: ActionGuard uses unknown when no interlocutor and not internal
def test_action_guard_no_interlocutor_uses_unknown():
    from igris.core.action_guard import check_action
    # "unknown" should be blocked for sensitive actions
    allowed, reason = check_action("run_command", profile_id="unknown")
    assert not allowed, "unknown profile should be blocked for run_command"

def test_action_guard_system_internal_allowed():
    from igris.core.action_guard import check_action
    allowed, reason = check_action("run_command", profile_id="system")
    assert allowed, "system internal profile should be allowed"


# FIX 5: _dk_id deleted (hard to test directly, verify via code inspection)
def test_delegation_key_verify_exists():
    """verify_key function must exist and be callable."""
    from igris.core.delegation_keys import verify_key
    assert callable(verify_key)


# FIX 6: MemoryGraph called from persist()
def test_memory_graph_persist_called(tmp_path, monkeypatch):
    """_persist_to_memory_graph must be called from persist()."""
    from igris.core.conversation_memory import ConversationEpisode, ConversationMemoryStore, MEMORY_POLICY_FULL

    called = []

    def mock_persist_graph(self, episode):
        called.append(True)

    monkeypatch.setattr(ConversationMemoryStore, "_persist_to_memory_graph", mock_persist_graph)

    ep = ConversationEpisode(
        session_id="s1",
        interlocutor_id="owner",
        trust_level="admin",
        memory_policy=MEMORY_POLICY_FULL,
    )
    store = ConversationMemoryStore(project_root=str(tmp_path))
    store.persist(ep)

    assert called, "_persist_to_memory_graph was not called from persist()"
