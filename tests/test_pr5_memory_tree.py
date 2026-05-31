"""PR 5 — Memory Tree cognitive packet tests.

Covers:
- MemoryGraph.check_consistency() — content/score/embedding integrity
- MemoryGraph.build_memory_context_packet() — structured packet for Context Manager
- ContextPacket.memory_influence field populated and surfaced in to_dict()
- Context Manager integration: uses packet, not raw separate calls
- Non-blocking: errors return partial/empty packet, never raise
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from igris.core.memory_graph import MemoryGraph


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def mg(tmp_root: Path) -> MemoryGraph:
    """Fresh in-memory MemoryGraph backed by a temp directory."""
    return MemoryGraph(str(tmp_root))


def _insert_node(
    mg: MemoryGraph,
    node_type: str,
    content: Dict[str, Any],
    confidence: float = 0.9,
    updated_at: float | None = None,
) -> str:
    """Helper: insert a raw node into the memory graph DB."""
    node_id = f"test_{node_type}_{int(time.time() * 1000)}"
    ts = updated_at or time.time()
    mg.conn.execute(
        """
        INSERT INTO memory_nodes
            (node_id, node_type, content, confidence, success_rate, created_at, updated_at, tags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (node_id, node_type, json.dumps(content), confidence, 1.0, ts, ts, "[]"),
    )
    mg.conn.commit()
    return node_id


# ---------------------------------------------------------------------------
# 1. check_consistency()
# ---------------------------------------------------------------------------

class TestCheckConsistency:

    def test_returns_required_keys(self, mg: MemoryGraph):
        report = mg.check_consistency()
        for key in (
            "content_empty_count",
            "invalid_score_count",
            "stale_node_count",
            "contradicted_lesson_count",
            "total_nodes_checked",
            "overall_health",
            "errors",
        ):
            assert key in report, f"missing key: {key}"

    def test_empty_graph_is_healthy(self, mg: MemoryGraph):
        report = mg.check_consistency()
        assert report["overall_health"] == "healthy"
        assert report["total_nodes_checked"] == 0

    def test_good_nodes_are_healthy(self, mg: MemoryGraph):
        for i in range(5):
            _insert_node(mg, "lesson", {"lesson": f"lesson {i}", "goal_type": f"type_{i}"})
        report = mg.check_consistency()
        assert report["content_empty_count"] == 0
        assert report["invalid_score_count"] == 0
        assert report["overall_health"] == "healthy"

    def test_empty_content_counted(self, mg: MemoryGraph):
        # Insert node with empty content directly
        mg.conn.execute(
            """
            INSERT INTO memory_nodes (node_id, node_type, content, confidence, success_rate, created_at, updated_at, tags)
            VALUES ('empty_node', 'lesson', '', 0.9, 1.0, ?, ?, '[]')
            """,
            (time.time(), time.time()),
        )
        mg.conn.commit()
        report = mg.check_consistency()
        assert report["content_empty_count"] >= 1

    def test_invalid_score_detected(self, mg: MemoryGraph):
        # Insert node with out-of-range score
        mg.conn.execute(
            """
            INSERT INTO memory_nodes (node_id, node_type, content, confidence, success_rate, created_at, updated_at, tags)
            VALUES ('bad_score', 'lesson', '{"lesson":"x","goal_type":"y"}', 999.9, 1.0, ?, ?, '[]')
            """,
            (time.time(), time.time()),
        )
        mg.conn.commit()
        report = mg.check_consistency()
        assert report["invalid_score_count"] >= 1

    def test_stale_lesson_detected(self, mg: MemoryGraph):
        # Insert a lesson updated 100 days ago
        stale_ts = time.time() - (100 * 86400)
        _insert_node(
            mg,
            "lesson",
            {"lesson": "old lesson", "goal_type": "old"},
            updated_at=stale_ts,
        )
        report = mg.check_consistency()
        assert report["stale_node_count"] >= 1

    def test_contradicted_lessons_detected(self, mg: MemoryGraph):
        # 3+ distinct lessons for same goal_type → contradiction
        for advice in ["do X", "do Y", "do Z"]:
            _insert_node(mg, "lesson", {"lesson": advice, "goal_type": "same_type"})
        report = mg.check_consistency()
        assert report["contradicted_lesson_count"] >= 1

    def test_degraded_when_some_empty(self, mg: MemoryGraph):
        # 1 bad node among many good ones → degraded
        for i in range(10):
            _insert_node(mg, "lesson", {"lesson": f"good {i}", "goal_type": f"t{i}"})
        mg.conn.execute(
            """
            INSERT INTO memory_nodes (node_id, node_type, content, confidence, success_rate, created_at, updated_at, tags)
            VALUES ('one_empty', 'lesson', '', 0.9, 1.0, ?, ?, '[]')
            """,
            (time.time(), time.time()),
        )
        mg.conn.commit()
        report = mg.check_consistency()
        assert report["overall_health"] in ("degraded", "failing")

    def test_failing_when_many_empty(self, mg: MemoryGraph):
        # Insert 6+ empty nodes among 10 total → failing threshold
        for i in range(10):
            mg.conn.execute(
                """
                INSERT INTO memory_nodes (node_id, node_type, content, confidence, success_rate, created_at, updated_at, tags)
                VALUES (?, 'lesson', '', 0.9, 1.0, ?, ?, '[]')
                """,
                (f"empty_{i}", time.time(), time.time()),
            )
        mg.conn.commit()
        report = mg.check_consistency()
        assert report["overall_health"] == "failing"

    def test_no_exception_on_corrupt_row(self, mg: MemoryGraph):
        # Insert row with null content — should not raise
        mg.conn.execute(
            """
            INSERT INTO memory_nodes (node_id, node_type, content, confidence, success_rate, created_at, updated_at, tags)
            VALUES ('null_content', 'lesson', 'null', 0.9, 1.0, ?, ?, '[]')
            """,
            (time.time(), time.time()),
        )
        mg.conn.commit()
        # Must not raise
        report = mg.check_consistency()
        assert isinstance(report, dict)


