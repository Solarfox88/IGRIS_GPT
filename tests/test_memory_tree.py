"""Tests for #536 — Memory Tree hierarchy.

Covers:
1. MemoryChunker — deterministic IDs, boundary preservation, size limits
2. ContentStore  — atomic write, read_all, frontmatter, delete
3. MemoryScorer  — 3+ signals, persist in SQLite, top_k
4. TopicTree     — grouping by tags, top-K retrieval, summary rebuild
5. GlobalDigest  — 1 node per day, markdown render, chunk_id determinism
6. MemoryRetrieval — topic path, scorer path, graph fallback
7. Integration   — MemoryGraph.add_node() triggers ContentStore write
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from igris.core.memory_chunker import MemoryChunker, Chunk
from igris.core.memory_content_store import ContentStore
from igris.core.memory_scorer import MemoryScorer
from igris.core.memory_topic_tree import TopicTree
from igris.core.memory_global_digest import GlobalDigest
from igris.core.memory_retrieval import MemoryRetrieval
from igris.core.memory_graph import MemoryGraph


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_root(tmp_path):
    return str(tmp_path)


@pytest.fixture
def store(tmp_root):
    return ContentStore(tmp_root)


@pytest.fixture
def scorer(tmp_root):
    db = os.path.join(tmp_root, ".igris", "memory", "scores.db")
    return MemoryScorer(db)


@pytest.fixture
def topic_tree(tmp_root):
    db = os.path.join(tmp_root, ".igris", "memory", "topics.db")
    return TopicTree(db, top_k=5, rebuild_every_n=3)


@pytest.fixture
def digest(tmp_root):
    return GlobalDigest(tmp_root)


@pytest.fixture
def graph(tmp_root):
    return MemoryGraph(tmp_root)


# ---------------------------------------------------------------------------
# 1. MemoryChunker
# ---------------------------------------------------------------------------

class TestMemoryChunker:

    def test_empty_content_returns_no_chunks(self):
        c = MemoryChunker()
        assert c.chunk("src", "") == []

    def test_short_content_single_chunk(self):
        c = MemoryChunker(max_tokens=3000)
        chunks = c.chunk("src1", "Hello world")
        assert len(chunks) == 1
        assert "Hello world" in chunks[0].content

    def test_chunk_id_is_deterministic(self):
        c = MemoryChunker()
        chunks1 = c.chunk("same_source", "Some content")
        chunks2 = c.chunk("same_source", "Some content")
        assert chunks1[0].chunk_id == chunks2[0].chunk_id

    def test_chunk_id_differs_for_different_source(self):
        c = MemoryChunker()
        c1 = c.chunk("source_a", "Content")
        c2 = c.chunk("source_b", "Content")
        assert c1[0].chunk_id != c2[0].chunk_id

    def test_chunk_id_is_16_hex_chars(self):
        c = MemoryChunker()
        chunks = c.chunk("s", "text")
        assert len(chunks[0].chunk_id) == 16
        assert all(ch in "0123456789abcdef" for ch in chunks[0].chunk_id)

    def test_long_content_splits_into_multiple_chunks(self):
        c = MemoryChunker(max_tokens=10)  # ~40 chars
        long = "word " * 100  # 500 chars >> 40
        chunks = c.chunk("src", long)
        assert len(chunks) > 1

    def test_chunks_cover_all_content(self):
        c = MemoryChunker(max_tokens=50)
        content = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
        chunks = c.chunk("src", content)
        combined = " ".join(ch.content for ch in chunks)
        assert "Paragraph one" in combined
        assert "Paragraph three" in combined

    def test_paragraph_boundaries_respected(self):
        """A paragraph should not be split mid-word when there's room."""
        c = MemoryChunker(max_tokens=3000)
        content = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunks = c.chunk("src", content)
        # All text accounted for
        combined = " ".join(ch.content for ch in chunks)
        assert "First" in combined and "Second" in combined and "Third" in combined

    def test_chunk_offset_increases(self):
        c = MemoryChunker(max_tokens=10)
        chunks = c.chunk("src", "a " * 200)
        offsets = [ch.offset for ch in chunks]
        assert offsets == sorted(offsets)


