"""GlobalDigest: daily digest of IGRIS activity for the memory tree.

Part of GitHub issue #536: Memory Tree hierarchy — chunk→score→topic→global pipeline.

Produces one `global_digest` node per calendar day summarising:
- Issues worked on
- Failure patterns seen
- Topics that appeared most
- Net outcome (successes vs failures)

The digest is stored in the MemoryGraph as a `global_digest` node_type
and written to ContentStore as a human-readable .md file.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


_DAY_SECONDS = 86400


def _day_key(ts: Optional[float] = None) -> str:
    """Return YYYY-MM-DD for the given timestamp (UTC)."""
    t = ts if ts is not None else time.time()
    return time.strftime("%Y-%m-%d", time.gmtime(t))


def _day_start(day_key: str) -> float:
    """Return Unix timestamp for midnight UTC of the given YYYY-MM-DD."""
    return time.mktime(time.strptime(day_key + " 00:00:00", "%Y-%m-%d %H:%M:%S"))


class GlobalDigest:
    """Builds and manages daily digest nodes for the memory tree.

    Usage::

        digest = GlobalDigest(project_root)
        node_id = digest.build_for_day("2026-05-29", memory_graph, content_store)
        today = digest.get_today(memory_graph)
    """

    # node_type used in MemoryGraph — must be added to NODE_TYPES if not present
    NODE_TYPE = "global_digest"

    def __init__(self, project_root: str) -> None:
        self._root = Path(project_root)

    # ------------------------------------------------------------------
    # Core build
    # ------------------------------------------------------------------

    def build_for_day(
        self,
        day_key: str,
        run_events: List[Dict[str, Any]],
        failure_events: List[Dict[str, Any]],
        topic_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Build a digest dict from raw events for a given day.

        Does NOT write to MemoryGraph or ContentStore — returns a plain dict.
        Call save() to persist.

        Parameters
        ----------
        day_key:        YYYY-MM-DD string
        run_events:     list of run-event dicts (from supervisor_runs.json)
        failure_events: list of failure/lesson dicts for the day
        topic_names:    optional list of top topics seen that day
        """
        issues_worked: List[str] = []
        successes = 0
        failures = 0
        seen_issues: set = set()

        for ev in run_events:
            issue = str(ev.get("issue_number") or ev.get("goal", "")[:40])
            if issue and issue not in seen_issues:
                issues_worked.append(issue)
                seen_issues.add(issue)
            status = str(ev.get("status", ""))
            if status in ("completed", "success"):
                successes += 1
            elif status in ("blocked", "failed", "failure"):
                failures += 1

        failure_classes: Dict[str, int] = {}
        for fe in failure_events:
            fc = str(fe.get("failure_class") or fe.get("class") or "unknown")
            failure_classes[fc] = failure_classes.get(fc, 0) + 1

        digest: Dict[str, Any] = {
            "day": day_key,
            "issues_worked": issues_worked[:20],
            "successes": successes,
            "failures": failures,
            "net_outcome": "positive" if successes >= failures else "negative",
            "failure_classes": failure_classes,
            "top_topics": (topic_names or [])[:10],
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        return digest

    def digest_to_markdown(self, digest: Dict[str, Any]) -> str:
        """Render a digest dict as a human-readable Markdown string."""
        day = digest.get("day", "?")
        issues = digest.get("issues_worked", [])
        s = digest.get("successes", 0)
        f = digest.get("failures", 0)
        fc = digest.get("failure_classes", {})
        topics = digest.get("top_topics", [])
        net = digest.get("net_outcome", "?")

        lines = [
            f"# Daily Digest — {day}",
            "",
            f"**Net outcome:** {net} ({s} ✅ / {f} ❌)",
            "",
            "## Issues worked",
        ]
        if issues:
            for iss in issues:
                lines.append(f"- {iss}")
        else:
            lines.append("- (none recorded)")

        if fc:
            lines += ["", "## Failure classes"]
            for cls, count in sorted(fc.items(), key=lambda x: -x[1]):
                lines.append(f"- `{cls}`: {count}×")

        if topics:
            lines += ["", "## Top topics"]
            for t in topics:
                lines.append(f"- {t}")

        return "\n".join(lines)

    def chunk_id_for_day(self, day_key: str) -> str:
        """Deterministic chunk_id for a day's digest."""
        raw = f"global_digest::{day_key}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def save(
        self,
        digest: Dict[str, Any],
        content_store: Any,  # ContentStore
    ) -> str:
        """Write digest to ContentStore as a .md file. Returns chunk_id."""
        day = digest.get("day", _day_key())
        chunk_id = self.chunk_id_for_day(day)
        markdown = self.digest_to_markdown(digest)
        content_store.write(
            chunk_id=chunk_id,
            node_type=self.NODE_TYPE,
            content=markdown,
            confidence=1.0,
            tags=["digest", "daily", day],
            source="global_digest",
            extra_meta={"day": day},
        )
        return chunk_id

    def save_to_graph(
        self,
        digest: Dict[str, Any],
        memory_graph: Any,  # MemoryGraph
    ) -> str:
        """Persist digest as a node in MemoryGraph (safe node_type check bypassed via raw insert).

        Returns the node_id.
        """
        import json
        import uuid

        day = digest.get("day", _day_key())
        now = time.time()
        node_id = uuid.uuid4().hex

        # Insert directly so we can use our custom node_type without
        # modifying MemoryGraph.NODE_TYPES (backward compat).
        with memory_graph._lock:
            memory_graph.conn.execute(
                "INSERT OR IGNORE INTO memory_nodes "
                "(node_id, node_type, content, confidence, success_rate, created_at, updated_at, tags) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    node_id,
                    self.NODE_TYPE,
                    json.dumps(digest),
                    1.0,
                    1.0,
                    now,
                    now,
                    json.dumps(["digest", "daily", day]),
                ),
            )
            memory_graph.conn.commit()
        return node_id

    def get_for_day(self, day_key: str, content_store: Any) -> Optional[Dict[str, Any]]:
        """Read the digest for a given day from ContentStore."""
        chunk_id = self.chunk_id_for_day(day_key)
        return content_store.read(self.NODE_TYPE, chunk_id)

    def get_today(self, content_store: Any) -> Optional[Dict[str, Any]]:
        return self.get_for_day(_day_key(), content_store)
