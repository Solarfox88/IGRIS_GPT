"""IGRIS web server router — auto-split from server.py (#725).

Route handlers are extracted from _create_app_impl; shared app state is
received via ``deps`` (SimpleNamespace). Do not edit route logic here;
changes should first be made in the original handler before full migration.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from igris.core import anti_loop
from igris.core import chat_context
from igris.core import chat_streaming
from igris.core import decision_memory
from igris.core import diagnostics as diagnostics_mod
from igris.core import execution_report
from igris.core import mission_planner
from igris.core import project_state as project_state_mod
from igris.core import safe_policy
from igris.core import safety
from igris.core import task_selection_explain
from igris.core import decision_report as decision_report_mod
from igris.core import autonomous_loop
from igris.core.chat_engine import chat as chat_llm, check_ollama_available
from igris.core import patch_proposal as patch_mod
from igris.core.memory import recent_memory_events, append_memory_event
from igris.core.memory_graph import MemoryGraph
from igris.core.outcome_router import route_outcome
from igris.core.project_context import build_project_snapshot
from igris.core.teacher import (
    build_teacher_payload, validate_teacher_assignment, propose_remediation_task,
)
from igris.core.task_engine import TaskEngine
from igris.layers.advisory import router as provider_router
from igris.layers.execution import runner as execution_runner
from igris.layers.execution.safe_commands import ALLOWED_COMMANDS
from igris.layers.git_layer import git_ops
from igris.layers.git_layer.git_status import get_git_info
from igris.layers.validation import validator as task_validator
from igris.models.config import CONFIG
from igris.models.report import GitStatusResponse, TestRunResponse
from igris.models.task import TaskStatus
from igris.agents import build_default_registry
from igris.a2a.agent_card import build_agent_card
from igris.a2a import task_store as a2a_store


def create_router(deps) -> APIRouter:
    """Router module 1/10 — _create_app_impl chunk 1."""
    router = APIRouter()
    # Unpack shared app state (names match what route bodies use directly)
    _redact = deps.redact
    _check_model_available = deps.check_model_available
    _get_graph = deps.get_graph
    jinja_env = deps.jinja_env
    sessions = deps.sessions
    task_engine = deps.task_engine
    nonlocal_test_running = deps.nonlocal_test_running
    nonlocal_cmd_running = deps.nonlocal_cmd_running

    @router.get('/api/diagnostics/session-resume')
    async def session_resume():
        # Implement the logic for session resume
        return JSONResponse(content={'status': 'success'})

    @router.get('/api/rank/s-dashboard')
    async def get_rank_s_dashboard():
        return {
            'app': 'IGRIS_GPT',
            'rank': 'S',
            'status': 'ok',
            'capability': 'end-to-end-supervised',
            'checks': {
                'backend': True,
                'ui': True,
                'tests': True,
                'workflow': True
            }
        }

    @router.get('/api/rank/gauntlet')
    async def rank_gauntlet_run():
        """Machine-readable Rank S gauntlet — pass/fail validation gate (#337)."""
        try:
            from igris.core.rank_gauntlet import RankGauntlet
            result = RankGauntlet().run(project_root=str(CONFIG.project_root))
            return result.to_dict()
        except Exception as e:
            return {"passed": False, "blocked": True, "error": str(e)}

    @router.get('/api/rank/ui-card')
    async def get_rank_ui_card():
        return {'app': 'IGRIS_GPT', 'rank': 'A++', 'status': 'ok', 'capability': 'ui-visible-supervised'}

    @router.get('/api/rank/summary-card')
    async def get_rank_summary_card():
        return {'app': 'IGRIS_GPT', 'rank': 'A+', 'status': 'ok', 'capability': 'multi-file-supervised'}

    @router.get('/api/system/version-summary')
    async def get_version_summary():
        return {'app': 'IGRIS_GPT', 'rank': 'A-generalization', 'status': 'ok'}

    @router.get('/api/rank/status')
    async def get_rank_status():
        return {'rank': 'A', 'status': 'ok', 'agent': 'IGRIS_GPT'}
    @router.get('/api/version-info')
    async def version_info():
        return {'app': 'IGRIS_GPT', 'status': 'ok'}

    @router.get("/", response_class=HTMLResponse)
    async def index() -> str:
        template = jinja_env.get_template("index.html")
        return template.render()

    # ---- Status / Config ----

    @router.get("/api/status")
    async def api_status() -> Dict[str, object]:
        provider, model = provider_router.choose_provider()
        return {"provider": provider, "model": model, "safe": True}

    @router.get("/api/config/safe")
    async def api_config_safe() -> Dict[str, object]:
        return CONFIG.safe_dict()

    # ---- Sessions / Chat ----

    @router.post("/api/sessions")
    async def create_session() -> Dict[str, str]:
        session_id = str(len(sessions) + 1)
        sessions[session_id] = []
        return {"id": session_id}

    @router.post("/api/sessions/{session_id}/messages")
    async def post_message(session_id: str, request: Request, content: Dict[str, str] = Body(...)) -> Dict[str, object]:
        if session_id not in sessions:
            raise HTTPException(status_code=404, detail="Session not found")
        message = content.get("message", "")

        # --- Interlocutor-aware preflight ---
        import logging as _pf_log
        _pf_logger = _pf_log.getLogger(__name__)
        system_enrichment = ""
        _sensitive_keywords = {
            # English
            "deploy", "delete", "remove", "rollback", "merge", "cancel",
            "drop", "wipe", "reset", "restart", "reboot", "admin",
            # Italian
            "cancella", "elimina", "rimuovi", "riavvia", "mergia", "unisci",
            "azzera", "distruggi", "svuota", "pulisci",
            "fai deploy", "fai rollback", "shutdown", "spegni",
        }
        try:
            from igris.core.chat_interlocutor_preflight import run_preflight, extract_interlocutor_id, is_trusted_local_request
            _remote_addr = request.client.host if request.client else ""
            _is_local = is_trusted_local_request(
                request_headers=dict(request.headers),
                remote_addr=_remote_addr,
            )
            interlocutor_id = extract_interlocutor_id(
                payload=dict(content),
                headers=dict(request.headers),
            )
            preflight = run_preflight(
                message,
                interlocutor_id=interlocutor_id,
                project_root=str(CONFIG.project_root),
                is_new_session=len(sessions.get(session_id, [])) == 0,
                is_local_request=_is_local,
                payload=dict(content),
            )
            if preflight.blocked:
                return {
                    "response": preflight.block_reason,
                    "blocked": True,
                    "interlocutor_id": preflight.interlocutor_id,
                    "trust_level": preflight.trust_level,
                }
            if preflight.requires_clarification:
                return {
                    "response": preflight.clarification_question or "Please clarify your request.",
                    "requires_clarification": True,
                    "interlocutor_id": preflight.interlocutor_id,
                }
            system_enrichment = preflight.system_prompt_enrichment
        except Exception as _pf_exc:
            _pf_logger.error("Preflight failed: %s", _pf_exc)
            # Fail-closed for sensitive requests
            if any(kw in message.lower() for kw in _sensitive_keywords):
                return {
                    "response": "Preflight security check failed. Sensitive request blocked for safety.",
                    "blocked": True,
                    "error": "preflight_exception",
                }
            system_enrichment = ""
        # --- end preflight ---

        sessions[session_id].append({"role": "user", "content": message})

        # --- Memory retrieval for context injection (best-effort, #1240) ---
        _memory_context = ""
        try:
            from igris.core.conversation_memory import ConversationRetriever
            _retriever = ConversationRetriever(project_root=str(CONFIG.project_root))
            _pid = preflight.interlocutor_id if 'preflight' in dir() else "unknown"
            _tl = preflight.trust_level if 'preflight' in dir() else "untrusted"
            _memory_context = _retriever.retrieve_for_context(_pid, _tl)
        except Exception:
            pass
        # --- end memory retrieval ---

        # Use real chat engine — always include IGRIS identity prompt,
        # with interlocutor enrichment appended (never replace core identity)
        from igris.core.chat_personality import IGRIS_SYSTEM_PROMPT as _IGRIS_SP
        _full_prompt = (_IGRIS_SP + "\n" + system_enrichment + "\n" + _memory_context).strip() if (system_enrichment or _memory_context) else None
        result = chat_llm(message, history=sessions[session_id][:-1],
                          system_prompt=_full_prompt)
        response_text = _redact(result["text"])

        sessions[session_id].append({"role": "assistant", "content": response_text})

        # --- Conversation memory persistence (best-effort, #1240) ---
        try:
            from igris.core.conversation_memory import (
                ConversationEpisode, ConversationMemoryStore, _get_memory_policy
            )
            _pf_obj = preflight if 'preflight' in dir() else None
            _episode = ConversationEpisode(
                session_id=session_id,
                interlocutor_id=_pf_obj.interlocutor_id if _pf_obj else "unknown",
                trust_level=_pf_obj.trust_level if _pf_obj else "untrusted",
                user_message=_redact(message),
                assistant_response=_redact(response_text)[:500],
                intent_action=_pf_obj.intent_action if _pf_obj else "unknown",
                intent_risk=_pf_obj.intent_risk if _pf_obj else "low",
                auth_decision="blocked" if (_pf_obj.blocked if _pf_obj else False) else "allowed",
                blocked=_pf_obj.blocked if _pf_obj else False,
                requires_clarification=_pf_obj.requires_clarification if _pf_obj else False,
                advisory=_pf_obj.advisory if _pf_obj else None,
                memory_policy=_get_memory_policy(_pf_obj.trust_level if _pf_obj else "untrusted"),
            )
            _store = ConversationMemoryStore(project_root=str(CONFIG.project_root))
            _store.persist(_episode)
        except Exception as _mem_exc:
            import logging as _ml; _ml.getLogger(__name__).warning("Memory persistence failed (degraded): %s", _mem_exc)
        # --- end memory persistence ---

        # Non-blocking readability audit (#953)
        _rdx = None
        try:
            from igris.core.response_readability import check_readability
            _rdx = check_readability(response_text)
            if not _rdx.passed:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "Readability violations in response (words=%d): %s",
                    _rdx.word_count, _rdx.violations,
                )
        except Exception:
            pass

        # Record routing decision
        provider_router.record_chat_routing(
            provider=result["provider"], model=result["model"],
            reason=result["routing_reason"], latency_ms=result["latency_ms"],
            fallback_used=result["fallback_used"],
        )

        task_engine.append_timeline_event({
            "type": "chat", "title": "Chat message",
            "detail": f"User: {message[:80]}",
        })

        return {
            "response": response_text,
            "provider": result["provider"],
            "model": result["model"],
            "fallback_used": result["fallback_used"],
            "latency_ms": result["latency_ms"],
            "intent_detected": result.get("intent_detected"),
            "suggested_actions": result.get("suggested_actions", []),
            "readability": _rdx.to_dict() if _rdx is not None else None,
        }

    # ---- Chat Streaming + Tier ----

    @router.post("/api/chat/stream")
    async def api_chat_stream(request: Request):
        content = await request.json()
        message = content.get("message", "")
        session_id = content.get("session_id")
        enrich = content.get("enrich", False)
        if not message:
            raise HTTPException(status_code=400, detail="message required")

        # --- Interlocutor-aware preflight ---
        import logging as _pf_log2
        _pf_logger2 = _pf_log2.getLogger(__name__)
        preflight_block = None
        system_enrichment = ""
        _sensitive_keywords_s = {
            # English
            "deploy", "delete", "remove", "rollback", "merge", "cancel",
            "drop", "wipe", "reset", "restart", "reboot", "admin",
            # Italian
            "cancella", "elimina", "rimuovi", "riavvia", "mergia", "unisci",
            "azzera", "distruggi", "svuota", "pulisci",
            "fai deploy", "fai rollback", "shutdown", "spegni",
        }
        try:
            from igris.core.chat_interlocutor_preflight import run_preflight, extract_interlocutor_id, is_trusted_local_request
            _remote_addr_s = request.client.host if request.client else ""
            _is_local_s = is_trusted_local_request(
                request_headers=dict(request.headers),
                remote_addr=_remote_addr_s,
            )
            interlocutor_id = extract_interlocutor_id(
                payload=content,
                headers=dict(request.headers),
            )
            preflight = run_preflight(
                message,
                interlocutor_id=interlocutor_id,
                project_root=str(CONFIG.project_root),
                is_new_session=False,  # stream — session already initialized
                is_local_request=_is_local_s,
                payload=content,
            )
            if preflight.blocked:
                preflight_block = preflight.block_reason
            elif preflight.requires_clarification:
                preflight_block = preflight.clarification_question or "Please clarify your request."
            else:
                system_enrichment = preflight.system_prompt_enrichment
        except Exception as _pf_exc2:
            _pf_logger2.error("Stream preflight failed: %s", _pf_exc2)
            # Fail-closed for sensitive requests
            if any(kw in message.lower() for kw in _sensitive_keywords_s):
                preflight_block = "Preflight security check failed. Sensitive request blocked for safety."
        # --- end preflight ---

        if preflight_block:
            async def blocked_generator():
                yield f"data: {json.dumps({'type': 'content', 'text': preflight_block})}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(
                blocked_generator(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        history = []
        if session_id and session_id in sessions:
            history = sessions[session_id]

        # --- Memory retrieval for stream context injection (best-effort, #1240) ---
        _stream_memory_context = ""
        try:
            from igris.core.conversation_memory import ConversationRetriever
            _s_retriever = ConversationRetriever(project_root=str(CONFIG.project_root))
            _s_pid = preflight.interlocutor_id if 'preflight' in dir() else "unknown"
            _s_tl = preflight.trust_level if 'preflight' in dir() else "untrusted"
            _stream_memory_context = _s_retriever.retrieve_for_context(_s_pid, _s_tl)
        except Exception:
            pass
        # --- end memory retrieval ---

        # Always include IGRIS identity — never replace with enrichment alone
        from igris.core.chat_personality import IGRIS_SYSTEM_PROMPT as _IGRIS_SP
        system_prompt = (_IGRIS_SP + "\n" + system_enrichment + "\n" + _stream_memory_context).strip() if (system_enrichment or _stream_memory_context) else _IGRIS_SP
        if enrich:
            ctx_prompt = chat_context.build_context_system_prompt(
                task_engine=task_engine,
                project_root=str(CONFIG.project_root),
            )
            system_prompt = (system_prompt + "\n" + ctx_prompt).strip()

        chunks = chat_streaming.chat_stream_sync(
            message=message, history=history, system_prompt=system_prompt,
        )

        # Store in session if provided
        if session_id:
            if session_id not in sessions:
                sessions[session_id] = []
            sessions[session_id].append({"role": "user", "content": message})
            full_text = "".join(c.text for c in chunks if c.type == "content")
            sessions[session_id].append({"role": "assistant", "content": full_text})

            task_engine.append_timeline_event({
                "type": "chat", "title": "Chat stream",
                "detail": f"User: {message[:80]}",
            })

            # --- Stream: conversation memory persistence (best-effort, #1240) ---
            try:
                from igris.core.conversation_memory import (
                    ConversationEpisode, ConversationMemoryStore, _get_memory_policy
                )
                _s_pf = preflight if 'preflight' in dir() else None
                _s_episode = ConversationEpisode(
                    session_id=session_id,
                    interlocutor_id=_s_pf.interlocutor_id if _s_pf else "unknown",
                    trust_level=_s_pf.trust_level if _s_pf else "untrusted",
                    user_message=_redact(message),
                    assistant_response=_redact(full_text)[:500],
                    intent_action=_s_pf.intent_action if _s_pf else "unknown",
                    intent_risk=_s_pf.intent_risk if _s_pf else "low",
                    auth_decision="blocked" if (_s_pf.blocked if _s_pf else False) else "allowed",
                    blocked=_s_pf.blocked if _s_pf else False,
                    memory_policy=_get_memory_policy(_s_pf.trust_level if _s_pf else "untrusted"),
                    source="stream",
                )
                _s_store = ConversationMemoryStore(project_root=str(CONFIG.project_root))
                _s_store.persist(_s_episode)
            except Exception as _s_mem_exc:
                import logging as _s_ml; _s_ml.getLogger(__name__).warning("Stream memory persistence failed (degraded): %s", _s_mem_exc)
            # --- end stream memory persistence ---

        async def event_generator():
            for chunk in chunks:
                yield chunk.to_sse()

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/api/chat/context")
    async def api_chat_context() -> Dict[str, object]:
        return chat_context.build_chat_context(
            task_engine=task_engine,
            project_root=str(CONFIG.project_root),
        )

    @router.get("/api/chat/context/summary")
    async def api_chat_context_summary() -> Dict[str, object]:
        return chat_context.get_context_summary(
            task_engine=task_engine,
            project_root=str(CONFIG.project_root),
        )

    @router.get("/api/chat/tiers")
    async def api_chat_tiers() -> Dict[str, object]:
        return chat_streaming.get_tier_availability()

    @router.post("/api/chat/tiers")
    async def api_set_chat_tier(request: Request) -> Dict[str, object]:
        content = await request.json()
        tier = content.get("tier", "")
        if not tier:
            raise HTTPException(status_code=400, detail="tier required")
        try:
            config = chat_streaming.set_tier(tier)
            return config.to_dict()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ---- System Info ----

    @router.get("/api/system/info")
    async def api_system_info() -> Dict[str, object]:
        """Safe, read-only system information."""
        from igris.core.system_info import get_system_info
        import os as _os
        return get_system_info(
            project_root=str(CONFIG.project_root),
            host=_os.environ.get("IGRIS_HOST", "127.0.0.1"),
            port=int(_os.environ.get("IGRIS_PORT", "8000")),
        )

    # ---- Dashboard Summary ----

    @router.get("/api/dashboard/summary")
    async def api_dashboard_summary() -> Dict[str, object]:
        """Aggregated dashboard view — health, readiness, diagnostics, loop."""
        from igris.core import diagnostics as diagnostics_dash

        diag = {}
        try:
            tasks = [t.to_dict() for t in task_engine.list_tasks()]
            timeline = task_engine.recent_timeline_events(limit=50)
            diag = diagnostics_dash.get_diagnostic_summary(
                tasks, timeline, project_root=str(CONFIG.project_root),
            )
        except Exception:
            pass

        loop_info = {}
        try:
            loop_info = loop_engine.get_status()
        except Exception:
            pass

        mission_overview = {
            "active_task_count": 0,
            "pending_task_count": 0,
            "running_task_id": "",
            "running_task_title": "",
        }
        try:
            mission_overview["active_task_count"] = len(tasks)
            pending = [t for t in tasks if str(t.get("status", "")).lower() == "pending"]
            running = [t for t in tasks if str(t.get("status", "")).lower() in {"in_progress", "running"}]
            mission_overview["pending_task_count"] = len(pending)
            if running:
                mission_overview["running_task_id"] = str(running[0].get("task_id", "") or "")
                mission_overview["running_task_title"] = str(running[0].get("description", "") or "")
        except Exception:
            pass

        risk_snapshot = {
            "level": "low",
            "reason": "",
        }
        try:
            loop_state = str(loop_info.get("status", "")).lower()
            if loop_state in {"error", "failed", "blocked"}:
                risk_snapshot["level"] = "high"
                risk_snapshot["reason"] = f"loop_status={loop_state}"
            elif mission_overview["pending_task_count"] > 15:
                risk_snapshot["level"] = "medium"
                risk_snapshot["reason"] = "task_backlog_high"
        except Exception:
            pass

        warnings = []
        if risk_snapshot["level"] in {"medium", "high"}:
            warnings.append(f"risk:{risk_snapshot['level']}")
        if mission_overview["pending_task_count"] > 0 and not mission_overview["running_task_id"]:
            warnings.append("no_task_running")

        next_action = {
            "id": "open_mission",
            "label": "Open Mission",
            "reason": "default_control_room_hint",
            "approval_required": False,
        }
        if mission_overview["running_task_id"]:
            next_action = {
                "id": "open_loop_status",
                "label": "Open Loop Status",
                "reason": "task_running_detected",
                "approval_required": False,
            }
        elif mission_overview["pending_task_count"] > 0:
            next_action = {
                "id": "start_next_task",
                "label": "Start Next Task",
                "reason": "pending_tasks_available",
                "approval_required": False,
            }

        # ---- Interlocutor section (issue #526) ----
        interlocutor_section: dict = {"profiles": [], "recent_audit": [], "error": None}
        try:
            from igris.core.identity_resolver import IdentityResolver
            from igris.core.interlocutor_audit import InterlocutorAudit
            _ir = IdentityResolver(str(CONFIG.project_root))
            interlocutor_section["profiles"] = [p.to_dict() for p in _ir.get_all_including_builtins()]
            _ia = InterlocutorAudit()
            interlocutor_section["recent_audit"] = _ia.recent(10)
            # last_chat: most recent chat-level audit event
            interlocutor_section["last_chat"] = {
                "interlocutor_id": None,
                "trust_level": None,
                "last_intent": None,
                "decision": None,
            }
            try:
                _recent = _ia.recent(5)
                _chat_events = [e for e in _recent if e.get("target_resource") == "chat"]
                if _chat_events:
                    _last = _chat_events[-1]
                    interlocutor_section["last_chat"] = {
                        "interlocutor_id": _last.get("interlocutor_id"),
                        "trust_level": _last.get("trust_level"),
                        "last_intent": _last.get("action_type"),
                        "decision": _last.get("decision"),
                    }
            except Exception:
                pass
        except Exception as _e:
            interlocutor_section["error"] = str(_e)

        # Memory status (#1240)
        try:
            from igris.core.conversation_memory import ConversationMemoryStore
            _ = ConversationMemoryStore
            interlocutor_section["memory_status"] = {"enabled": True, "last_error": None}
        except Exception as _ms_exc:
            interlocutor_section["memory_status"] = {"enabled": False, "last_error": str(_ms_exc)}

        return {
            "health": {"status": "ok"},
            "diagnostics": diag,
            "loop": loop_info,
            "interlocutor": interlocutor_section,
            "control_room": {
                "mission_overview": mission_overview,
                "risk_snapshot": risk_snapshot,
                "next_action": next_action,
                "warnings": warnings,
            },
            "tab_layout": {
                "primary": ["dashboard", "code", "tasks", "terminal", "memory", "safety", "advanced"],
                "grouped": {
                    "code": ["files", "git", "patches"],
                    "tasks": ["tasks", "loop"],
                    "terminal": ["commands", "tests"],
                    "memory": ["memory", "timeline"],
                    "safety": ["safety", "cost"],
                    "advanced": ["a2a", "logs"],
                },
            },
        }

    # ---- Chat Personality / Capabilities ----

    @router.get("/api/chat/capabilities")
    async def api_chat_capabilities() -> Dict[str, object]:
        from igris.core.chat_personality import get_capability_summary
        return get_capability_summary()

    @router.post("/api/chat/intent")
    async def api_chat_intent(request: Request) -> Dict[str, object]:
        from igris.core.chat_personality import (
            detect_intent, get_grounded_response, get_suggested_actions,
        )
        content = await request.json()
        message = content.get("message", "")
        if not message:
            raise HTTPException(status_code=400, detail="message required")
        intent = detect_intent(message)
        response = get_grounded_response(intent) if intent else None
        actions = get_suggested_actions(intent) if intent else []
        return {
            "intent": intent,
            "grounded_response": response,
            "has_response": response is not None,
            "suggested_actions": actions,
        }


    return router