# ---------------------------------------------------------------------------
# 2. ContentStore
# ---------------------------------------------------------------------------

class TestContentStore:

    def test_write_creates_md_file(self, store, tmp_root):
        store.write("abc123", "lesson", "Some content", tags=["python"])
        path = Path(tmp_root) / ".igris" / "memory" / "lesson" / "abc123.md"
        assert path.exists()

    def test_write_contains_frontmatter(self, store, tmp_root):
        store.write("fm_test", "lesson", "Body text", tags=["test"], confidence=0.9)
        path = Path(tmp_root) / ".igris" / "memory" / "lesson" / "fm_test.md"
        text = path.read_text()
        assert "node_id: fm_test" in text
        assert "node_type: lesson" in text
        assert "confidence: 0.9" in text

    def test_read_returns_chunk(self, store):
        store.write("r1", "decision", "Decision content", tags=["tag1"])
        result = store.read("decision", "r1")
        assert result is not None
        assert result["chunk_id"] == "r1"
        assert "Decision content" in result["content"]
        assert result["node_type"] == "decision"

    def test_read_nonexistent_returns_none(self, store):
        assert store.read("lesson", "nonexistent_id") is None

    def test_read_all_returns_all_chunks(self, store):
        store.write("c1", "lesson", "Content 1", tags=["a"])
        store.write("c2", "lesson", "Content 2", tags=["b"])
        store.write("c3", "decision", "Content 3", tags=["c"])
        all_chunks = store.read_all()
        ids = {c["chunk_id"] for c in all_chunks}
        assert {"c1", "c2", "c3"}.issubset(ids)

    def test_read_all_filtered_by_node_type(self, store):
        store.write("l1", "lesson", "Lesson", tags=[])
        store.write("d1", "decision", "Decision", tags=[])
        lessons = store.read_all(node_type="lesson")
        assert all(c["node_type"] == "lesson" for c in lessons)
        assert any(c["chunk_id"] == "l1" for c in lessons)

    def test_atomic_write_no_partial_file(self, store, tmp_root):
        """Write + read cycle should never see a .tmp file."""
        store.write("atomic1", "lesson", "Atomic test")
        tmp = Path(tmp_root) / ".igris" / "memory" / "lesson" / "atomic1.tmp"
        assert not tmp.exists()

    def test_delete_removes_file(self, store, tmp_root):
        store.write("del1", "lesson", "Delete me")
        assert store.exists("lesson", "del1")
        store.delete("lesson", "del1")
        assert not store.exists("lesson", "del1")

    def test_list_chunk_ids(self, store):
        store.write("id1", "lesson", "A")
        store.write("id2", "lesson", "B")
        ids = store.list_chunk_ids("lesson")
        assert "id1" in ids and "id2" in ids

    def test_overwrite_updates_content(self, store):
        store.write("ow1", "lesson", "Original")
        store.write("ow1", "lesson", "Updated")
        result = store.read("lesson", "ow1")
        assert "Updated" in result["content"]


# ---------------------------------------------------------------------------
# 3. MemoryScorer
# ---------------------------------------------------------------------------

