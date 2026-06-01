from __future__ import annotations

import json
import time
from pathlib import Path

from igris.core.memory_graph import MemoryGraph
from igris.core.memory_content_store import ContentStore
from igris.core.memory_global_digest import GlobalDigest
from igris.core.memory_retrieval import MemoryRetrieval
from igris.core.memory_scorer import MemoryScorer
from igris.core.memory_topic_tree import TopicTree


def _make_graph(tmp_path: Path) -> MemoryGraph:
    return MemoryGraph(str(tmp_path))


def _set_node_meta(graph: MemoryGraph, node_id: str, *, updated_at: float, tags: str) -> None:
    with graph._lock:  # noqa: SLF001 - test helper only
        graph.conn.execute(
            "UPDATE memory_nodes SET updated_at=?, tags=? WHERE node_id=?",
            (updated_at, tags, node_id),
        )
        graph.conn.commit()


def test_pipeline_report_exposes_all_hierarchical_stages(tmp_path: Path) -> None:
    graph = _make_graph(tmp_path)
    graph.add_node("lesson", {"goal": "memory tree", "text": "memory topic lessons"}, tags=["memory", "topic"])
    graph.add_node("project_fact", {"goal": "memory tree", "fact": "global digest is ready"}, tags=["memory"])

    store = graph.project_root / ".igris" / "memory"
    digest = GlobalDigest(str(tmp_path))
    digest.save(
        digest.build_for_day(
            "2026-06-01",
            run_events=[{"status": "completed", "issue_number": "1156"}],
            failure_events=[],
            topic_names=["memory"],
        ),
        content_store=ContentStore(str(tmp_path)),
    )

    report = graph.build_memory_tree_pipeline_report("memory tree", top_k=3)

    assert report["status"] == "healthy"
    assert report["degraded"] is False
    assert [stage["name"] for stage in report["stages"]] == [
        "source_event",
        "topic_digest",
        "global_digest",
        "retrieval_multilevel",
        "context_flow",
    ]
    assert report["topic_hits"]
    assert report["global_digest"] is not None
    assert report["retrieved"]
    assert report["penalties"] == {"stale": 0, "contradiction": 0}


def test_pipeline_report_surfaces_degraded_memory_and_penalties(tmp_path: Path) -> None:
    graph = _make_graph(tmp_path)
    node_id = graph.add_node("lesson", {"goal": "memory tree", "outcome": "failure", "advice": "same"}, tags=["stale", "contradicted"])
    _set_node_meta(graph, node_id, updated_at=time.time() - (240 * 86400), tags='["stale", "contradicted"]')

    report = graph.build_memory_tree_pipeline_report("memory tree", top_k=3)

    assert report["degraded"] is True
    assert "stale_penalty_applied" in report["reasons"] or "contradiction_penalty_applied" in report["reasons"]
    assert report["penalties"]["stale"] >= 1
    assert report["penalties"]["contradiction"] >= 1
    assert report["stages"][-1]["status"] == "degraded"


def test_reindex_report_is_safe_and_reflects_legacy_sources(tmp_path: Path) -> None:
    graph = _make_graph(tmp_path)
    legacy_dir = Path(tmp_path) / ".igris" / "memory"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "decisions.json").write_text(json.dumps([{"event_type": "decision", "timestamp": 1.0}]), encoding="utf-8")

    report = graph.get_memory_reindex_report()
    assert report["safe"] is True
    assert report["status"] == "pending"
    assert report["legacy_sources_found"] is True
    assert report["recommended_action"] == "migrate_legacy"

    graph.migrate_legacy(str(tmp_path))
    done = graph.get_memory_reindex_report()
    assert done["status"] == "done"
    assert done["already_migrated"] is True


def test_build_memory_context_packet_embeds_pipeline_and_reindex(tmp_path: Path) -> None:
    graph = _make_graph(tmp_path)
    graph.add_node("lesson", {"goal": "memory tree", "text": "memory tree context"}, tags=["memory"])
    digest = GlobalDigest(str(tmp_path))
    digest.save(
        digest.build_for_day(
            "2026-06-01",
            run_events=[{"status": "completed", "issue_number": "1156"}],
            failure_events=[],
            topic_names=["memory"],
        ),
        content_store=ContentStore(str(tmp_path)),
    )

    packet = graph.build_memory_context_packet("memory tree", include_health=True)
    assert "pipeline" in packet
    assert "reindex" in packet
    assert packet["pipeline"]["stages"][0]["name"] == "source_event"
    assert packet["reindex"]["safe"] is True
    assert "memory_influence" in packet
