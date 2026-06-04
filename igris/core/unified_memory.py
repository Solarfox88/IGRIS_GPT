"""Unified Memory Facade — single entry point for all memory operations (#1242).

Architecture:
- UnifiedMemory is the ONLY interface other modules should use for memory.
- All backends (LTM, MemoryGraph, ConversationMemoryStore, etc.) are accessed
  through this facade, never directly by chat/mission/reasoning modules.
- Degraded backends produce warnings but don't crash the system.
- Security: no auto-elevation, no raw secrets, trust-level enforcement throughout.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Secret redaction ──────────────────────────────────────────────────────────

_SECRET_PATTERNS = [
    re.compile(
        r'(token|passphrase|password|secret|api[_\s]?key|private[_\s]?key|bearer'
        r'|(?<!\w)key(?!\w)|auth|credential|cred)'
        r'\s*[=:]\s*\S+',
        re.IGNORECASE,
    ),
    re.compile(r'[A-Za-z0-9+/]{20,}={0,2}'),  # base64-like
]


def _redact(text: str) -> str:
    if not text:
        return text
    for p in _SECRET_PATTERNS:
        text = p.sub('<REDACTED>', text)
    return text


# ── Primary backends (degraded = healthcheck fails) ───────────────────────────

_PRIMARY_BACKENDS = {"long_term_memory", "conversation_memory"}

# ── Trust policy ──────────────────────────────────────────────────────────────

_SENSITIVE_TRUST = {"admin", "owner", "trusted"}


def _allows_sensitive(trust_level: str) -> bool:
    return trust_level.lower() in _SENSITIVE_TRUST


# ── Result types ─────────────────────────────────────────────────────────────

@dataclass
class StoreResult:
    ok: bool
    kind: str
    id: str = ""
    backends: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "kind": self.kind, "id": self.id,
                "backends": self.backends, "warnings": self.warnings}


@dataclass
class MemoryItem:
    id: str
    source: str          # conversation|ltm|graph|topic|embedding
    kind: str            # preference|decision|correction|lesson|fact|episode|run_event
    text: str
    score: float = 0.5
    confidence: float = 0.7
    why_selected: str = ""
    safe_for_context: bool = True
    trust_required: str = "untrusted"
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "source": self.source, "kind": self.kind,
            "text": _redact(self.text), "score": self.score,
            "confidence": self.confidence, "why_selected": self.why_selected,
            "safe_for_context": self.safe_for_context,
            "trust_required": self.trust_required,
        }


@dataclass
class RetrievalResult:
    context: str
    items: list
    influence_report: str
    degraded: bool = False
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "context": _redact(self.context),
            "items": [i.to_dict() for i in self.items],
            "influence_report": _redact(self.influence_report),
            "degraded": self.degraded,
            "warnings": self.warnings,
        }


# ── UnifiedMemory ─────────────────────────────────────────────────────────────

class UnifiedMemory:
    """Unified facade for all IGRIS memory operations.

    Usage:
        mem = UnifiedMemory(project_root="/path/to/igris")
        result = mem.store_preference("owner", "admin", "Prefer short answers")
        ctx = mem.retrieve_for_chat("report query", "owner", "admin")
    """

    def __init__(self, project_root: "str | Path | None" = None):
        if project_root is None:
            try:
                from igris.models.config import CONFIG
                project_root = CONFIG.project_root
            except Exception:
                project_root = Path.home()
        self.project_root = Path(project_root)
        self._backends: dict = {}  # name -> "ok"|"degraded"|"unavailable"
        self._ltm = None
        self._graph = None
        self._conv_store = None
        self._retriever = None
        self._summary_mgr = None
        self._scorer = None
        self._topic_tree = None
        self._embedding_store = None
        self._init_backends()

    def _init_backends(self) -> None:
        """Initialize backends lazily; track status for healthcheck."""
        # LongTermMemory
        try:
            from igris.core.long_term_memory import LongTermMemory
            ltm_path = self.project_root / ".igris" / "memory" / "long_term"
            self._ltm = LongTermMemory(storage_dir=str(ltm_path))
            self._backends["long_term_memory"] = "ok"
        except Exception as e:
            logger.warning("UnifiedMemory: LongTermMemory unavailable: %s", e)
            self._backends["long_term_memory"] = "degraded"

        # MemoryGraph
        try:
            from igris.core.memory_graph import MemoryGraph
            self._graph = MemoryGraph(str(self.project_root))
            self._backends["memory_graph"] = "ok"
        except Exception as e:
            logger.debug("UnifiedMemory: MemoryGraph unavailable: %s", e)
            self._backends["memory_graph"] = "degraded"

        # ConversationMemory
        try:
            from igris.core.conversation_memory import (
                ConversationMemoryStore, ConversationRetriever, ConversationSummaryManager
            )
            self._conv_store = ConversationMemoryStore(project_root=str(self.project_root))
            self._retriever = ConversationRetriever(project_root=str(self.project_root))
            self._summary_mgr = ConversationSummaryManager(project_root=str(self.project_root))
            self._backends["conversation_memory"] = "ok"
        except Exception as e:
            logger.warning("UnifiedMemory: ConversationMemory unavailable: %s", e)
            self._backends["conversation_memory"] = "degraded"

        # MemoryScorer (optional)
        try:
            from igris.core.memory_scorer import MemoryScorer
            self._scorer = MemoryScorer(str(self.project_root))
            self._backends["memory_scorer"] = "ok"
        except Exception:
            self._backends["memory_scorer"] = "unavailable"

        # TopicTree (optional)
        try:
            from igris.core.memory_topic_tree import MemoryTopicTree
            self._topic_tree = MemoryTopicTree(str(self.project_root))
            self._backends["topic_tree"] = "ok"
        except Exception:
            self._backends["topic_tree"] = "unavailable"

        # EmbeddingStore (optional — best-effort only)
        try:
            from igris.core.embedding_store import EmbeddingStore
            self._embedding_store = EmbeddingStore(str(self.project_root))
            self._backends["embedding_store"] = "ok"
        except Exception:
            self._backends["embedding_store"] = "unavailable"

    # ── Store operations ──────────────────────────────────────────────────────

    def store_episode(self, episode_or_kwargs, **kwargs) -> StoreResult:
        """Store a conversation episode via ConversationMemoryStore."""
        backends_status: dict = {}
        warnings: list = []
        ep_id = str(uuid.uuid4())

        try:
            from igris.core.conversation_memory import ConversationEpisode
            if isinstance(episode_or_kwargs, ConversationEpisode):
                ep = episode_or_kwargs
            else:
                ep = ConversationEpisode(**{**episode_or_kwargs, **kwargs})
            ep_id = ep.episode_id
        except Exception as e:
            return StoreResult(ok=False, kind="episode", id="", warnings=[str(e)])

        if self._conv_store:
            try:
                ok = self._conv_store.persist(ep)
                backends_status["conversation_store"] = "ok" if ok else "degraded"
            except Exception as e:
                backends_status["conversation_store"] = "degraded"
                warnings.append(f"conv_store: {e}")
        else:
            backends_status["conversation_store"] = "unavailable"

        return StoreResult(ok=True, kind="episode", id=ep_id,
                           backends=backends_status, warnings=warnings)

    def store_preference(self, interlocutor_id: str, trust_level: str, text: str,
                         tags: "list | None" = None) -> StoreResult:
        """Store a user preference in synaptic/preference domain."""
        text = _redact(text)
        warnings: list = []
        backends_status: dict = {}
        entry_id = str(uuid.uuid4())
        domain = f"synaptic:{interlocutor_id}"
        any_primary_wrote = False

        if self._ltm:
            try:
                entry = self._ltm.add_entry(
                    domain=domain,
                    content={"kind": "preference", "text": text,
                              "interlocutor_id": interlocutor_id,
                              "trust_level": trust_level, "id": entry_id,
                              "tags": tags or []},
                    source="unified_memory",
                    tags=tags or [],
                    importance=0.8,
                )
                entry_id = entry.id
                backends_status["ltm"] = "ok"
                any_primary_wrote = True
            except Exception as e:
                backends_status["ltm"] = "degraded"
                warnings.append(f"ltm: {e}")
                logger.warning("store_preference LTM failed: %s", e)
        else:
            backends_status["ltm"] = "unavailable"

        return StoreResult(ok=any_primary_wrote, kind="preference",
                           id=entry_id if any_primary_wrote else "",
                           backends=backends_status, warnings=warnings)

    def store_decision(self, text: str, interlocutor_id: str = "unknown",
                       trust_level: str = "untrusted", project: str = "default",
                       confidence: float = 0.8, tags: "list | None" = None) -> StoreResult:
        """Store a project/operational decision."""
        text = _redact(text)
        entry_id = str(uuid.uuid4())
        warnings: list = []
        backends_status: dict = {}
        domain = f"decision:{project}"
        any_primary_wrote = False

        if self._ltm:
            try:
                entry = self._ltm.add_entry(
                    domain=domain,
                    content={"kind": "decision", "text": text,
                              "interlocutor_id": interlocutor_id,
                              "project": project, "confidence": confidence,
                              "tags": tags or [], "id": entry_id},
                    source="unified_memory",
                    tags=tags or [],
                    importance=confidence,
                )
                entry_id = entry.id
                backends_status["ltm"] = "ok"
                any_primary_wrote = True
            except Exception as e:
                backends_status["ltm"] = "degraded"
                warnings.append(f"ltm: {e}")
                logger.warning("store_decision LTM failed: %s", e)
        else:
            backends_status["ltm"] = "unavailable"

        return StoreResult(ok=any_primary_wrote, kind="decision",
                           id=entry_id if any_primary_wrote else "",
                           backends=backends_status, warnings=warnings)

    def store_correction(self, text: str, interlocutor_id: str = "unknown",
                         trust_level: str = "untrusted",
                         supersedes_id: "str | None" = None) -> StoreResult:
        """Store an explicit user correction."""
        text = _redact(text)
        entry_id = str(uuid.uuid4())
        warnings: list = []
        backends_status: dict = {}
        domain = f"synaptic:{interlocutor_id}"
        any_primary_wrote = False

        if self._ltm:
            try:
                entry = self._ltm.add_entry(
                    domain=domain,
                    content={"kind": "correction", "text": text,
                              "interlocutor_id": interlocutor_id,
                              "supersedes_id": supersedes_id, "id": entry_id},
                    source="unified_memory",
                    tags=[],
                    importance=0.9,
                )
                entry_id = entry.id
                backends_status["ltm"] = "ok"
                any_primary_wrote = True
            except Exception as e:
                backends_status["ltm"] = "degraded"
                warnings.append(f"ltm: {e}")
                logger.warning("store_correction LTM failed: %s", e)
        else:
            backends_status["ltm"] = "unavailable"

        return StoreResult(ok=any_primary_wrote, kind="correction",
                           id=entry_id if any_primary_wrote else "",
                           backends=backends_status, warnings=warnings)

    def store_lesson(self, text: str, project: str = "default",
                     confidence: float = 0.85, tags: "list | None" = None) -> StoreResult:
        """Store an operational lesson."""
        text = _redact(text)
        entry_id = str(uuid.uuid4())
        warnings: list = []
        backends_status: dict = {}
        domain = f"lesson:{project}"
        any_primary_wrote = False

        if self._ltm:
            try:
                entry = self._ltm.add_entry(
                    domain=domain,
                    content={"kind": "lesson", "text": text,
                              "project": project, "confidence": confidence,
                              "tags": tags or [], "id": entry_id},
                    source="unified_memory",
                    tags=tags or [],
                    importance=confidence,
                )
                entry_id = entry.id
                backends_status["ltm"] = "ok"
                any_primary_wrote = True
            except Exception as e:
                backends_status["ltm"] = "degraded"
                warnings.append(f"ltm: {e}")
                logger.warning("store_lesson LTM failed: %s", e)
        else:
            backends_status["ltm"] = "unavailable"

        return StoreResult(ok=any_primary_wrote, kind="lesson",
                           id=entry_id if any_primary_wrote else "",
                           backends=backends_status, warnings=warnings)

    def store_run_event(self, mission_id: str, action: str, status: str,
                        outcome: str = "", evidence_ref: str = "",
                        project: str = "default") -> StoreResult:
        """Store an operational run event."""
        # Fix 4: Redact sensitive fields before persistence
        action = _redact(action)
        outcome = _redact(outcome)
        evidence_ref = _redact(evidence_ref)
        entry_id = str(uuid.uuid4())
        warnings: list = []
        backends_status: dict = {}
        domain = f"run:{project}"
        text = f"[{status}] {action}: {outcome}"
        any_primary_wrote = False

        if self._ltm:
            try:
                entry = self._ltm.add_entry(
                    domain=domain,
                    content={"kind": "run_event", "text": text,
                              "mission_id": mission_id, "action": action,
                              "status": status, "outcome": outcome,
                              "evidence_ref": evidence_ref, "id": entry_id},
                    source="unified_memory",
                    tags=[],
                    importance=0.6,
                )
                entry_id = entry.id
                backends_status["ltm"] = "ok"
                any_primary_wrote = True
            except Exception as e:
                backends_status["ltm"] = "degraded"
                warnings.append(f"ltm: {e}")
                logger.warning("store_run_event LTM failed: %s", e)
        else:
            backends_status["ltm"] = "unavailable"

        return StoreResult(ok=any_primary_wrote, kind="run_event",
                           id=entry_id if any_primary_wrote else "",
                           backends=backends_status, warnings=warnings)

    def store_fact(self, text: str, fact_type: str = "project_fact",
                   project: str = "default", confidence: float = 0.9) -> StoreResult:
        """Store a stable fact (identity_fact, project_fact, environment_fact, etc.)."""
        text = _redact(text)
        entry_id = str(uuid.uuid4())
        warnings: list = []
        backends_status: dict = {}
        domain = f"fact:{project}"
        any_primary_wrote = False

        if self._ltm:
            try:
                entry = self._ltm.add_entry(
                    domain=domain,
                    content={"kind": fact_type, "text": text,
                              "project": project, "confidence": confidence,
                              "id": entry_id},
                    source="unified_memory",
                    tags=[],
                    importance=confidence,
                )
                entry_id = entry.id
                backends_status["ltm"] = "ok"
                any_primary_wrote = True
            except Exception as e:
                backends_status["ltm"] = "degraded"
                warnings.append(f"ltm: {e}")
                logger.warning("store_fact LTM failed: %s", e)
        else:
            backends_status["ltm"] = "unavailable"

        return StoreResult(ok=any_primary_wrote, kind=fact_type,
                           id=entry_id if any_primary_wrote else "",
                           backends=backends_status, warnings=warnings)

    # ── Retrieve operations ───────────────────────────────────────────────────

    def retrieve_for_chat(self, query: str, interlocutor_id: str, trust_level: str,
                          limit: int = 8, include_influence: bool = True) -> RetrievalResult:
        """Retrieve memory context for chat system prompt injection."""
        from igris.core.memory_retrieval_hybrid import HybridRetriever

        retriever = HybridRetriever(
            project_root=self.project_root,
            ltm=self._ltm,
            graph=self._graph,
            conv_retriever=self._retriever,
            embedding_store=self._embedding_store,
        )
        return retriever.retrieve(
            query=query,
            interlocutor_id=interlocutor_id,
            trust_level=trust_level,
            limit=limit,
            context="chat",
            include_influence=include_influence,
        )

    def retrieve_for_mission(self, goal: str, mission_type: "str | None" = None,
                              interlocutor_id: str = "unknown",
                              trust_level: str = "untrusted",
                              project: str = "default", limit: int = 10) -> RetrievalResult:
        """Retrieve memory for mission/reasoning loop context."""
        from igris.core.memory_retrieval_hybrid import HybridRetriever

        retriever = HybridRetriever(
            project_root=self.project_root,
            ltm=self._ltm,
            graph=self._graph,
            conv_retriever=self._retriever,
            embedding_store=self._embedding_store,
        )
        return retriever.retrieve(
            query=goal,
            interlocutor_id=interlocutor_id,
            trust_level=trust_level,
            limit=limit,
            context="mission",
            project=project,
            mission_type=mission_type,
        )

    # ── Feedback / lifecycle ──────────────────────────────────────────────────

    def record_feedback(self, memory_id: str, used: bool, helpful: "bool | None" = None,
                        outcome: str = "neutral", mission_id: str = "",
                        query: str = "", notes: str = "") -> StoreResult:
        """Record feedback on a memory item (for future learning)."""
        # Fix 5: Redact sensitive fields
        query = _redact(query)
        notes = _redact(notes)
        entry_id = str(uuid.uuid4())
        warnings: list = []
        domain = "feedback:system"
        content = {"kind": "feedback", "memory_id": memory_id, "used": used,
                   "helpful": helpful, "outcome": outcome, "id": entry_id,
                   "mission_id": mission_id, "query": query, "notes": notes}

        if self._ltm:
            try:
                self._ltm.add_entry(
                    domain=domain,
                    content=content,
                    source="unified_memory",
                    tags=[],
                    importance=0.3,
                )
            except Exception as e:
                warnings.append(f"feedback ltm: {e}")
                logger.warning("record_feedback LTM failed: %s", e)

        return StoreResult(ok=True, kind="feedback", id=entry_id, warnings=warnings)

    def mark_superseded(self, memory_id: str, superseded_by_id: str,
                        reason: str = "") -> StoreResult:
        """Mark a memory as superseded by a newer one."""
        entry_id = str(uuid.uuid4())
        warnings: list = []
        any_wrote = False
        content = {"kind": "superseded", "memory_id": memory_id,
                   "superseded_by": superseded_by_id, "reason": reason}

        if self._ltm:
            try:
                self._ltm.add_entry(
                    domain="superseded:system",
                    content=content,
                    source="unified_memory",
                    tags=[],
                    importance=0.5,
                )
                any_wrote = True
            except Exception as e:
                logger.warning("mark_superseded LTM failed: %s", e)
                warnings.append(f"ltm: {e}")

        return StoreResult(ok=any_wrote or self._ltm is None, kind="superseded",
                           id=entry_id, warnings=warnings)

    def forget(self, memory_id: str, reason: str = "user_request") -> StoreResult:
        """Soft-delete a memory item by marking it as forgotten."""
        warnings: list = []
        any_wrote = False
        content = {"kind": "forgotten", "memory_id": memory_id, "reason": reason}

        if self._ltm:
            try:
                self._ltm.add_entry(
                    domain="forgotten:system",
                    content=content,
                    source="unified_memory",
                    tags=[],
                    importance=0.1,
                )
                any_wrote = True
            except Exception as e:
                logger.warning("forget LTM failed: %s", e)
                warnings.append(f"ltm: {e}")

        return StoreResult(ok=any_wrote or self._ltm is None, kind="forgotten",
                           id=memory_id, warnings=warnings)

    def memory_influence_report(self, retrieval_result: RetrievalResult) -> str:
        """Generate a human-readable influence report from retrieval result."""
        if not retrieval_result.items:
            return "No memory context used."

        lines = ["Memorie usate:"]
        for item in retrieval_result.items[:5]:
            lines.append(
                f"- [{item.kind}] da {item.source} (score={item.score:.2f}): "
                f"{_redact(item.text[:80])}{'...' if len(item.text) > 80 else ''}"
            )
            if item.why_selected:
                lines.append(f"  Motivo: {item.why_selected}")

        if retrieval_result.degraded:
            lines.append("[Nota: alcuni backend non disponibili — risultati parziali]")

        return "\n".join(lines)

    def healthcheck(self) -> dict:
        """Return health status of all backends.

        ok=False if any PRIMARY backend (long_term_memory, conversation_memory) is degraded.
        Optional backends (memory_graph, topic_tree, etc.) degraded only add warnings.
        """
        primary_ok = all(
            self._backends.get(b, "degraded") == "ok"
            for b in _PRIMARY_BACKENDS
        )
        return {
            "ok": primary_ok,
            "backends": dict(self._backends),
            "warnings": [
                f"{k}: {v}" for k, v in self._backends.items()
                if v == "degraded"
            ],
        }