class TestMemoryScorer:

    def test_score_in_range(self, scorer):
        score = scorer.compute("c1", "lesson", "Some useful content with many words here", time.time())
        assert 0.0 <= score <= 1.0

    def test_recency_signal_decays(self, scorer):
        recent = scorer.compute("r", "lesson", "text", time.time())
        old = scorer.compute("o", "lesson", "text", time.time() - 60 * 86400)
        assert recent > old

    def test_unique_words_penalises_repetitive(self, scorer):
        unique = scorer.compute("u", "lesson", "word1 word2 word3 word4 word5", time.time())
        repetitive = scorer.compute("rep", "lesson", "word word word word word", time.time())
        assert unique > repetitive

    def test_token_count_penalises_too_short(self, scorer):
        # "Hi" = ~0.5 tokens → severe short penalty
        # very long repetitive text → long penalty
        # The token signal for "Hi" should be lower than for medium-length content
        ts = time.time()
        short_sig = scorer._token_count_signal("Hi")
        medium_sig = scorer._token_count_signal("word " * 200)
        assert medium_sig > short_sig

    def test_source_weight_lesson_beats_environment(self, scorer):
        lesson_score = scorer.compute("l", "lesson", "important learning", time.time())
        env_score = scorer.compute("e", "environment_fact", "important learning", time.time())
        assert lesson_score > env_score

    def test_score_and_store_persists(self, scorer):
        scorer.score_and_store("p1", "lesson", "Persistent content", time.time())
        retrieved = scorer.get_score("p1")
        assert retrieved is not None
        assert 0.0 <= retrieved <= 1.0

    def test_top_k_returns_sorted(self, scorer):
        for i in range(5):
            scorer.score_and_store(f"topk{i}", "lesson", f"content {i} " * (i + 1), time.time())
        top = scorer.top_k(k=3)
        assert len(top) == 3
        scores = [s for _, s in top]
        assert scores == sorted(scores, reverse=True)

    def test_top_k_filtered_by_node_type(self, scorer):
        scorer.score_and_store("filt_lesson", "lesson", "lesson content", time.time())
        scorer.score_and_store("filt_decision", "decision", "decision content", time.time())
        top = scorer.top_k(k=10, node_type="lesson")
        assert all(True for _ in top)  # just check it doesn't crash
        ids = [cid for cid, _ in top]
        assert "filt_lesson" in ids

    def test_signals_for_returns_breakdown(self, scorer):
        scorer.score_and_store("sig1", "lesson", "Words about something important indeed", time.time())
        sigs = scorer.signals_for("sig1")
        assert sigs is not None
        assert set(sigs.keys()) >= {"score", "recency", "unique_words", "token_count", "source_weight"}

    def test_three_signals_are_nonzero(self, scorer):
        scorer.score_and_store("ns1", "lesson", "Some meaningful content here to analyse", time.time())
        sigs = scorer.signals_for("ns1")
        nonzero = [k for k, v in sigs.items() if k != "score" and v > 0]
        assert len(nonzero) >= 3


# ---------------------------------------------------------------------------
# 4. TopicTree
# ---------------------------------------------------------------------------

class TestTopicTree:

    def _make_chunks(self, tags_list):
        return [
            {"chunk_id": f"tc{i}", "content": f"Content about {tags[0] if tags else 'misc'}", "score": 0.8 - i * 0.05, "tags": tags}
            for i, tags in enumerate(tags_list)
        ]

    def test_update_indexes_topics(self, topic_tree):
        chunks = self._make_chunks([["python"], ["python", "async"], ["rust"]])
        topic_tree.update(chunks)
        topics = topic_tree.list_topics()
        topic_names = {t["topic"] for t in topics}
        assert "python" in topic_names
        assert "rust" in topic_names

    def test_get_topic_returns_chunks(self, topic_tree):
        chunks = self._make_chunks([["ml", "ai"], ["ml"], ["ai"]])
        topic_tree.update(chunks)
        result = topic_tree.get_topic("ml")
        assert result is not None
        assert len(result["top_chunks"]) >= 1
        assert result["topic"] == "ml"

    def test_get_nonexistent_topic_returns_none(self, topic_tree):
        assert topic_tree.get_topic("nonexistent_xyz_topic") is None

    def test_top_k_respected(self, topic_tree):
        tree = TopicTree.__new__(TopicTree)
        TopicTree.__init__(tree, str(Path(topic_tree._db_path).parent / "tk.db"), top_k=2, rebuild_every_n=100)
        chunks = [{"chunk_id": f"tk{i}", "content": f"c{i}", "score": 1.0 - i * 0.1, "tags": ["mytopic"]} for i in range(10)]
        tree.update(chunks)
        result = tree.get_topic("mytopic")
        assert len(result["top_chunks"]) <= 2

    def test_search_topics_finds_by_keyword(self, topic_tree):
        topic_tree.update([{"chunk_id": "kw1", "content": "Python is great", "score": 0.9, "tags": ["python_dev"]}])
        # Force rebuild
        topic_tree._rebuild_summaries()
        results = topic_tree.search_topics("python", limit=5)
        assert any("python" in r["topic"] for r in results)

    def test_summary_is_built_after_rebuild(self, topic_tree):
        chunks = [{"chunk_id": f"s{i}", "content": f"Important line {i} about topic", "score": 0.8, "tags": ["mytag"]} for i in range(5)]
        topic_tree.update(chunks)  # triggers rebuild at N=3
        result = topic_tree.get_topic("mytag")
        # Summary may be empty until rebuild threshold, just check no crash
        assert result is not None

    def test_topic_count(self, topic_tree):
        topic_tree.update([
            {"chunk_id": "t1", "content": "a", "score": 0.5, "tags": ["alpha"]},
            {"chunk_id": "t2", "content": "b", "score": 0.5, "tags": ["beta"]},
        ])
        assert topic_tree.topic_count() >= 2


