"""
FastAPI application for IGRIS_GPT.

This module exposes a factory to create the FastAPI application and a helper
to run it with Uvicorn.  The application serves both the HTTP API used by
the web UI as well as the root HTML page rendered via Jinja2 templates.
"""

from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from igris.core import anti_loop
from igris.core.task_engine import TaskEngine
from igris.core.teacher import build_teacher_payload
from igris.layers.advisory import router as provider_router
from igris.layers.execution import runner as execution_runner
from igris.layers.execution.safe_commands import ALLOWED_COMMANDS
from igris.core import safety
from igris.layers.git_layer.git_status import get_git_info
from igris.models.config import CONFIG
from igris.models.report import GitStatusResponse, TestRunResponse
from igris.agents import build_default_registry
from igris.a2a.agent_card import build_agent_card
from igris.core.project_context import build_project_snapshot
from igris.core.memory import recent_memory_events, append_memory_event

# Determine paths relative to this file
MODULE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = MODULE_DIR / "templates"
STATIC_DIR = MODULE_DIR / "static"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="IGRIS_GPT", version="0.1.0")

    # Mount static files for CSS/JS
    if STATIC_DIR.exists():
        app.mount(
            "/static",
            StaticFiles(directory=str(STATIC_DIR)),
            name="static",
        )

    # Set up Jinja environment manually; FastAPI includes a Templates helper but
    # this manual setup avoids the dependency on starlette.templating during tests.
    jinja_env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )

    # In‑memory session storage
    sessions: Dict[str, List[Dict[str, str]]] = {}
    task_engine = TaskEngine()

    # Build default agents into the registry for A2A/card exposure
    build_default_registry()

    # Concurrency locks for test and terminal execution
    nonlocal_test_running = {"running": False}  # use dict to allow mutation in closure
    nonlocal_cmd_running = {"running": False}

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        """Serve the main UI page."""
        template = jinja_env.get_template("index.html")
        return template.render()

    @app.get("/api/status")
    async def api_status() -> Dict[str, object]:
        provider, model = provider_router.choose_provider()
        return {
            "provider": provider,
            "model": model,
            "safe": True,
        }

    @app.get("/api/config/safe")
    async def api_config_safe() -> Dict[str, object]:
        return CONFIG.safe_dict()

    @app.post("/api/sessions")
    async def create_session() -> Dict[str, str]:
        session_id = str(len(sessions) + 1)
        sessions[session_id] = []
        return {"id": session_id}

    @app.post("/api/sessions/{session_id}/messages")
    async def post_message(session_id: str, content: Dict[str, str] = Body(...)) -> Dict[str, str]:
        if session_id not in sessions:
            raise HTTPException(status_code=404, detail="Session not found")
        message = content.get("message", "")
        sessions[session_id].append({"role": "user", "content": message})
        # Choose provider (for now always local) and produce a placeholder response
        provider_router.choose_provider(for_task="chat")
        response_text = "This is a placeholder response."
        sessions[session_id].append({"role": "assistant", "content": response_text})
        return {"response": response_text}

    @app.get("/api/git/status", response_model=GitStatusResponse)
    async def api_git_status() -> GitStatusResponse:
        info = get_git_info()
        return GitStatusResponse(
            branch=info.branch,
            remote=info.remote,
            dirty=info.dirty,
            changed=info.changed,
            head=info.head,
        )

    def _redact(text: str) -> str:
        """Apply centralized secret redaction.

        This helper wraps ``igris.core.safety.redact_secrets`` for use
        within the web server.  It ensures that even if None is
        passed, a string is returned.
        """
        return safety.redact_secrets(text)

    @app.get("/api/routing/history")
    async def api_routing_history() -> Dict[str, object]:
        """Return the history of model provider decisions."""
        history = provider_router.get_history()
        return {"history": history}

    @app.get("/api/cost/summary")
    async def api_cost_summary() -> Dict[str, object]:
        """Return a summary of provider usage counts."""
        summary = provider_router.cost_summary()
        return summary

    @app.get("/api/files/tree")
    async def api_files_tree() -> Dict[str, object]:
        root = CONFIG.project_root
        tree = []
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root)
            # Filter out directories that are runtime artifacts or hidden
            filtered_dirs: List[str] = []
            for d in list(dirnames):
                sub_path = Path(dirpath) / d
                if safety.is_runtime_artifact(sub_path):
                    dirnames.remove(d)
                    continue
                if d.startswith('.'):
                    dirnames.remove(d)
                    continue
                filtered_dirs.append(d)
            entries = []
            for d in sorted(filtered_dirs):
                entries.append({"type": "dir", "name": d})
            # Filter out sensitive or runtime files
            for f in sorted(filenames):
                if f.startswith('.'):
                    continue
                if safety.is_sensitive_filename(f):
                    continue
                sub = Path(dirpath) / f
                if safety.is_runtime_artifact(sub):
                    continue
                entries.append({"type": "file", "name": f})
            tree.append({"path": rel_dir, "entries": entries})
        return {"tree": tree}

    @app.get("/api/files/preview")
    async def api_files_preview(path: str) -> Dict[str, object]:
        root = CONFIG.project_root
        # Normalize and validate path
        requested = (root / path).resolve()
        if not safety.check_path_access(requested, root):
            raise HTTPException(status_code=403, detail="Invalid path")
        if requested.is_dir():
            raise HTTPException(status_code=400, detail="Cannot preview a directory")
        if not requested.exists():
            raise HTTPException(status_code=404, detail="File not found")
        # Reject sensitive filenames
        if safety.is_sensitive_filename(requested.name) or safety.is_runtime_artifact(requested):
            raise HTTPException(status_code=403, detail="Preview of this file is not allowed")
        # Reject binary files based on mimetype
        mime, _ = mimetypes.guess_type(str(requested))
        if mime and not mime.startswith("text"):
            raise HTTPException(status_code=400, detail="Only text files can be previewed")
        try:
            with requested.open("r", encoding="utf-8", errors="replace") as f:
                content = f.read(20_000)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        # If secret-like patterns exist, redact them
        if safety.detect_secret_like_content(content):
            content = safety.redact_secrets(content)
        return {"path": path, "preview": content}

    @app.post("/api/tests/run", response_model=TestRunResponse)
    async def api_tests_run() -> TestRunResponse:
        # Ensure only one test run at a time
        if nonlocal_test_running["running"]:
            raise HTTPException(status_code=409, detail="Test run already in progress")
        nonlocal_test_running["running"] = True
        try:
            result = execution_runner.run_tests()
            success = result["returncode"] == 0
            # Redact secrets from output
            stdout = _redact(result.get("stdout", ""))
            stderr = _redact(result.get("stderr", ""))
            return TestRunResponse(success=success, stdout=stdout, stderr=stderr)
        finally:
            nonlocal_test_running["running"] = False

    @app.get("/api/logs")
    async def api_logs(lines: int = 200) -> Dict[str, str]:
        log_path = Path("logs/igris.log")
        if not log_path.exists():
            return {"logs": "Log file not found."}
        with log_path.open("r", encoding="utf-8", errors="replace") as f:
            data = f.readlines()[-lines:]
        return {"logs": "".join(data)}

    @app.get("/api/agent/timeline")
    async def api_agent_timeline() -> Dict[str, object]:
        # Placeholder timeline; this would normally include plan/action/observation events
        return {"timeline": []}

    @app.get("/api/safety/status")
    async def api_safety_status() -> Dict[str, object]:
        # Compute saturated families from the recent tasks
        tasks = [t.description for t in task_engine.tasks]
        counts = anti_loop.compute_family_counts(tasks)
        saturated = anti_loop.saturated_families(counts)
        return {
            "saturated_families": saturated,
            "counts": counts,
        }

    @app.get("/api/routing/explain")
    async def api_routing_explain() -> Dict[str, str]:
        explanation = provider_router.explain_routing()
        return {"explanation": explanation}

    @app.get("/api/health")
    async def api_health() -> Dict[str, object]:
        """Simple health endpoint to indicate the service is up."""
        import time

        return {"status": "ok", "version": app.version, "time": time.time()}

    @app.get("/api/readiness")
    async def api_readiness() -> Dict[str, object]:
        """Readiness check to verify that dependencies and configuration are valid."""
        checks: Dict[str, object] = {}
        # Check project_root
        root = CONFIG.project_root
        checks["project_root_exists"] = root.exists()
        checks["project_root_is_dir"] = root.is_dir()
        # Check that templates and static directories exist
        checks["templates"] = TEMPLATES_DIR.exists()
        checks["static"] = STATIC_DIR.exists()
        # Check registry has agents
        from igris.agents import list_agents

        checks["agents_registered"] = len(list_agents()) > 0
        return checks

    @app.get("/api/project/context")
    async def api_project_context() -> Dict[str, object]:
        """Return a snapshot of the current project context."""
        # Use the global task_engine (with in-memory tasks) when building snapshot
        snapshot = build_project_snapshot(task_engine=task_engine)
        return snapshot

    @app.get("/api/memory/recent")
    async def api_memory_recent(namespace: str, limit: int = 20) -> Dict[str, object]:
        """Return recent events from the given memory namespace."""
        events = recent_memory_events(namespace, limit)
        return {"events": events}

    # Task management endpoints

    @app.get("/api/tasks")
    async def api_list_tasks() -> Dict[str, object]:
        """Return a list of all tasks with minimal fields."""
        tasks = []
        for t in task_engine.tasks:
            tasks.append({"id": t.id, "description": t.description, "status": t.status.value, "result": t.result})
        return {"tasks": tasks}

    @app.post("/api/tasks")
    async def api_create_task(content: Dict[str, str] = Body(...)) -> Dict[str, object]:
        """Create a new task from a description."""
        description = content.get("description")
        if not description:
            raise HTTPException(status_code=400, detail="description is required")
        task = task_engine.add_task(description)
        # Record event in memory (optional)
        append_memory_event("tasks", {"event": "created", "id": task.id, "description": task.description})
        return {"id": task.id, "description": task.description, "status": task.status.value}

    @app.get("/api/tasks/{task_id}")
    async def api_get_task(task_id: int) -> Dict[str, object]:
        """Return details of a single task."""
        task = task_engine.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"id": task.id, "description": task.description, "status": task.status.value, "result": task.result}

    @app.post("/api/tasks/{task_id}/complete")
    async def api_complete_task(task_id: int, body: Dict[str, str] = Body(default={})):  # type: ignore
        """Mark a task as completed."""
        result_text = body.get("result") if isinstance(body, dict) else None
        task = task_engine.complete_task(task_id, result_text)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        append_memory_event("tasks", {"event": "completed", "id": task.id, "result": task.result})
        return {"id": task.id, "status": task.status.value, "result": task.result}

    @app.post("/api/tasks/{task_id}/block")
    async def api_block_task(task_id: int, body: Dict[str, str] = Body(default={})):  # type: ignore
        """Mark a task as blocked with a reason."""
        reason = body.get("reason") if isinstance(body, dict) else None
        task = task_engine.block_task(task_id, reason)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        append_memory_event("tasks", {"event": "blocked", "id": task.id, "reason": task.result})
        return {"id": task.id, "status": task.status.value, "result": task.result}

    # A2A task lifecycle endpoints (simplified MVP)

    @app.post("/api/a2a/tasks")
    async def a2a_create_task(task: Dict[str, object] = Body(...)) -> Dict[str, object]:
        """Create a new task via the A2A protocol.

        This endpoint accepts a minimal A2A task payload containing at least
        a title or description.  Additional A2A fields are ignored for now.
        """
        description = None
        # Accept title or description keys
        if isinstance(task, dict):
            description = task.get("description") or task.get("title")
        if not description:
            raise HTTPException(status_code=400, detail="description or title is required")
        created = task_engine.add_task(str(description))
        append_memory_event("tasks", {"event": "a2a_created", "id": created.id, "description": created.description})
        return {"id": created.id, "status": created.status.value}

    @app.get("/api/a2a/tasks/{task_id}")
    async def a2a_get_task(task_id: int) -> Dict[str, object]:
        """Return the status of an A2A task (identical to internal tasks)."""
        t = task_engine.get_task(task_id)
        if not t:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"id": t.id, "description": t.description, "status": t.status.value, "result": t.result}

    @app.post("/api/a2a/tasks/{task_id}/messages")
    async def a2a_append_message(task_id: int, message: Dict[str, object] = Body(...)) -> Dict[str, object]:
        """Append a message to a task's conversation timeline (placeholder).

        Stores messages in the memory namespace "a2a_messages" keyed by task id.
        """
        t = task_engine.get_task(task_id)
        if not t:
            raise HTTPException(status_code=404, detail="Task not found")
        if not isinstance(message, dict):
            raise HTTPException(status_code=400, detail="Invalid message format")
        entry = {
            "task_id": task_id,
            "sender": message.get("sender", "unknown"),
            "content": message.get("content", ""),
        }
        append_memory_event(f"a2a_messages_{task_id}", entry)
        return {"status": "ok"}

    @app.get("/.well-known/agent-card.json")
    @app.get("/.well-known/agent.json")
    async def well_known_agent(request: Request) -> JSONResponse:
        """Serve the agent card in a well-known location for A2A discovery."""
        # Determine base URL from request if possible
        base_url = str(request.base_url).rstrip("/")
        card = build_agent_card(base_url)
        # Convert dataclass to dict for JSON serialization
        from dataclasses import asdict

        return JSONResponse(content=asdict(card))

    @app.get("/api/terminal/commands")
    async def api_terminal_commands() -> Dict[str, object]:
        """Return the list of allowed safe command identifiers."""
        return {"commands": list(ALLOWED_COMMANDS.keys())}

    @app.post("/api/terminal/run")
    async def api_terminal_run(command: Dict[str, str] = Body(...)) -> Dict[str, object]:
        """Execute a safe command by its identifier."""
        cmd_id = command.get("command_id")
        if not cmd_id:
            raise HTTPException(status_code=400, detail="command_id is required")
        # Check command against centralized safety helper
        if not safety.check_command_allowed(cmd_id):
            raise HTTPException(status_code=403, detail="Command not allowed")
        # Prevent concurrent executions
        if nonlocal_cmd_running["running"]:
            raise HTTPException(status_code=409, detail="A command is already running")
        nonlocal_cmd_running["running"] = True
        try:
            result = execution_runner.run_safe_command(cmd_id)
            stdout = _redact(result.get("stdout", ""))
            stderr = _redact(result.get("stderr", ""))
            return {"command_id": cmd_id, "stdout": stdout, "stderr": stderr, "returncode": result.get("returncode")}
        finally:
            nonlocal_cmd_running["running"] = False

    return app


def run_app(app: FastAPI, host: str = "0.0.0.0", port: int = 7778) -> None:
    """Run the FastAPI application using Uvicorn."""
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")