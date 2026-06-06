"""Tests for LearningRanker — shadow-mode memory ranking (#1248)."""
from __future__ import annotations
import json
import pytest


def _make_item(item_id, text, source="lesson", confidence=0.7, importance=0.7):
    return {
        "id": item_id,
        "text": text,
        "source": source,
        "confidence": confidence,
        "importance": importance,
        "metadata": {},
    }


# ── Init / health ─────────────────────────────────────────────────────────────

def test_learning_ranker_initializes(tmp_path):
    from igris.core.learning_ranker import LearningRanker
    r = LearningRanker(project_root=tmp_path)
    assert r is not None


def test_learning_ranker_healthcheck(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.learning_ranker import LearningRanker
    mem = UnifiedMemory(project_root=tmp_path)
    r = LearningRanker(project_root=tmp_path, unified_memory=mem)
    h = r.healthcheck()
    assert h["ok"] is True


# ── Empty dataset / fallback ──────────────────────────────────────────────────

def test_ranker_empty_items_returns_empty_report(tmp_path):
    from igris.core.learning_ranker import LearningRanker
    r = LearningRanker(project_root=tmp_path)
    report = r.rank_items("query test", [])
    assert report.ok is True
    assert report.scores == []
    assert report.metrics["dataset_size"] == 0
    assert "empty_items_list" in report.warnings


def test_ranker_empty_feedback_uses_heuristic_fallback(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.learning_ranker import LearningRanker
    mem = UnifiedMemory(project_root=tmp_path)
    r = LearningRanker(project_root=tmp_path, unified_memory=mem)
    items = [_make_item("i1", "test lesson about python")]
    report = r.rank_items("python", items)
    assert report.ok is True
    assert report.metrics["heuristic_fallback"] is True


def test_ranker_insufficient_data_warning(tmp_path):
    from igris.core.learning_ranker import LearningRanker
    r = LearningRanker(project_root=tmp_path)
    items = [_make_item("i1", "lesson text")]
    report = r.rank_items("lesson", items)
    assert "insufficient_feedback_data" in report.warnings


# ── Ranking correctness ───────────────────────────────────────────────────────

def test_ranker_keyword_match_scores_higher(tmp_path):
    from igris.core.learning_ranker import LearningRanker
    r = LearningRanker(project_root=tmp_path)
    items = [
        _make_item("match", "deploy production release"),
        _make_item("nomatch", "unrelated gardening"),
    ]
    report = r.rank_items("deploy production", items)
    assert report.ok is True
    scores_by_id = {s.item_id: s.score for s in report.scores}
    assert scores_by_id["match"] > scores_by_id["nomatch"]


def test_ranker_confidence_affects_score(tmp_path):
    from igris.core.learning_ranker import LearningRanker
    r = LearningRanker(project_root=tmp_path)
    items = [
        _make_item("high_conf", "same text", confidence=0.95),
        _make_item("low_conf", "same text", confidence=0.1),
    ]
    report = r.rank_items("same text", items)
    scores_by_id = {s.item_id: s.score for s in report.scores}
    assert scores_by_id["high_conf"] > scores_by_id["low_conf"]


def test_ranker_feedback_success_rate_affects_score(tmp_path):
    from igris.core.learning_ranker import LearningRanker
    r = LearningRanker(project_root=tmp_path)
    items = [
        _make_item("i1", "test item"),
        _make_item("i2", "test item"),
    ]
    feedback_stats = {
        "i1": {"helpful_rate": 1.0, "success_rate": 1.0},
        "i2": {"helpful_rate": 0.0, "success_rate": 0.0},
    }
    ss1 = r.score_item("test", items[0], feedback_stats=feedback_stats)
    ss2 = r.score_item("test", items[1], feedback_stats=feedback_stats)
    assert ss1.score > ss2.score


def test_ranker_source_weight_affects_score(tmp_path):
    from igris.core.learning_ranker import LearningRanker
    r = LearningRanker(project_root=tmp_path)
    items = [
        _make_item("lesson_item", "same text", source="lesson"),
        _make_item("run_event_item", "same text", source="run_event"),
    ]
    report = r.rank_items("same text", items)
    scores_by_id = {s.item_id: s.score for s in report.scores}
    assert scores_by_id["lesson_item"] > scores_by_id["run_event_item"]


def test_ranker_limit_applied(tmp_path):
    from igris.core.learning_ranker import LearningRanker
    r = LearningRanker(project_root=tmp_path)
    items = [_make_item(f"i{i}", f"text {i}") for i in range(10)]
    report = r.rank_items("text", items, limit=3)
    assert len(report.scores) == 3


def test_ranker_scores_sorted_descending(tmp_path):
    from igris.core.learning_ranker import LearningRanker
    r = LearningRanker(project_root=tmp_path)
    items = [_make_item(f"i{i}", f"keyword match {i}" if i < 3 else "unrelated") for i in range(6)]
    report = r.rank_items("keyword match", items)
    scores = [s.score for s in report.scores]
    assert scores == sorted(scores, reverse=True)


# ── Safety ────────────────────────────────────────────────────────────────────

def test_ranker_shadow_only_never_changes_decision(tmp_path):
    from igris.core.learning_ranker import LearningRanker
    r = LearningRanker(project_root=tmp_path)
    items = [_make_item("i1", "deploy production")]
    report = r.rank_items("deploy", items)
    assert report.shadow_only is True
    assert report.changed_decision is False


def test_ranker_no_raw_secret_in_report(tmp_path):
    FAKE = "FAKE_TOKEN_SHADOW_1234567890"
    from igris.core.learning_ranker import LearningRanker
    r = LearningRanker(project_root=tmp_path)
    items = [_make_item("i1", f"token={FAKE} in text")]
    report = r.rank_items(f"token={FAKE}", items)
    output = json.dumps(report.to_dict())
    assert f"token={FAKE}" not in output
    # summary too
    assert f"token={FAKE}" not in report.summary_text()


def test_ranker_no_silent_except_behavior(tmp_path):
    """If UnifiedMemory raises in healthcheck, must return ok=False not swallow."""
    import unittest.mock as mock
    from igris.core.learning_ranker import LearningRanker
    r = LearningRanker(project_root=tmp_path, unified_memory=None)
    with mock.patch("igris.core.unified_memory.UnifiedMemory.__init__",
                    side_effect=RuntimeError("disk unavailable")):
        h = r.healthcheck()
    assert h["ok"] is False
    assert "error" in h


# ── Integration ───────────────────────────────────────────────────────────────

def test_ranker_with_unified_memory_feedback_stats(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.learning_ranker import LearningRanker
    mem = UnifiedMemory(project_root=tmp_path)
    r = LearningRanker(project_root=tmp_path, unified_memory=mem)
    stats = r.load_feedback_stats()
    assert isinstance(stats, dict)  # may be empty, must not crash


def test_ranker_degraded_memory_does_not_crash(tmp_path):
    from igris.core.learning_ranker import LearningRanker
    r = LearningRanker(project_root=tmp_path, unified_memory=None)
    items = [_make_item("i1", "some lesson")]
    report = r.rank_items("lesson", items)
    assert report.ok is True  # graceful degradation