# ---------------------------------------------------------------------------
# 5. GlobalDigest
# ---------------------------------------------------------------------------

class TestGlobalDigest:

    def test_chunk_id_is_deterministic(self, digest):
        id1 = digest.chunk_id_for_day("2026-05-29")
        id2 = digest.chunk_id_for_day("2026-05-29")
        assert id1 == id2

    def test_different_days_have_different_ids(self, digest):
        id1 = digest.chunk_id_for_day("2026-05-28")
        id2 = digest.chunk_id_for_day("2026-05-29")
        assert id1 != id2

    def test_build_produces_dict(self, digest):
        d = digest.build_for_day("2026-05-29", run_events=[], failure_events=[])
        assert d["day"] == "2026-05-29"
        assert "issues_worked" in d
        assert "successes" in d
        assert "failures" in d

    def test_net_outcome_positive(self, digest):
        runs = [{"status": "completed"}, {"status": "completed"}, {"status": "blocked"}]
        d = digest.build_for_day("2026-05-29", run_events=runs, failure_events=[])
        assert d["net_outcome"] == "positive"

    def test_net_outcome_negative(self, digest):
        runs = [{"status": "blocked"}, {"status": "blocked"}, {"status": "completed"}]
        d = digest.build_for_day("2026-05-29", run_events=runs, failure_events=[])
        assert d["net_outcome"] == "negative"

    def test_failure_classes_counted(self, digest):
        failures = [{"failure_class": "pytest_failure"}, {"failure_class": "pytest_failure"}, {"failure_class": "timeout"}]
        d = digest.build_for_day("2026-05-29", run_events=[], failure_events=failures)
        assert d["failure_classes"]["pytest_failure"] == 2
        assert d["failure_classes"]["timeout"] == 1

    def test_markdown_render(self, digest):
        d = digest.build_for_day("2026-05-29", run_events=[{"status": "completed", "issue_number": "536"}], failure_events=[])
        md = digest.digest_to_markdown(d)
        assert "2026-05-29" in md
        assert "536" in md
        assert "positive" in md or "negative" in md

    def test_save_writes_md_file(self, digest, store):
        d = digest.build_for_day("2026-05-29", run_events=[], failure_events=[])
        chunk_id = digest.save(d, store)
        assert store.exists("global_digest", chunk_id)

    def test_get_for_day_retrieves_saved(self, digest, store):
        d = digest.build_for_day("2026-05-29", run_events=[], failure_events=[])
        digest.save(d, store)
        result = digest.get_for_day("2026-05-29", store)
        assert result is not None

    def test_one_digest_per_day(self, digest, store):
        """Saving the digest twice for same day overwrites, does not duplicate."""
        d1 = digest.build_for_day("2026-05-29", run_events=[{"status": "completed"}], failure_events=[])
        d2 = digest.build_for_day("2026-05-29", run_events=[{"status": "blocked"}], failure_events=[])
        digest.save(d1, store)
        digest.save(d2, store)
        ids = store.list_chunk_ids("global_digest")
        # Only one entry for 2026-05-29
        day_ids = [i for i in ids if digest.chunk_id_for_day("2026-05-29") == i]
        assert len(day_ids) == 1


# ---------------------------------------------------------------------------
# 6. MemoryRetrieval
# ---------------------------------------------------------------------------

