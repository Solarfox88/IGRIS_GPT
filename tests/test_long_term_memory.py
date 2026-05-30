"""Tests for long-term persistent memory and gate override."""

import time
import tempfile
from pathlib import Path

import pytest

from igris.core.long_term_memory import (
    LongTermMemory,
    MemoryEntry,
    MemoryRetriever,
    GateOverride,
    OTPRecord,
)


@pytest.fixture
def memory(tmp_path: Path) -> LongTermMemory:
    return LongTermMemory(storage_dir=str(tmp_path))


@pytest.fixture
def retriever(memory: LongTermMemory) -> MemoryRetriever:
    return MemoryRetriever(memory)


@pytest.fixture
def gate_override() -> GateOverride:
    return GateOverride()


class TestLongTermMemory:
    def test_store_and_retrieve(self, memory: LongTermMemory):
        entry = memory.store("test_domain", {"key": "value"}, metadata={"source": "test"})
        assert entry.id is not None
        retrieved = memory.get(entry.id)
        assert retrieved is not None
        assert retrieved.content == {"key": "value"}

    def test_domain_index(self, memory: LongTermMemory):
        memory.store("domain_a", {"a": 1})
        memory.store("domain_b", {"b": 2})
        memory.store("domain_a", {"a": 3})
        index = memory.get_domain_index()
        assert "domain_a" in index
        assert "domain_b" in index
        assert len(index["domain_a"]) == 2

    def test_rolling_summary(self, memory: LongTermMemory):
        for i in range(5):
            memory.store("sum_domain", {"num": i})
        summary = memory.get_rolling_summary("sum_domain", max_entries=3)
        assert len(summary) <= 3

    def test_search_by_content(self, memory: LongTermMemory):
        memory.store("search_domain", {"text": "hello world"})
        memory.store("search_domain", {"text": "foo bar"})
        results = memory.search("hello")
        assert len(results) == 1
        assert results[0].content["text"] == "hello world"


class TestMemoryRetriever:
    def test_retrieve_contextual(self, retriever: MemoryRetriever, memory: LongTermMemory):
        memory.store("ctx", {"msg": "first"})
        memory.store("ctx", {"msg": "second"})
        context = retriever.retrieve_contextual("ctx", query="first")
        assert any("first" in str(entry.content) for entry in context)

    def test_retrieve_recent(self, retriever: MemoryRetriever, memory: LongTermMemory):
        memory.store("recent", {"data": "old"})
        time.sleep(0.01)
        memory.store("recent", {"data": "new"})
        recent = retriever.retrieve_recent("recent", limit=1)
        assert recent[0].content["data"] == "new"


class TestGateOverride:
    def test_generate_otp(self, gate_override: GateOverride):
        otp = gate_override.generate_otp("admin", ttl=60)
        assert len(otp) == 6
        assert gate_override.validate_otp(otp)

    def test_otp_expiry(self, gate_override: GateOverride):
        otp = gate_override.generate_otp("admin", ttl=0)
        time.sleep(0.01)
        assert not gate_override.validate_otp(otp)

    def test_audit_trail(self, gate_override: GateOverride):
        gate_override.generate_otp("user1")
        logs = gate_override.get_audit_logs()
        assert len(logs) >= 1
        assert logs[0]["user"] == "user1"

    def test_physical_approval(self, gate_override: GateOverride):
        otp = gate_override.generate_otp("admin")
        approval = gate_override.request_physical_approval(otp)
        assert approval is not None
        # Simulate physical approval
        gate_override.approve_physically(otp)
        assert gate_override.is_physically_approved(otp)
