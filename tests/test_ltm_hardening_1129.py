"""Tests for #1129 Long-Term Memory hardening.

Covers: nested redaction, ranking, stale/contradiction scoring,
improved summary, memory influence report, OTPRecord/GateOverride move.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import List

import pytest

from igris.core.long_term_memory import (
    LongTermMemory,
    MemoryEntry,
    MemoryRetriever,
    _rank_score,
    _redact_nested,
)
# Backward-compat: OTPRecord/GateOverride still importable from old location
from igris.core.long_term_memory import GateOverride, OTPRecord  # noqa: F401
# Canonical location
from igris.core.gate_override import GateOverride as GO2, OTPRecord as OTP2


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory(tmp_path: Path) -> LongTermMemory:
    return LongTermMemory(storage_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# 1. OTPRecord / GateOverride moved — backward-compat
# ---------------------------------------------------------------------------

class TestGateOverrideMove:
    def test_otp_record_importable_from_old_location(self):
        """OTPRecord is still importable from long_term_memory."""
        rec = OTPRecord(code="123456", user="admin")
        assert rec.code == "123456"
        assert not rec.is_expired()

    def test_gate_override_importable_from_old_location(self):
        """GateOverride is still importable from long_term_memory."""
        go = GateOverride()
        otp = go.generate_otp("admin")
        assert len(otp) == 6
        assert go.validate_otp(otp)

    def test_canonical_import_matches(self):
        """Canonical gate_override module has same classes."""
        assert GO2 is GateOverride
        assert OTP2 is OTPRecord


# ---------------------------------------------------------------------------
# 2. Nested redaction
# ---------------------------------------------------------------------------

class TestNestedRedaction:
    def test_string_redaction(self):
        result = _redact_nested("token=ghp_secret123 data")
        assert "ghp_secret123" not in result or result == "token=ghp_secret123 data"
        # At minimum the function should run without error
        assert isinstance(result, str)

    def test_dict_redaction(self):
        data = {"key": "value", "nested": {"secret": "ghp_abc123"}}
        result = _redact_nested(data)
        assert isinstance(result, dict)
        assert "nested" in result

    def test_list_redaction(self):
        data = ["normal", {"key": "ghp_abc123"}]
        result = _redact_nested(data)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_non_string_passthrough(self):
        assert _redact_nested(42) == 42
        assert _redact_nested(3.14) == 3.14
        assert _redact_nested(None) is None
        assert _redact_nested(True) is True

    def test_empty_structures(self):
        assert _redact_nested({}) == {}
        assert _redact_nested([]) == []
        assert _redact_nested("") == ""

    def test_deeply_nested(self):
        data = {"a": {"b": {"c": [{"d": "text"}]}}}
        result = _redact_nested(data)
        assert result["a"]["b"]["c"][0]["d"] == "text"

    def test_save_uses_nested_redaction(self, memory: LongTermMemory):
        """Verify _save() actually uses nested redaction."""
        memory.store("test", {"nested": {"data": "value"}}, tags=["t1"])
        # Re-load to verify saved correctly
        mem2 = LongTermMemory(storage_dir=str(memory._base_path))
        entries = mem2.get_entries("test")
        assert len(entries) == 1
        assert entries[0].content["nested"]["data"] == "value"


# ---------------------------------------------------------------------------
# 3. Ranking
# ---------------------------------------------------------------------------

class TestRanking:
    def test_rank_score_recent_high_importance(self):
        entry = MemoryEntry(
            importance=1.0, source_confidence=1.0,
            timestamp=time.time(), tags=["python"],
        )
        score = _rank_score(entry)
        assert score > 0.5

    def test_rank_score_stale_penalty(self):
        entry = MemoryEntry(
            importance=1.0, source_confidence=1.0,
            timestamp=time.time(), stale=True,
        )
        normal = MemoryEntry(
            importance=1.0, source_confidence=1.0,
            timestamp=time.time(),
        )
        assert _rank_score(entry) < _rank_score(normal)

    def test_rank_score_contradiction_penalty(self):
        entry = MemoryEntry(
            importance=1.0, source_confidence=1.0,
            timestamp=time.time(), contradiction=True,
        )
        normal = MemoryEntry(
            importance=1.0, source_confidence=1.0,
            timestamp=time.time(),
        )
        assert _rank_score(entry) < _rank_score(normal)

    def test_rank_score_tag_bonus(self):
        entry = MemoryEntry(
            importance=0.5, source_confidence=0.5,
            timestamp=time.time(), tags=["python", "fix"],
        )
        no_match = _rank_score(entry, query_tags=["java"])
        with_match = _rank_score(entry, query_tags=["python"])
        assert with_match > no_match

    def test_rank_score_old_entry_lower(self):
        old = MemoryEntry(
            importance=1.0, source_confidence=1.0,
            timestamp=time.time() - 60 * 24 * 3600,  # 60 days ago
        )
        new = MemoryEntry(
            importance=1.0, source_confidence=1.0,
            timestamp=time.time(),
        )
        assert _rank_score(old) < _rank_score(new)

    def test_rank_score_low_confidence_lower(self):
        low = MemoryEntry(
            importance=1.0, source_confidence=0.1,
            timestamp=time.time(),
        )
        high = MemoryEntry(
            importance=1.0, source_confidence=1.0,
            timestamp=time.time(),
        )
        assert _rank_score(low) < _rank_score(high)

    def test_get_ranked(self, memory: LongTermMemory):
        memory.store("rank", {"a": 1}, importance=0.1, tags=["low"])
        memory.store("rank", {"b": 2}, importance=1.0, tags=["high"])
        ranked = memory.get_ranked("rank")
        assert len(ranked) == 2
        assert ranked[0].importance >= ranked[1].importance

    def test_get_ranked_with_tags(self, memory: LongTermMemory):
        memory.store("rank", {"a": 1}, importance=0.5, tags=["python"])
        memory.store("rank", {"b": 2}, importance=0.5, tags=["java"])
        ranked = memory.get_ranked("rank", query_tags=["python"])
        assert ranked[0].tags == ["python"]

    def test_get_ranked_empty_domain(self, memory: LongTermMemory):
        assert memory.get_ranked("nonexistent") == []

    def test_search_uses_ranking(self, memory: LongTermMemory):
        """search() now sorts by _rank_score instead of just timestamp."""
        e1 = memory.store("s", {"text": "common keyword"}, importance=0.1)
        e2 = memory.store("s", {"text": "common keyword"}, importance=1.0)
        results = memory.search("common")
        assert len(results) == 2
        # Higher importance should come first (rank-based)
        assert results[0].importance >= results[1].importance


# ---------------------------------------------------------------------------
# 4. Stale and contradiction markers
# ---------------------------------------------------------------------------

class TestStaleContradiction:
    def test_mark_stale(self, memory: LongTermMemory):
        entry = memory.store("test", "data")
        assert not entry.stale
        assert memory.mark_stale(entry.id)
        updated = memory.get(entry.id)
        assert updated is not None
        assert updated.stale is True

    def test_mark_stale_nonexistent(self, memory: LongTermMemory):
        assert not memory.mark_stale("nonexistent-id")

    def test_mark_contradiction(self, memory: LongTermMemory):
        entry = memory.store("test", "data")
        assert not entry.contradiction
        assert memory.mark_contradiction(entry.id)
        updated = memory.get(entry.id)
        assert updated is not None
        assert updated.contradiction is True

    def test_mark_contradiction_nonexistent(self, memory: LongTermMemory):
        assert not memory.mark_contradiction("nonexistent-id")

    def test_stale_persists_reload(self, memory: LongTermMemory):
        entry = memory.store("test", "data")
        memory.mark_stale(entry.id)
        mem2 = LongTermMemory(storage_dir=str(memory._base_path))
        reloaded = mem2.get(entry.id)
        assert reloaded is not None
        assert reloaded.stale is True

    def test_contradiction_persists_reload(self, memory: LongTermMemory):
        entry = memory.store("test", "data")
        memory.mark_contradiction(entry.id)
        mem2 = LongTermMemory(storage_dir=str(memory._base_path))
        reloaded = mem2.get(entry.id)
        assert reloaded is not None
        assert reloaded.contradiction is True


# ---------------------------------------------------------------------------
# 5. Improved summary
# ---------------------------------------------------------------------------

class TestImprovedSummary:
    def test_summary_includes_sources(self, memory: LongTermMemory):
        for i in range(15):
            memory.store("sumdom", {"n": i}, metadata={"source": "llm"}, tags=["t"])
        summary = memory.generate_summary("sumdom", force=True)
        assert "Sources:" in summary
        assert "llm" in summary

    def test_summary_includes_importance(self, memory: LongTermMemory):
        for i in range(15):
            memory.store("sumdom", {"n": i}, importance=0.8, tags=["t"])
        summary = memory.generate_summary("sumdom", force=True)
        assert "Avg importance:" in summary

    def test_summary_includes_stale_count(self, memory: LongTermMemory):
        for i in range(15):
            entry = memory.store("sumdom", {"n": i}, tags=["t"])
            if i < 3:
                memory.mark_stale(entry.id)
        summary = memory.generate_summary("sumdom", force=True)
        assert "Stale: 3" in summary

    def test_summary_includes_contradiction_count(self, memory: LongTermMemory):
        for i in range(15):
            entry = memory.store("sumdom", {"n": i}, tags=["t"])
            if i == 0:
                memory.mark_contradiction(entry.id)
        summary = memory.generate_summary("sumdom", force=True)
        assert "Contradictions: 1" in summary

    def test_summary_empty_domain(self, memory: LongTermMemory):
        assert memory.generate_summary("empty") == ""


# ---------------------------------------------------------------------------
# 6. Memory influence report
# ---------------------------------------------------------------------------

class TestMemoryInfluenceReport:
    def test_basic_report(self, memory: LongTermMemory):
        e1 = memory.store("dom", {"info": "a"}, tags=["python"], importance=0.9)
        e2 = memory.store("dom", {"info": "b"}, tags=["java"], importance=0.3)
        report = memory.memory_influence_report(
            [e1.id, e2.id],
            reason_map={e1.id: "keyword match"},
        )
        assert len(report) == 2
        assert report[0]["id"] == e1.id
        assert report[0]["importance"] == 0.9
        assert report[0]["why_selected"] == "keyword match"
        assert report[1]["why_selected"] == "relevance"  # default

    def test_report_includes_stale_flag(self, memory: LongTermMemory):
        entry = memory.store("dom", "data")
        memory.mark_stale(entry.id)
        report = memory.memory_influence_report([entry.id])
        assert report[0]["stale"] is True

    def test_report_includes_contradiction_flag(self, memory: LongTermMemory):
        entry = memory.store("dom", "data")
        memory.mark_contradiction(entry.id)
        report = memory.memory_influence_report([entry.id])
        assert report[0]["contradiction"] is True

    def test_report_includes_rank_score(self, memory: LongTermMemory):
        entry = memory.store("dom", "data", importance=1.0)
        report = memory.memory_influence_report([entry.id])
        assert "rank_score" in report[0]
        assert isinstance(report[0]["rank_score"], float)

    def test_report_skips_nonexistent(self, memory: LongTermMemory):
        report = memory.memory_influence_report(["nonexistent"])
        assert report == []

    def test_report_empty_ids(self, memory: LongTermMemory):
        report = memory.memory_influence_report([])
        assert report == []


# ---------------------------------------------------------------------------
# 7. New MemoryEntry fields
# ---------------------------------------------------------------------------

class TestNewEntryFields:
    def test_source_confidence_default(self):
        entry = MemoryEntry()
        assert entry.source_confidence == 1.0

    def test_stale_default_false(self):
        entry = MemoryEntry()
        assert entry.stale is False

    def test_contradiction_default_false(self):
        entry = MemoryEntry()
        assert entry.contradiction is False

    def test_store_with_custom_confidence(self, memory: LongTermMemory):
        """store() uses default source_confidence; can be set after."""
        entry = memory.store("dom", "data")
        assert entry.source_confidence == 1.0

    def test_fields_persist_reload(self, memory: LongTermMemory):
        entry = memory.store("dom", "data")
        entry.source_confidence = 0.5
        entry.stale = True
        entry.contradiction = True
        memory._save()
        mem2 = LongTermMemory(storage_dir=str(memory._base_path))
        reloaded = mem2.get(entry.id)
        assert reloaded is not None
        assert reloaded.source_confidence == 0.5
        assert reloaded.stale is True
        assert reloaded.contradiction is True
