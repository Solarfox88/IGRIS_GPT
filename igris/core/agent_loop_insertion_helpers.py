"""Insertion helper functions extracted from AgentReasoningLoop (#1395).

These static methods support insert_after/insert_before/replace_range operations
and were extracted to reduce the size of agent_reasoning_loop.py.
They accept plain parameters (no `self`) so they can be used as module-level
functions while the original class retains thin delegation wrappers.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Destructive write guard constants (extracted from AgentReasoningLoop #1395)
_SOURCE_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".html", ".css", ".scss", ".sass",
    ".md", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".sh",
    ".go", ".rs", ".java", ".cpp", ".c", ".h",
    ".rb", ".php", ".swift", ".kt",
})
_DESTRUCTIVE_RATIO_THRESHOLD = 0.3   # new < 30% of old → suspicious
_DESTRUCTIVE_MIN_EXISTING_CHARS = 200  # only guard files > 200 chars


def is_destructive_write(
    file_path: str,
    existing_content: str,
    new_content: str,
) -> Optional[str]:
    """Return an error message if this write would be destructively small.

    A write is considered destructive when:
    - The file already exists with substantial content (>200 chars)
    - The new content is much smaller (< 30 % of existing size)
    - The file has a source-code extension

    Returns None if the write is safe.
    """
    import os as _os
    ext = _os.path.splitext(file_path)[1].lower()
    if ext not in _SOURCE_EXTENSIONS:
        return None  # Unknown extension — not guarded

    existing_size = len(existing_content)
    new_size = len(new_content)

    if existing_size < _DESTRUCTIVE_MIN_EXISTING_CHARS:
        return None  # Small file — replacing is safe

    ratio = new_size / existing_size if existing_size > 0 else 1.0
    if ratio >= _DESTRUCTIVE_RATIO_THRESHOLD:
        return None  # New content is large enough — safe

    return (
        f"Destructive write guard: '{file_path}' has {existing_size} chars "
        f"but new content is only {new_size} chars "
        f"({ratio:.0%} of original). "
        f"This looks like a snippet replacing a full file. "
        f"Use insert_after / insert_before / replace_range / append_file "
        f"for targeted edits, or write_file only when providing the "
        f"complete replacement file content."
    )


def insertion_already_near_anchor(
    file_lines: List[str],
    anchor_idx: int,
    insertion: str,
    *,
    after: bool,
) -> bool:
    wanted = insertion.strip()
    if not wanted:
        return False
    insertion_line_count = max(1, len(insertion.splitlines()))
    window_size = insertion_line_count + 4
    if after:
        window = "".join(file_lines[anchor_idx + 1 : anchor_idx + 1 + window_size])
    else:
        start = max(0, anchor_idx - window_size)
        window = "".join(file_lines[start:anchor_idx])
    return wanted in window.strip()


def inserts_app_route_before_app_init(
    file_lines: List[str],
    anchor_idx: int,
    insertion: str,
    *,
    after: bool,
) -> bool:
    if "@app." not in insertion:
        return False
    insertion_point_end = anchor_idx + 1 if after else anchor_idx
    prior_text = "".join(file_lines[:insertion_point_end])
    return "app = FastAPI" not in prior_text


def inserts_app_route_after_block_header(anchor_line: str, insertion: str) -> bool:
    if "@app." not in insertion:
        return False
    stripped = anchor_line.strip()
    return stripped.endswith(":") and not stripped.startswith("@")


def normalize_app_route_insertion_indent(anchor_line: str, insertion: str) -> str:
    if "@app." not in insertion or "app = FastAPI(" not in anchor_line:
        return insertion
    anchor_indent = anchor_line[: len(anchor_line) - len(anchor_line.lstrip())]
    if not anchor_indent:
        return insertion
    lines = insertion.splitlines()
    leading_blank = bool(lines and not lines[0].strip())
    content_lines = lines[1:] if leading_blank else lines
    nonblank = [line for line in content_lines if line.strip()]
    if not nonblank:
        return insertion
    first_nonblank_index = next(i for i, line in enumerate(content_lines) if line.strip())
    body_nonblank = [line for line in content_lines[first_nonblank_index + 1 :] if line.strip()]
    body_base_indent = min((len(line) - len(line.lstrip(" ")) for line in body_nonblank), default=0)
    normalized = []
    for i, line in enumerate(content_lines):
        if not line.strip():
            normalized.append(line)
            continue
        if i == first_nonblank_index:
            stripped = line.lstrip(" ")
        else:
            stripped = line[body_base_indent:] if len(line) >= body_base_indent else line.lstrip(" ")
        normalized.append(anchor_indent + stripped)
    if leading_blank:
        normalized.insert(0, "")
    return "\n".join(normalized) + ("\n" if insertion.endswith("\n") else "")


def inserts_app_route_after_decorator_line(anchor_line: str, insertion: str) -> bool:
    return "@app." in insertion and anchor_line.strip().startswith("@")


def app_routes_in_content(content: str) -> set[tuple[str, str]]:
    import re

    return {
        (match.group(1), match.group(2))
        for match in re.finditer(r"@app\.(\w+)\(\s*['\"]([^'\"]+)['\"]", content)
    }


def app_route_already_exists(
    file_lines: List[str],
    insertion: str,
    *,
    exclude_start: Optional[int] = None,
    exclude_end: Optional[int] = None,
) -> bool:
    inserted_routes = app_routes_in_content(insertion)
    if not inserted_routes:
        return False
    if exclude_start is not None and exclude_end is not None:
        existing_text = "".join(file_lines[:exclude_start] + file_lines[exclude_end:])
    else:
        existing_text = "".join(file_lines)
    existing_routes = app_routes_in_content(existing_text)
    return bool(inserted_routes & existing_routes)


def duplicate_app_route_error(action_type: str) -> str:
    return (
        f"{action_type}: FastAPI route already present; do not retry this edit. "
        "Proceed to tests/report or use replace_range only if the existing route "
        "body needs a targeted update."
    )


def looks_like_complete_python_module(content: str) -> bool:
    """Heuristic for full-module Python content accidentally used as an append."""
    stripped = content.lstrip()
    if not (stripped.startswith("import ") or stripped.startswith("from ")):
        return False
    probe = "\n" + stripped
    module_body_markers = (
        "\ndef ",
        "\nasync def ",
        "\nclass ",
        "\n@pytest.fixture",
        "\napp = ",
        "\nclient = ",
    )
    return any(marker in probe for marker in module_body_markers)
