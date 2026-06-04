"""Tests for HybridRetriever (#1242)."""
from __future__ import annotations

import pytest
from pathlib import Path


# ── Scoring helpers ────────────────────────────────────────────────────────

def test_keyword_score_matching(tmp_path):
    from igris.core.memory_retrieval_hybrid import _keyword_score
    assert _keyword_score("risposte brevi", "risposte") > _keyword_score("qualcosa else", "risposte")


def test_keyword_score_empty_query(tmp_path):
    from igris.core.memory_retrieval_hybrid import _keyword_score
    assert _keyword_score("some text", "") == 0.0


def test_keyword_score_full_match(tmp_path):
    from igris.core.memory_retrieval_hybrid import _keyword_score
    score = _keyword_score("deploy to staging", "deploy staging")
    assert score > 0.8


def test_recency_score_recent(tmp_path):
    import time
    from igris.core.memory_retrieval_hybrid import _recency_score
    now = time.time()
    assert _recency_score(now - 3600) == 1.0  # 1 hour ago


def test_recency_score_old(tmp_path):
    import time
    from igris.core.memory_retrieval_hybrid import _recency_score
    old = time.time() - 200 * 86400  # 200 days ago
    assert _recency_score(old) == 0.2


def test_recency_score_none(tmp_path):
    from igris.core.memory_retrieval_hybrid import _recency_score
    assert _recency_score(None) == 0.3