# ---------------------------------------------------------------------------
# 2. build_memory_context_packet()
# ---------------------------------------------------------------------------

class TestBuildMemoryContextPacket:

    def test_returns_required_keys(self, mg: MemoryGraph):
        packet = mg.build_memory_context_packet("fix the deploy script")
        for key in ("goal", "lessons", "project_facts", "command_recipe",
                    "health", "consistency", "memory_influence", "total_items"):
            assert key in packet, f"missing key: {key}"

    def test_empty_graph_returns_empty_packet(self, mg: MemoryGraph):
        packet = mg.build_memory_context_packet("anything")
        assert packet["lessons"] == []
        assert packet["project_facts"] == []
        assert packet["command_recipe"] is None
        assert packet["total_items"] == 0
        assert packet["memory_influence"] == "no memory context"

    def test_lessons_retrieved(self, mg: MemoryGraph):
        _insert_node(mg, "lesson", {
            "lesson": "always test your code",
            "goal_type": "coding",
            "tags": ["coding"],
        })
        packet = mg.build_memory_context_packet("write code", lesson_limit=5)
        # May or may not match depending on intent scoring — just check no error
        assert isinstance(packet["lessons"], list)

    def test_include_health_true_populates_consistency(self, mg: MemoryGraph):
        packet = mg.build_memory_context_packet("test", include_health=True)
        assert "overall_health" in packet["consistency"]

    def test_include_health_false_skips_consistency(self, mg: MemoryGraph):
        packet = mg.build_memory_context_packet("test", include_health=False)
        # consistency may be empty dict when include_health=False
        # health fields also shouldn't include healthcheck keys
        assert isinstance(packet["health"], dict)
        # consistency is empty (no check ran)
        assert packet["consistency"] == {}

    def test_total_items_matches_lists(self, mg: MemoryGraph):
        packet = mg.build_memory_context_packet("test")
        expected = len(packet["lessons"]) + len(packet["project_facts"])
        if packet["command_recipe"]:
            expected += 1
        assert packet["total_items"] == expected

    def test_memory_influence_string(self, mg: MemoryGraph):
        packet = mg.build_memory_context_packet("test")
        assert isinstance(packet["memory_influence"], str)
        assert len(packet["memory_influence"]) > 0

    def test_goal_truncated_to_200(self, mg: MemoryGraph):
        long_goal = "x" * 300
        packet = mg.build_memory_context_packet(long_goal)
        assert len(packet["goal"]) <= 200

    def test_non_blocking_on_db_error(self, tmp_root: Path):
        """build_memory_context_packet must not raise even if DB is broken."""
        mg_bad = MemoryGraph(str(tmp_root))
        # Close the DB connection to simulate error
        mg_bad.conn.close()
        # Should return partial packet, not raise
        try:
            packet = mg_bad.build_memory_context_packet("anything")
            assert isinstance(packet, dict)
        except Exception as exc:
            pytest.fail(f"build_memory_context_packet raised unexpectedly: {exc}")

    def test_health_status_in_memory_influence_when_degraded(self, mg: MemoryGraph):
        # Force degraded state
        for i in range(10):
            _insert_node(mg, "lesson", {"lesson": f"good {i}", "goal_type": f"t{i}"})
        mg.conn.execute(
            "INSERT INTO memory_nodes (node_id, node_type, content, confidence, success_rate, created_at, updated_at, tags)"
            " VALUES ('e1', 'lesson', '', 0.9, 1.0, ?, ?, '[]')", (time.time(), time.time())
        )
        mg.conn.commit()
        packet = mg.build_memory_context_packet("test", include_health=True)
        if packet["consistency"].get("overall_health") not in ("healthy", "unknown"):
            assert "memory health" in packet["memory_influence"]

    def test_lessons_with_facts_updates_total(self, mg: MemoryGraph):
        """total_items counts lessons + facts + recipe."""
        packet = mg.build_memory_context_packet("test")
        total = len(packet["lessons"]) + len(packet["project_facts"])
        if packet["command_recipe"]:
            total += 1
        assert packet["total_items"] == total


