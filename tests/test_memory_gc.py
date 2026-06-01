from __future__ import annotations

import time
from pathlib import Path

from igris.core.memory_gc import MemoryGCPolicy, MemoryGarbageCollector
from igris.core.memory_graph import MemoryGraph


def _set_node_meta(graph: MemoryGraph, node_id: str, *, updated_at: float, tags: str = "[]", confidence: float = 0.2, success_rate: float = 0.2) -> None:
    with graph._lock:  # noqa: SLF001 - test helper only
        graph.conn.execute(
            "UPDATE memory_nodes SET updated_at=?, confidence=?, success_rate=?, tags=? WHERE node_id=?",
            (updated_at, confidence, success_rate, tags, node_id),
        )
        graph.conn.commit()


def test_dry_run_scan_does_not_delete(tmp_path: Path) -> None:
    mg = MemoryGraph(str(tmp_path))
    old = time.time() - (200 * 86400)
    nid = mg.add_node("lesson", {"goal": "x", "outcome": "failure"})
    _set_node_meta(mg, nid, updated_at=old)
    gc = MemoryGarbageCollector(str(tmp_path))
    report = gc.scan(MemoryGCPolicy(dry_run=True))
    assert report.dry_run is True
    assert report.delete_candidate_count >= 1
    assert mg.get_node(nid) is not None


def test_apply_without_confirmation_is_blocked(tmp_path: Path) -> None:
    mg = MemoryGraph(str(tmp_path))
    old = time.time() - (200 * 86400)
    nid = mg.add_node("lesson", {"goal": "x", "outcome": "failure"})
    _set_node_meta(mg, nid, updated_at=old)
    gc = MemoryGarbageCollector(str(tmp_path))
    report = gc.scan(MemoryGCPolicy(dry_run=False))
    result = gc.apply(report, confirmation_token="nope")
    assert result.applied is False
    assert "confirmation_required" in result.warnings
    assert mg.get_node(nid) is not None


def test_recent_and_high_importance_are_protected(tmp_path: Path) -> None:
    mg = MemoryGraph(str(tmp_path))
    recent = mg.add_node("lesson", {"goal": "recent"})
    high = mg.add_node("lesson", {"goal": "high"})
    _set_node_meta(mg, recent, updated_at=time.time() - 3600, confidence=0.1, success_rate=0.1)
    _set_node_meta(mg, high, updated_at=time.time() - (200 * 86400), confidence=0.95, success_rate=0.95)
    report = MemoryGarbageCollector(str(tmp_path)).scan(MemoryGCPolicy(dry_run=True))
    ids = {c.id for c in report.candidates}
    assert recent not in ids
    assert high not in ids


def test_stale_contradiction_duplicate_candidates(tmp_path: Path) -> None:
    mg = MemoryGraph(str(tmp_path))
    old = time.time() - (240 * 86400)
    n1 = mg.add_node("lesson", {"goal": "g1", "outcome": "failure", "advice": "same"})
    n2 = mg.add_node("lesson", {"goal": "g1", "outcome": "failure", "advice": "same"})
    n3 = mg.add_node("lesson", {"goal": "g2"})
    _set_node_meta(mg, n1, updated_at=old, tags='["contradicted"]')
    _set_node_meta(mg, n2, updated_at=old, tags='["contradicted"]')
    _set_node_meta(mg, n3, updated_at=old, tags="[]")
    report = MemoryGarbageCollector(str(tmp_path)).scan(MemoryGCPolicy(dry_run=True))
    by_id = {c.id: c for c in report.candidates}
    assert n3 in by_id  # stale
    assert (n1 in by_id) or (n2 in by_id)  # contradiction
    dup_candidates = [c for c in report.candidates if c.duplicate_of]
    assert dup_candidates  # duplicate conservative candidate


def test_unknown_metadata_kept_and_corrupt_data_degraded(tmp_path: Path) -> None:
    mg = MemoryGraph(str(tmp_path))
    n1 = mg.add_node("lesson", {"goal": "normal"})
    with mg._lock:  # noqa: SLF001 - test helper only
        mg.conn.execute("UPDATE memory_nodes SET updated_at=? WHERE node_id=?", ("bad_ts", n1))
        mg.conn.execute(
            "INSERT INTO memory_nodes (node_id,node_type,content,confidence,success_rate,created_at,updated_at,tags) VALUES (?,?,?,?,?,?,?,?)",
            ("corrupt_json_node", "lesson", "{not json", 0.1, 0.1, time.time(), time.time() - (200 * 86400), "[]"),
        )
        mg.conn.commit()
    report = MemoryGarbageCollector(str(tmp_path)).scan(MemoryGCPolicy(dry_run=True))
    ids = {c.id for c in report.candidates}
    assert n1 not in ids
    assert any(w.startswith("corrupt_content:") for w in report.warnings)


def test_archive_failure_prevents_delete(tmp_path: Path, monkeypatch) -> None:
    mg = MemoryGraph(str(tmp_path))
    old = time.time() - (200 * 86400)
    nid = mg.add_node("lesson", {"goal": "x"})
    _set_node_meta(mg, nid, updated_at=old)
    gc = MemoryGarbageCollector(str(tmp_path))
    report = gc.scan(MemoryGCPolicy(dry_run=False, archive_before_delete=True))

    monkeypatch.setattr(gc, "_archive_candidates", lambda _c: False)
    result = gc.apply(report, confirmation_token="approved")
    assert result.applied is False
    assert "archive_failed_no_delete_performed" in result.warnings
    assert mg.get_node(nid) is not None


def test_apply_generates_audit_and_deletes_when_confirmed(tmp_path: Path) -> None:
    mg = MemoryGraph(str(tmp_path))
    old = time.time() - (200 * 86400)
    nid = mg.add_node("lesson", {"goal": "x"})
    _set_node_meta(mg, nid, updated_at=old)
    gc = MemoryGarbageCollector(str(tmp_path))
    report = gc.scan(MemoryGCPolicy(dry_run=False, archive_before_delete=True))
    result = gc.apply(report, confirmation_token="approved")
    assert result.audit_id.startswith("gc_apply_")
    assert result.archived >= 1
    assert mg.get_node(nid) is None
    audit_path = tmp_path / ".igris" / "memory" / "gc_audit.jsonl"
    assert audit_path.exists()


def test_apply_refuses_dry_run_report(tmp_path: Path) -> None:
    mg = MemoryGraph(str(tmp_path))
    old = time.time() - (200 * 86400)
    nid = mg.add_node("lesson", {"goal": "x"})
    _set_node_meta(mg, nid, updated_at=old)
    gc = MemoryGarbageCollector(str(tmp_path))
    report = gc.scan(MemoryGCPolicy(dry_run=True))
    result = gc.apply(report, confirmation_token="approved")
    assert result.applied is False
    assert "apply_blocked_dry_run_report" in result.warnings
    assert mg.get_node(nid) is not None


def test_missing_db_returns_degraded_report(tmp_path: Path) -> None:
    # Create collector without initializing MemoryGraph DB.
    gc = MemoryGarbageCollector(str(tmp_path))
    report = gc.scan(MemoryGCPolicy(dry_run=True))
    assert report.candidates == []
    assert "memory_db_missing" in report.warnings
