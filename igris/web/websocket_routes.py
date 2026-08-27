"""WebSocket chat streaming endpoint (#1323 Phase 2).

Provides /ws/chat for real-time chat streaming and /ws/loop for
reasoning loop step streaming.

Phase 1: basic WebSocket endpoint with auth integration.
Phase 2: structured word-by-word streaming (fallback simulation).
  The chat engine is synchronous, so we split the complete response
  into word chunks. Real token-by-token streaming requires
  orchestrator changes (Phase 3).

Usage:
    # Connect to /ws/chat with session token in query param or header
    ws://localhost:7778/ws/chat?token=<session_token>

    # Send a message
    {"type": "chat", "message": "Hello"}

    # Receive streaming responses
    {"type": "chunk", "content": "Hello"}
    {"type": "chunk", "content": "!"}
    {"type": "done", "message_id": "msg-123"}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

_log = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


def _validate_token(token: str) -> tuple[str, str]:
    """Validate session token and return (profile_id, trust_level).

    Returns ("anonymous", "untrusted") if token is invalid or missing.
    """
    if not token:
        return "anonymous", "untrusted"

    try:
        from igris.core.interlocutor_auth import AuthSessionManager
        sm = AuthSessionManager(project_root=os.environ.get("PROJECT_ROOT", "."))
        session, result = sm.resolve_session(token)
        if result.ok and session is not None:
            profile_id = session.profile_id or "anonymous"
            # Try to resolve trust level
            trust_level = "untrusted"
            try:
                from igris.core.identity_resolver import IdentityResolver
                ir = IdentityResolver(project_root=os.environ.get("PROJECT_ROOT", "."))
                profile = ir.resolve(profile_id)
                trust_level = str(getattr(profile, "trust_level", "untrusted")).lower()
            except (ImportError, AttributeError, TypeError, ValueError):
                pass
            return profile_id, trust_level
    except (ImportError, OSError, AttributeError, TypeError, ValueError) as exc:
        _log.debug("ws: token validation failed: %s", exc)

    return "anonymous", "untrusted"


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket) -> None:
    """WebSocket endpoint for chat streaming.

    Accepts JSON messages:
    - {"type": "chat", "message": "text"}
    - {"type": "ping"}

    Sends JSON responses:
    - {"type": "chunk", "content": "text"}
    - {"type": "done", "message_id": "id"}
    - {"type": "error", "message": "text"}
    - {"type": "pong"}
    """
    # Extract token from query param
    token = websocket.query_params.get("token", "")
    profile_id, trust_level = _validate_token(token)

    await websocket.accept()

    # Send connection established message
    await websocket.send_json({
        "type": "connected",
        "profile_id": profile_id,
        "trust_level": trust_level,
        "timestamp": time.time(),
    })

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON",
                })
                continue

            msg_type = msg.get("type", "")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "timestamp": time.time()})
                continue

            if msg_type == "chat":
                message = msg.get("message", "")
                if not message:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Empty message",
                    })
                    continue

                message_id = f"msg-{uuid.uuid4().hex[:8]}"

                # Phase 2: structured streaming
                # The chat engine is synchronous and returns a complete response.
                # We stream the response word-by-word to simulate token streaming.
                # Real token-by-token streaming requires orchestrator changes (Phase 3).
                try:
                    from igris.core.chat_engine import chat as chat_fn
                    response = chat_fn(message)

                    # Extract text from response dict
                    if isinstance(response, dict):
                        text = response.get("text", "")
                        provider = response.get("provider", "unknown")
                        model = response.get("model", "unknown")
                    else:
                        text = str(response)
                        provider = "unknown"
                        model = "unknown"

                    # Send metadata first
                    await websocket.send_json({
                        "type": "start",
                        "message_id": message_id,
                        "provider": provider,
                        "model": model,
                        "streaming_mode": "word_split",
                        "timestamp": time.time(),
                    })

                    # Stream word by word (fallback simulation)
                    # Each chunk is a word to simulate token streaming.
                    # Real token streaming will be added in Phase 3 when
                    # the orchestrator exposes a streaming generator.
                    words = text.split()
                    for i, word in enumerate(words):
                        await websocket.send_json({
                            "type": "chunk",
                            "content": word + (" " if i < len(words) - 1 else ""),
                            "message_id": message_id,
                            "chunk_index": i,
                        })
                        # Small delay to simulate streaming
                        await asyncio.sleep(0.02)

                    await websocket.send_json({
                        "type": "done",
                        "message_id": message_id,
                        "total_chunks": len(words),
                        "timestamp": time.time(),
                    })
                except Exception as exc:
                    _log.warning("ws: chat error: %s", exc, exc_info=True)
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Chat error: {exc}",
                        "message_id": message_id,
                    })
            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}",
                })

    except WebSocketDisconnect:
        _log.debug("ws: client disconnected")
    except Exception as exc:
        _log.warning("ws: unexpected error: %s", exc, exc_info=True)


@router.websocket("/ws/loop")
async def ws_loop(websocket: WebSocket) -> None:
    """WebSocket endpoint for reasoning loop step streaming.

    Accepts JSON messages:
    - {"type": "start", "goal": "text", "mission_id": "id"}
    - {"type": "stop"}

    Sends JSON responses:
    - {"type": "step", "step_num": 1, "action": "...", "result": "..."}
    - {"type": "finished", "status": "finished"}
    - {"type": "error", "message": "text"}
    """
    token = websocket.query_params.get("token", "")
    profile_id, trust_level = _validate_token(token)

    # Only admin/owner can start loops via WebSocket
    if trust_level not in ("admin", "owner"):
        await websocket.accept()
        await websocket.send_json({
            "type": "error",
            "message": "Insufficient permissions. Admin/owner required.",
        })
        await websocket.close(code=1008)
        return

    await websocket.accept()
    await websocket.send_json({
        "type": "connected",
        "profile_id": profile_id,
        "endpoint": "loop",
    })

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = msg.get("type", "")

            if msg_type == "start":
                goal = msg.get("goal", "")
                mission_id = msg.get("mission_id", f"ws-{uuid.uuid4().hex[:8]}")

                if not goal:
                    await websocket.send_json({"type": "error", "message": "Empty goal"})
                    continue

                # Phase 1: acknowledge start, actual loop integration in Phase 2
                await websocket.send_json({
                    "type": "started",
                    "mission_id": mission_id,
                    "goal": goal,
                })
                await websocket.send_json({
                    "type": "finished",
                    "status": "stopped",
                    "message": "Loop streaming not yet implemented (Phase 2)",
                })

            elif msg_type == "stop":
                await websocket.send_json({"type": "stopped"})
                break
            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}",
                })

    except WebSocketDisconnect:
        _log.debug("ws/loop: client disconnected")
    except Exception as exc:
        _log.warning("ws/loop: unexpected error: %s", exc, exc_info=True)