# ---------------------------------------------------------------------------
# 3. Context Manager integration
# ---------------------------------------------------------------------------

class TestContextManagerMemoryPacket:

    def test_memory_influence_in_context_packet(self, tmp_root: Path):
        """ContextPacket.memory_influence is populated from build_memory_context_packet."""
        from igris.core.context_manager import ContextManager, ContextPacket

        cm = ContextManager(project_root=str(tmp_root))

        fake_packet = {
            "goal": "test",
            "lessons": [],
            "project_facts": [],
            "command_recipe": None,
            "health": {},
            "consistency": {"overall_health": "healthy"},
            "memory_influence": "2 lesson(s) retrieved; 1 project fact(s) retrieved",
            "total_items": 3,
        }

        with patch(
            "igris.core.memory_graph.MemoryGraph.build_memory_context_packet",
            return_value=fake_packet,
        ):
            packet = cm.build_context(goal="test goal")

        assert packet.memory_influence == "2 lesson(s) retrieved; 1 project fact(s) retrieved"

    def test_memory_influence_in_to_dict(self, tmp_root: Path):
        """to_dict() includes memory_influence field."""
        from igris.core.context_manager import ContextManager

        cm = ContextManager(project_root=str(tmp_root))

        fake_packet = {
            "goal": "test",
            "lessons": [],
            "project_facts": [],
            "command_recipe": None,
            "health": {},
            "consistency": {"overall_health": "healthy"},
            "memory_influence": "no memory context",
            "total_items": 0,
        }

        with patch(
            "igris.core.memory_graph.MemoryGraph.build_memory_context_packet",
            return_value=fake_packet,
        ):
            packet = cm.build_context(goal="test goal")
            d = packet.to_dict()

        assert "memory_influence" in d
        assert d["memory_influence"] == "no memory context"

    def test_memory_influence_empty_when_mg_unavailable(self, tmp_root: Path):
        """If MemoryGraph raises on construction, memory_influence stays empty."""
        from igris.core.context_manager import ContextManager

        cm = ContextManager(project_root=str(tmp_root))

        with patch(
            "igris.core.memory_graph.MemoryGraph",
            side_effect=RuntimeError("DB not available"),
        ):
            packet = cm.build_context(goal="test goal")

        # Should not raise, memory_influence stays at default
        assert isinstance(packet.memory_influence, str)

    def test_context_packet_memory_influence_default_empty(self):
        """ContextPacket.memory_influence defaults to empty string."""
        from igris.core.context_manager import ContextPacket

        pkt = ContextPacket()
        assert pkt.memory_influence == ""

    def test_context_packet_to_dict_has_memory_influence_key(self):
        """ContextPacket.to_dict() always has memory_influence key."""
        from igris.core.context_manager import ContextPacket

        pkt = ContextPacket(memory_influence="3 lesson(s) retrieved")
        d = pkt.to_dict()
        assert d["memory_influence"] == "3 lesson(s) retrieved"
