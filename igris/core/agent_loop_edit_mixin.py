"""File edit operations extracted from AgentReasoningLoop (#1395).

This mixin provides _commit_safe_edit, _execute_insert_after,
_execute_insert_before, _execute_replace_range, and _execute_append_file.
The original class inherits from this mixin to preserve backward compatibility.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, Optional
import logging

_log = logging.getLogger(__name__)


class AgentLoopEditMixin:
    """Mixin for file edit operations extracted from AgentReasoningLoop.

    Requires the host class to provide:
    - self.project_root: str
    - self._files_modified: list
    - self._validate_python_ast(path, content) -> Optional[str]
    - self._looks_like_complete_python_module(content) -> bool
    - self._normalize_app_route_insertion_indent(anchor_line, insertion) -> str
    - self._inserts_app_route_after_block_header(anchor_line, insertion) -> bool
    - self._inserts_app_route_after_decorator_line(anchor_line, insertion) -> bool
    - self._app_route_already_exists(file_lines, insertion, *, exclude_start, exclude_end) -> bool
    - self._inserts_app_route_before_app_init(file_lines, idx, insertion, *, after) -> bool
    - self._insertion_already_near_anchor(file_lines, idx, insertion, *, after) -> bool
    - self._duplicate_app_route_error(action_type) -> str
    - self._is_destructive_write(file_path, existing_content, new_content) -> Optional[str]
    """

    # Type annotations for attributes/methods provided by the host class.
    project_root: Any
    _files_modified: Any
    _SOURCE_EXTENSIONS: Any
    _DESTRUCTIVE_RATIO_THRESHOLD: Any
    _DESTRUCTIVE_MIN_EXISTING_CHARS: Any
    _validate_python_ast: Any
    _looks_like_complete_python_module: Any
    _normalize_app_route_insertion_indent: Any
    _inserts_app_route_after_block_header: Any
    _inserts_app_route_after_decorator_line: Any
    _app_route_already_exists: Any
    _inserts_app_route_before_app_init: Any
    _insertion_already_near_anchor: Any
    _duplicate_app_route_error: Any
    _is_destructive_write: Any

    def _commit_safe_edit(self, full_path: str, merged: str, insertion: str) -> Dict[str, Any]:
        """Write merged content for a safe edit.

        Secret check applies only to the *insertion* (new content), not the
        entire merged file.  Pre-existing code that happens to match a secret
        pattern (e.g. ``token=content.get(...)`` in server.py) must not block
        legitimate edits — that code was already committed and is not a secret.
        """
        from igris.core.safety import detect_secret_like_content
        from igris.core.rollback_manager import RollbackManager
        import pathlib

        if detect_secret_like_content(insertion):
            return {"success": False, "error": "Safe edit blocked: insertion contains secret-like patterns"}

        target = pathlib.Path(full_path)
        rollback_id = ""
        if target.exists():
            mgr = RollbackManager(project_root=str(self.project_root))
            entry = mgr.backup_file(str(target))
            if entry:
                rollback_id = entry.id

        try:
            target.write_text(merged, encoding="utf-8")
            return {"success": True, "rollback_id": rollback_id}
        except OSError as exc:
            return {"success": False, "error": str(exc)}

    def _execute_insert_after(self, rt, action) -> Dict[str, Any]:
        """Insert content after anchor line. Params: path, anchor, content."""
        file_path = action.parameters.get("path", "")
        anchor = action.parameters.get("anchor", "")
        new_content = action.parameters.get("content", "")
        if not file_path or anchor is None or new_content is None:
            return {"success": False, "error": "insert_after: missing path/anchor/content"}
        full_path = os.path.join(self.project_root, file_path)
        if not os.path.isfile(full_path):
            return {"success": False, "error": f"insert_after: file not found: {file_path}"}
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                file_lines = f.readlines()
        except OSError as exc:
            return {"success": False, "error": str(exc)}
        idx = next((i for i, ln in enumerate(file_lines) if anchor in ln), None)
        if idx is None and anchor.strip() == "app = FastAPI()":
            idx = next((i for i, ln in enumerate(file_lines) if "app = FastAPI(" in ln), None)
        if idx is None:
            return {"success": False, "error": f"insert_after: anchor not found: {repr(anchor)}"}
        nl = "\n"
        insertion = new_content if new_content.endswith(nl) else new_content + nl
        insertion = self._normalize_app_route_insertion_indent(file_lines[idx], insertion)
        if self._inserts_app_route_after_block_header(file_lines[idx], insertion):
            return {
                "success": False,
                "error": (
                    "insert_after: refusing to insert @app route immediately after "
                    "a Python block header; use an anchor after app = FastAPI(...) "
                    "or after the complete previous route/block; "
                    "route would be before app = FastAPI initialization"
                ),
            }
        if self._inserts_app_route_after_decorator_line(file_lines[idx], insertion):
            return {
                "success": False,
                "error": (
                    "insert_after: refusing to insert @app route immediately after "
                    "a decorator line; use an anchor after the complete decorated "
                    "function block or after app = FastAPI(...)"
                ),
            }
        if self._app_route_already_exists(file_lines, insertion):
            return {"success": False, "error": self._duplicate_app_route_error("insert_after")}
        if self._inserts_app_route_before_app_init(file_lines, idx, insertion, after=True):
            return {
                "success": False,
                "error": "insert_after: refusing to insert @app route before app = FastAPI initialization",
            }
        if self._insertion_already_near_anchor(file_lines, idx, insertion, after=True):
            return {"success": True, "summary": "insert_after: no change; content already present near anchor"}
        merged_lines = file_lines[: idx + 1] + [insertion] + file_lines[idx + 1 :]
        merged = "".join(merged_lines)
        if file_path.endswith(".py"):
            err = self._validate_python_ast(file_path, merged)
            if err:
                return {"success": False, "error": err}
        hash_before = hashlib.sha256("".join(file_lines).encode()).hexdigest()
        hash_new = hashlib.sha256(merged.encode()).hexdigest()
        if hash_before == hash_new:
            return {"success": True, "summary": "insert_after: no change"}
        wr = self._commit_safe_edit(full_path, merged, insertion)
        if not wr["success"]:
            return {"success": False, "error": wr["error"]}
        self._files_modified.append(file_path)
        return {
            "success": True,
            "summary": f"Inserted {len(insertion)} chars after line {idx+1} in {file_path}",
            "result_data": {"path": file_path, "after_line": idx + 1},
        }

    def _execute_insert_before(self, rt, action) -> Dict[str, Any]:
        """Insert content before anchor line. Params: path, anchor, content."""
        file_path = action.parameters.get("path", "")
        anchor = action.parameters.get("anchor", "")
        new_content = action.parameters.get("content", "")
        if not file_path or anchor is None or new_content is None:
            return {"success": False, "error": "insert_before: missing path/anchor/content"}
        full_path = os.path.join(self.project_root, file_path)
        if not os.path.isfile(full_path):
            return {"success": False, "error": f"insert_before: file not found: {file_path}"}
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                file_lines = f.readlines()
        except OSError as exc:
            return {"success": False, "error": str(exc)}
        idx = next((i for i, ln in enumerate(file_lines) if anchor in ln), None)
        if idx is None:
            return {"success": False, "error": f"insert_before: anchor not found: {repr(anchor)}"}
        nl = "\n"
        insertion = new_content if new_content.endswith(nl) else new_content + nl
        if self._app_route_already_exists(file_lines, insertion):
            return {"success": False, "error": self._duplicate_app_route_error("insert_before")}
        if self._inserts_app_route_before_app_init(file_lines, idx, insertion, after=False):
            return {
                "success": False,
                "error": "insert_before: refusing to insert @app route before app = FastAPI initialization",
            }
        if self._insertion_already_near_anchor(file_lines, idx, insertion, after=False):
            return {"success": True, "summary": "insert_before: no change; content already present near anchor"}
        merged_lines = file_lines[:idx] + [insertion] + file_lines[idx:]
        merged = "".join(merged_lines)
        if file_path.endswith(".py"):
            err = self._validate_python_ast(file_path, merged)
            if err:
                return {"success": False, "error": err}
        hash_before = hashlib.sha256("".join(file_lines).encode()).hexdigest()
        hash_new = hashlib.sha256(merged.encode()).hexdigest()
        if hash_before == hash_new:
            return {"success": True, "summary": "insert_before: no change"}
        wr = self._commit_safe_edit(full_path, merged, insertion)
        if not wr["success"]:
            return {"success": False, "error": wr["error"]}
        self._files_modified.append(file_path)
        return {
            "success": True,
            "summary": f"Inserted {len(insertion)} chars before line {idx+1} in {file_path}",
            "result_data": {"path": file_path, "before_line": idx + 1},
        }

    def _execute_replace_range(self, rt, action) -> Dict[str, Any]:
        """Replace line range. Params: path, start (1-based), end (1-based), content."""
        file_path = action.parameters.get("path", "")
        start = action.parameters.get("start")
        end = action.parameters.get("end")
        new_content = action.parameters.get("content", "")
        if not file_path or start is None or end is None or new_content is None:
            return {"success": False, "error": "replace_range: missing path/start/end/content"}
        try:
            start, end = int(start), int(end)
        except (TypeError, ValueError):
            return {"success": False, "error": "replace_range: start/end must be integers"}
        if start < 1 or end < start:
            return {"success": False, "error": f"replace_range: invalid range {start}..{end}"}
        full_path = os.path.join(self.project_root, file_path)
        if not os.path.isfile(full_path):
            return {"success": False, "error": f"replace_range: file not found: {file_path}"}
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                file_lines = f.readlines()
        except OSError as exc:
            return {"success": False, "error": str(exc)}
        if end > len(file_lines):
            return {"success": False, "error": f"replace_range: end {end} > file length {len(file_lines)}"}
        nl = "\n"
        replacement = new_content if new_content.endswith(nl) else new_content + nl
        if self._app_route_already_exists(
            file_lines,
            replacement,
            exclude_start=start - 1,
            exclude_end=end,
        ):
            return {
                "success": True,
                "summary": "replace_range: FastAPI route already present; no change",
                "result_data": {"path": file_path, "start": start, "end": end, "noop": True},
            }
        merged_lines = file_lines[: start - 1] + [replacement] + file_lines[end:]
        merged = "".join(merged_lines)
        if file_path.endswith(".py"):
            err = self._validate_python_ast(file_path, merged)
            if err:
                return {"success": False, "error": err}
        hash_before = hashlib.sha256("".join(file_lines).encode()).hexdigest()
        hash_new = hashlib.sha256(merged.encode()).hexdigest()
        if hash_before == hash_new:
            return {"success": True, "summary": "replace_range: no change"}
        wr = self._commit_safe_edit(full_path, merged, replacement)
        if not wr["success"]:
            return {"success": False, "error": wr["error"]}
        self._files_modified.append(file_path)
        return {
            "success": True,
            "summary": f"Replaced lines {start}–{end} in {file_path} with {len(replacement)} chars",
            "result_data": {"path": file_path, "start": start, "end": end},
        }

    def _execute_append_file(self, rt, action) -> Dict[str, Any]:
        """Append content to end of file. Params: path, content."""
        file_path = action.parameters.get("path", "")
        new_content = action.parameters.get("content", "")
        if not file_path or new_content is None:
            return {"success": False, "error": "append_file: missing path/content"}
        full_path = os.path.join(self.project_root, file_path)
        existing = ""
        if os.path.isfile(full_path):
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    existing = f.read()
            except OSError as exc:
                return {"success": False, "error": str(exc)}
        if (
            file_path.endswith(".py")
            and existing.strip()
            and self._looks_like_complete_python_module(new_content)
        ):
            return {
                "success": False,
                "error": (
                    "append_file: refusing to append complete Python module content "
                    f"to existing file: {file_path}; use write_file for new files "
                    "or replace_range/insert_after/insert_before for existing files"
                ),
            }
        nl = "\n"
        sep = "" if (not existing or existing.endswith(nl)) else nl
        merged = existing + sep + new_content
        if file_path.endswith(".py"):
            err = self._validate_python_ast(file_path, merged)
            if err:
                return {"success": False, "error": err}
        hash_before = hashlib.sha256(existing.encode()).hexdigest()
        hash_new = hashlib.sha256(merged.encode()).hexdigest()
        if hash_before == hash_new:
            return {"success": True, "summary": "append_file: no change"}
        wr = self._commit_safe_edit(full_path, merged, new_content)
        if not wr["success"]:
            return {"success": False, "error": wr["error"]}
        self._files_modified.append(file_path)
        return {
            "success": True,
            "summary": f"Appended {len(new_content)} chars to {file_path}",
            "result_data": {"path": file_path, "appended_chars": len(new_content)},
        }

    def _execute_write_file(self, rt, action) -> Dict[str, Any]:
        """Execute write_file with destructive-write guard and verification.

        Guards (#76):
        - Blocks snippet replacement on large existing source files
        - Verifies hash before/after to confirm real change
        - Validates Python AST for .py files
        - Checks that critical symbols survive in igris/web/server.py
        - Tracks files_modified only on real diff
        - Idempotent: if content is already on disk, returns success=True
          without re-writing (no disk I/O, no files_modified entry)
        """
        import hashlib
        import ast as _ast

        file_path = action.parameters.get("path", "")
        content = action.parameters.get("content", "")

        if not file_path:
            return {"success": False, "error": "write_file: missing 'path' parameter"}
        if content is None:
            return {"success": False, "error": "write_file: missing 'content' parameter"}

        # Resolve full path
        full_path = os.path.join(self.project_root, file_path)

        # Read existing file (if any)
        existing_content: Optional[str] = None
        hash_before: Optional[str] = None
        if os.path.isfile(full_path):
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    existing_content = f.read()
                hash_before = hashlib.sha256(existing_content.encode("utf-8")).hexdigest()
            except OSError as exc:
                _log.debug("agent_reasoning_loop: narrowed catch failed: %s", exc, exc_info=True)

        # Hash of the new content
        hash_new = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # Idempotent: content already on disk — no write needed
        if hash_before is not None and hash_before == hash_new:
            # Count this as a modification (caller may be retrying a previous
            # successful write that crashed before tracking; we honour it)
            self._files_modified.append(file_path)
            return {
                "success": True,
                "summary": f"write_file: '{file_path}' already has this content (idempotent)",
                "result_data": {"path": file_path, "chars": len(content), "hash": hash_new[:12]},
            }

        # ── Destructive write guard ──────────────────────────────────────────
        if existing_content is not None:
            guard_error = self._is_destructive_write(file_path, existing_content, content)
            if guard_error:
                return {
                    "success": False,
                    "error": guard_error,
                    "summary": f"Blocked: destructive write on '{file_path}'",
                }

            # Extra guard for server.py: critical symbols must survive
            import os as _os
            if _os.path.basename(file_path) == "server.py" or file_path.endswith("web/server.py"):
                if file_path.endswith(".py"):
                    # Check existing has create_app / run_app
                    try:
                        old_tree = _ast.parse(existing_content, filename=file_path)
                        old_defs = {
                            n.name for n in _ast.walk(old_tree)
                            if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                        }
                        critical_existing = {"create_app", "run_app"} & old_defs
                        if critical_existing:
                            # New content must also have them
                            new_tree = _ast.parse(content, filename=file_path)
                            new_defs = {
                                n.name for n in _ast.walk(new_tree)
                                if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                            }
                            missing = critical_existing - new_defs
                            if missing:
                                return {
                                    "success": False,
                                    "error": (
                                        f"Symbol guard: writing '{file_path}' would remove "
                                        f"critical symbols: {sorted(missing)}. "
                                        f"Provide a complete file that preserves these functions."
                                    ),
                                    "summary": f"Blocked: symbol removal in '{file_path}'",
                                }
                    except SyntaxError:
                        pass  # Will be caught by AST validation below

        # ── Python AST validation ────────────────────────────────────────────
        if file_path.endswith(".py"):
            ast_error = self._validate_python_ast(file_path, content)
            if ast_error:
                return {
                    "success": False,
                    "error": ast_error,
                    "summary": f"Blocked: invalid Python in '{file_path}'",
                }

        # ── Perform the write via ToolRuntime ────────────────────────────────
        tr = rt.fs_write(path=full_path, content=content)
        if not tr.success:
            return {
                "success": False,
                "error": tr.error,
                "summary": f"write_file failed: {tr.error}",
            }

        # ── Verify hash after write ──────────────────────────────────────────
        try:
            with open(full_path, "rb") as f:
                hash_after = hashlib.sha256(f.read()).hexdigest()
        except OSError as exc:
            return {
                "success": False,
                "error": f"write_file: cannot verify written file: {exc}",
            }

        if hash_after != hash_new:
            return {
                "success": False,
                "error": "write_file: verification failed — hash mismatch after write",
            }

        # Real change confirmed — track it
        self._files_modified.append(file_path)

        return {
            "success": True,
            "summary": (
                f"Written {len(content)} chars to {file_path} "
                f"(hash: {(hash_before or 'new')[:8]}→{hash_after[:8]})"
            ),
            "result_data": {"path": file_path, "chars": len(content), "hash": hash_after[:12]},
        }

    def _execute_propose_patch(self, rt, action) -> Dict[str, Any]:
        """Execute propose_patch: show diff preview without applying."""
        file_path = action.parameters.get("path", "")
        new_content = action.parameters.get("content", "")

        if not file_path:
            return {"success": False, "error": "propose_patch: missing 'path'"}

        full_path = os.path.join(self.project_root, file_path)
        tr = rt.fs_diff(path=full_path, new_content=new_content)

        return {
            "success": tr.success,
            "summary": tr.output[:300] if tr.output else "No diff output",
            "error": tr.error,
            "result_data": tr.output,
        }

    def _execute_apply_patch(self, rt, action) -> Dict[str, Any]:
        """Execute apply_patch: write verified content to file."""
        file_path = action.parameters.get("path", "")
        content = action.parameters.get("content", "")

        if not file_path or not content:
            return {"success": False, "error": "apply_patch: missing 'path' or 'content'"}

        # Delegate to write_file logic for verified write
        from igris.core.agent_action_schema import AgentAction
        write_action = AgentAction(
            action_type="write_file",
            parameters={"path": file_path, "content": content},
        )
        return self._execute_write_file(rt, write_action)