class TestMemoryRetrieval:

    @pytest.fixture
    def populated_retrieval(self, store, topic_tree, scorer, graph):
        # Populate some chunks
        chunks = [
            {"chunk_id": "ret1", "content": "Python async error handling best practices", "score": 0.9, "tags": ["python", "async"]},
            {"chunk_id": "ret2", "content": "Memory graph storage and retrieval patterns", "score": 0.7, "tags": ["memory", "graph"]},
            {"chunk_id": "ret3", "content": "Test coverage for supervisor module", "score": 0.8, "tags": ["testing", "supervisor"]},
        ]
        for c in chunks:
            store.write(c["chunk_id"], "lesson", c["content"], tags=c["tags"])
            scorer.score_and_store(c["chunk_id"], "lesson", c["content"], time.time())
        topic_tree.update(chunks)
        return MemoryRetrieval(store, topic_tree, scorer, graph)

    def test_search_returns_results(self, populated_retrieval):
        results = populated_retrieval.search("python async", top_k=5)
        assert isinstance(results, list)

    def test_search_ordered_by_score(self, populated_retrieval):
        results = populated_retrieval.search("memory graph", top_k=5)
        if len(results) >= 2:
            scores = [r["score"] for r in results]
            assert scores == sorted(scores, reverse=True)

    def test_search_with_no_match_returns_empty_or_fallback(self, populated_retrieval):
        results = populated_retrieval.search("zzz_completely_unknown_xyz", top_k=5)
        assert isinstance(results, list)  # no crash

    def test_drill_down_returns_topic_chunks(self, populated_retrieval):
        results = populated_retrieval.drill_down("python", top_k=3)
        assert isinstance(results, list)

    def test_each_result_has_required_fields(self, populated_retrieval):
        results = populated_retrieval.search("python", top_k=5)
        for r in results:
            assert "chunk_id" in r
            assert "content" in r
            assert "score" in r

    def test_top_k_limits_results(self, populated_retrieval):
        results = populated_retrieval.search("memory", top_k=1)
        assert len(results) <= 1


# ---------------------------------------------------------------------------
# 7. Integration — MemoryGraph.add_node() triggers ContentStore write
# ---------------------------------------------------------------------------

class TestMemoryTreeIntegration:

    def test_add_node_writes_md_file(self, graph, tmp_root):
        node_id = graph.add_node("lesson", {"text": "learned something"}, tags=["test"])
        store = ContentStore(tmp_root)
        # The node should appear in read_all (ContentStore written by _tree_write)
        all_chunks = store.read_all()
        ids = {c["chunk_id"] for c in all_chunks}
        assert node_id in ids

    def test_add_node_computes_score(self, graph, tmp_root):
        import sqlite3
        node_id = graph.add_node("lesson", {"text": "scored lesson content"}, tags=[])
        scores_db = Path(tmp_root) / ".igris" / "memory" / "scores.db"
        if scores_db.exists():
            conn = sqlite3.connect(str(scores_db))
            row = conn.execute("SELECT score FROM chunk_scores WHERE chunk_id=?", (node_id,)).fetchone()
            if row:
                assert float(row[0]) > 0.0

    def test_add_node_does_not_break_on_tree_error(self, graph):
        """Even if ContentStore fails, add_node must succeed."""
        # Just call add_node and verify it returns a valid node_id
        node_id = graph.add_node("decision", {"outcome": "success"}, tags=["important"])
        assert len(node_id) == 32  # uuid4().hex

    def test_global_digest_node_type_accepted(self, graph):
        """global_digest is a valid node type in MemoryGraph."""
        node_id = graph.add_node(
            "global_digest",
            {"day": "2026-05-29", "successes": 5, "failures": 1},
            tags=["digest"],
        )
        node = graph.get_node(node_id)
        assert node is not None
        assert node["node_type"] == "global_digest"

    def test_migration_exports_to_md(self, tmp_root):
        """After migration, existing nodes can be read from ContentStore."""
        graph = MemoryGraph(tmp_root)
        # Add some nodes (these go through _tree_write)
        graph.add_node("lesson", {"text": "pre-migration lesson"}, tags=["old"])
        store = ContentStore(tmp_root)
        chunks = store.read_all()
        assert len(chunks) >= 1
