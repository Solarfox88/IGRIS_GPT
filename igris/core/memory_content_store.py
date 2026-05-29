"""ContentStore: persists memory chunks as human-readable .md files.

Part of GitHub issue #536: Memory Tree hierarchy — chunk→score→topic→global pipeline.

Each chunk is written as a Markdown file with YAML frontmatter to
.igris/memory/{node_type}/{chunk_id}.md — readable, correctable, and
importable by IGRIS at next startup.

Atomic write: tmp file → rename, so a crash never leaves a corrupt file.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def _yaml_value(v: Any) -> str:
    """Simple scalar YAML serialiser (no dependency on pyyaml)."""
    if isinstance(v, str):
        # Quote strings that contain special chars
        if any(c in v for c in (':', '#', '[', ']', '{', '}', ',', '\n', '"', "'")):
            escaped = v.replace('"', '\\"')
            return f'"{escaped}"'
        return v
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        items = ", ".join(_yaml_value(i) for i in v)
        return f"[{items}]"
    if v is None:
        return "null"
    return str(v)


def _write_frontmatter(fields: Dict[str, Any]) -> str:
    lines = ["---"]
    for k, v in fields.items():
        lines.append(f"{k}: {_yaml_value(v)}")
    lines.append("---")
    return "\n".join(lines)


def _parse_frontmatter(text: str) -> tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter from a .md file. Returns (meta, body)."""
    meta: Dict[str, Any] = {}
    body = text
    if not text.startswith("---"):
        return meta, body
    end = text.find("\n---", 3)
    if end == -1:
        return meta, body
    fm_block = text[3:end].strip()
    body = text[end + 4:].strip()
    for line in fm_block.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        # Basic type coercion
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1]
            meta[k] = [i.strip().strip('"') for i in inner.split(",") if i.strip()] if inner.strip() else []
        elif v == "null":
            meta[k] = None
        else:
            try:
                meta[k] = float(v) if "." in v else int(v)
            except ValueError:
                meta[k] = v.strip('"')
    return meta, body


class ContentStore:
    """Writes and reads memory chunks as .md files with YAML frontmatter.

    Directory layout:
        <project_root>/.igris/memory/<node_type>/<chunk_id>.md
    """

    def __init__(self, project_root: str) -> None:
        self._root = Path(project_root) / ".igris" / "memory"

    def _chunk_path(self, node_type: str, chunk_id: str) -> Path:
        return self._root / node_type / f"{chunk_id}.md"

    def write(
        self,
        chunk_id: str,
        node_type: str,
        content: str,
        confidence: float = 1.0,
        tags: Optional[List[str]] = None,
        source: str = "",
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """Atomically write a chunk to disk. Returns the path written."""
        dest = self._chunk_path(node_type, chunk_id)
        dest.parent.mkdir(parents=True, exist_ok=True)

        meta: Dict[str, Any] = {
            "node_id": chunk_id,
            "node_type": node_type,
            "confidence": round(float(confidence), 4),
            "tags": tags or [],
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": source,
        }
        if extra_meta:
            meta.update(extra_meta)

        body = _write_frontmatter(meta) + "\n\n" + content

        # Atomic write: write to .tmp then rename
        tmp = dest.with_suffix(".tmp")
        try:
            tmp.write_text(body, encoding="utf-8")
            tmp.replace(dest)
        except Exception:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise

        return dest

    def read(self, node_type: str, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Read a chunk from disk. Returns None if not found."""
        path = self._chunk_path(node_type, chunk_id)
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        return {"chunk_id": chunk_id, "node_type": node_type, "content": body, **meta}

    def read_all(self, node_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Read all chunks from disk, optionally filtered by node_type.

        Useful for syncing human edits back into the memory graph.
        """
        results: List[Dict[str, Any]] = []
        search_root = self._root / node_type if node_type else self._root
        if not search_root.exists():
            return results
        pattern = "*.md"
        for md_file in sorted(search_root.rglob(pattern)):
            try:
                text = md_file.read_text(encoding="utf-8")
                meta, body = _parse_frontmatter(text)
                chunk_id = md_file.stem
                nt = md_file.parent.name
                results.append({"chunk_id": chunk_id, "node_type": nt, "content": body, **meta})
            except Exception:
                continue
        return results

    def delete(self, node_type: str, chunk_id: str) -> bool:
        """Delete a chunk file. Returns True if deleted."""
        path = self._chunk_path(node_type, chunk_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def exists(self, node_type: str, chunk_id: str) -> bool:
        return self._chunk_path(node_type, chunk_id).exists()

    def list_chunk_ids(self, node_type: str) -> List[str]:
        """List all chunk IDs for a given node_type."""
        d = self._root / node_type
        if not d.exists():
            return []
        return [f.stem for f in sorted(d.glob("*.md"))]