def test_compute_score_bounds(tmp_path):
    from igris.core.memory_retrieval_hybrid import _compute_score
    score = _compute_score(0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
    assert 0.0 <= score <= 1.0


# ── HybridRetriever basic ──────────────────────────────────────────────────

def test_hybrid_retrieval_without_any_backend(tmp_path):
    from igris.core.memory_retrieval_hybrid import HybridRetriever
    from igris.core.unified_memory import RetrievalResult
    r = HybridRetriever(project_root=tmp_path)
    result = r.retrieve("query", "owner", "admin", limit=5)
    assert isinstance(result, RetrievalResult)
    assert result.context == ""  # no backends -> empty context


def test_hybrid_retrieval_without_embedding_backend(tmp_path):
    from igris.core.memory_retrieval_hybrid import HybridRetriever
    from igris.core.unified_memory import RetrievalResult
    r = HybridRetriever(project_root=tmp_path, embedding_store=None)
    result = r.retrieve("query", "owner", "admin", limit=5)
    assert isinstance(result, RetrievalResult)


def test_hybrid_retrieval_empty_query(tmp_path):
    from igris.core.memory_retrieval_hybrid import HybridRetriever
    r = HybridRetriever(project_root=tmp_path)
    result = r.retrieve("", "owner", "admin")
    assert isinstance(result.items, list)


# ── Trust enforcement ──────────────────────────────────────────────────────

def test_hybrid_retrieval_untrusted_no_sensitive_items(tmp_path):
    from igris.core.memory_retrieval_hybrid import HybridRetriever
    from igris.core.long_term_memory import LongTermMemory
    ltm_path = tmp_path / ".igris" / "memory" / "long_term"
    ltm = LongTermMemory(storage_dir=str(ltm_path))
    ltm.add_entry(
        domain=f"synaptic:owner",
        content={"kind": "preference", "text": "Prefer short replies"},
        source="test", tags=[], importance=0.9,
    )
    r = HybridRetriever(project_root=tmp_path, ltm=ltm)
    result = r.retrieve("query", "unknown", "untrusted")
    for item in result.items:
        assert not (item.trust_required == "trusted" and item.safe_for_context)


def test_hybrid_retrieval_owner_untrusted_not_elevated(tmp_path):
    from igris.core.memory_retrieval_hybrid import HybridRetriever
    from igris.core.long_term_memory import LongTermMemory
    ltm_path = tmp_path / ".igris" / "memory" / "long_term"
    ltm = LongTermMemory(storage_dir=str(ltm_path))
    ltm.add_entry(
        domain="synaptic:owner",
        content={"kind": "preference", "text": "Owner preference"},
        source="test", tags=[], importance=0.9,
    )
    r = HybridRetriever(project_root=tmp_path, ltm=ltm)
    result = r.retrieve("query", "owner", "untrusted")
    sensitive = [i for i in result.items if i.trust_required == "trusted"]
    assert len(sensitive) == 0, f"Owner+untrusted got sensitive items: {sensitive}"


def test_hybrid_retrieval_admin_gets_sensitive_items(tmp_path):
    from igris.core.memory_retrieval_hybrid import HybridRetriever
    from igris.core.long_term_memory import LongTermMemory
    ltm_path = tmp_path / ".igris" / "memory" / "long_term"
    ltm = LongTermMemory(storage_dir=str(ltm_path))
    ltm.add_entry(
        domain="synaptic:owner",
        content={"kind": "preference", "text": "Prefer short replies"},
        source="test", tags=[], importance=0.9,
    )
    r = HybridRetriever(project_root=tmp_path, ltm=ltm)
    result = r.retrieve("risposte brevi", "owner", "admin")
    # admin CAN receive sensitive items
    assert isinstance(result.items, list)


# ── Degraded backends ──────────────────────────────────────────────────────

def test_hybrid_retrieval_broken_graph_not_crash(tmp_path):
    from igris.core.memory_retrieval_hybrid import HybridRetriever

    class BrokenGraph:
        def query_by_intent(self, *a, **kw):
            raise RuntimeError("graph down")

    r = HybridRetriever(project_root=tmp_path, graph=BrokenGraph())
    result = r.retrieve("query", "owner", "admin")
    assert isinstance(result.context, str)
    assert result.degraded is True


def test_hybrid_retrieval_broken_ltm_not_crash(tmp_path):
    from igris.core.memory_retrieval_hybrid import HybridRetriever

    class BrokenLTM:
        def search(self, *a, **kw):
            raise RuntimeError("ltm down")

    r = HybridRetriever(project_root=tmp_path, ltm=BrokenLTM())
    result = r.retrieve("query", "owner", "admin")
    assert isinstance(result.context, str)


def test_hybrid_retrieval_broken_conv_retriever_not_crash(tmp_path):
    from igris.core.memory_retrieval_hybrid import HybridRetriever

    class BrokenConv:
        def retrieve_for_context(self, *a, **kw):
            raise RuntimeError("conv down")

    r = HybridRetriever(project_root=tmp_path, conv_retriever=BrokenConv())
    result = r.retrieve("query", "owner", "admin")
    assert isinstance(result.context, str)
    assert result.degraded is True


# ── Context and influence report ───────────────────────────────────────────

def test_hybrid_retrieval_context_format(tmp_path):
    from igris.core.memory_retrieval_hybrid import HybridRetriever
    from igris.core.long_term_memory import LongTermMemory
    ltm_path = tmp_path / ".igris" / "memory" / "long_term"
    ltm = LongTermMemory(storage_dir=str(ltm_path))
    # LTM search does substring match, so the query must be a substring of the text
    ltm.add_entry(
        domain="lesson:myproj",
        content={"kind": "lesson", "text": "Always test before deploy"},
        source="test", tags=[], importance=0.9,
    )
    r = HybridRetriever(project_root=tmp_path, ltm=ltm)
    # "test" is a substring of the stored text so search will find it
    result = r.retrieve("test", "owner", "admin", context="mission", project="myproj")
    assert "[MEMORY CONTEXT]" in result.context


def test_hybrid_retrieval_influence_report_no_items(tmp_path):
    from igris.core.memory_retrieval_hybrid import HybridRetriever
    r = HybridRetriever(project_root=tmp_path)
    result = r.retrieve("query", "owner", "admin")
    assert "Nessun contesto" in result.influence_report


def test_influence_report_redacts_secrets(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    FAKE = "FAKE_SECRET_TOREDICT_NOTREAL_ABCDEFG"
    mem = UnifiedMemory(project_root=tmp_path)
    mem.store_lesson(f"usa token={FAKE} nel deploy", project="testproj2")
    result = mem.retrieve_for_mission("deploy token", project="testproj2")
    report = mem.memory_influence_report(result)
    assert FAKE not in report, f"Secret in influence report: {report}"


# ── Mission context ────────────────────────────────────────────────────────

def test_hybrid_retrieval_mission_boosts_lessons(tmp_path):
    from igris.core.memory_retrieval_hybrid import HybridRetriever
    from igris.core.long_term_memory import LongTermMemory
    ltm_path = tmp_path / ".igris" / "memory" / "long_term"
    ltm = LongTermMemory(storage_dir=str(ltm_path))
    ltm.add_entry(
        domain="lesson:proj",
        content={"kind": "lesson", "text": "critical lesson here"},
        source="test", tags=[], importance=0.7,
    )
    r = HybridRetriever(project_root=tmp_path, ltm=ltm)
    result = r.retrieve("critical lesson", "owner", "admin", context="mission", project="proj")
    lesson_items = [i for i in result.items if i.kind == "lesson"]
    assert len(lesson_items) >= 1


def test_hybrid_retrieval_returns_deduplicated_items(tmp_path):
    from igris.core.memory_retrieval_hybrid import HybridRetriever
    from igris.core.long_term_memory import LongTermMemory
    ltm_path = tmp_path / ".igris" / "memory" / "long_term"
    ltm = LongTermMemory(storage_dir=str(ltm_path))
    # Add the same content twice in different domains — dedup should catch it
    for domain in ["lesson:p", "decision:p"]:
        ltm.add_entry(
            domain=domain,
            content={"kind": "lesson", "text": "Deploy carefully"},
            source="test", tags=[], importance=0.8,
        )
    r = HybridRetriever(project_root=tmp_path, ltm=ltm)
    result = r.retrieve("deploy", "owner", "admin", context="mission", project="p")
    texts = [i.text for i in result.items]
    assert len(texts) == len(set(texts)), "Duplicate texts found in retrieval result"
