"""Persistent synaptic conversation memory (#1240).

Implements:
- ConversationEpisode: persistent model for chat turns
- SynapticExtractor: deterministic extraction of preferences/decisions/corrections
- ConversationMemoryStore: persistence in LongTermMemory + MemoryGraph
- ConversationRetriever: secure retrieval respecting trust level
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Memory policy constants
MEMORY_POLICY_FULL = "full"       # owner/admin
MEMORY_POLICY_SCOPED = "scoped"   # trusted/limited
MEMORY_POLICY_MINIMAL = "minimal" # unknown/untrusted
MEMORY_POLICY_NONE = "none"       # explicitly opted out


def _get_memory_policy(trust_level: str) -> str:
    """Map trust level to memory policy."""
    tl = (trust_level or "").lower()
    if tl in ("admin", "owner"):
        return MEMORY_POLICY_FULL
    elif tl in ("trusted", "limited"):
        return MEMORY_POLICY_SCOPED
    elif tl in ("untrusted", "unknown", ""):
        return MEMORY_POLICY_MINIMAL
    return MEMORY_POLICY_MINIMAL


@dataclass
class ConversationEpisode:
    """A single persisted chat turn with metadata."""
    episode_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    interlocutor_id: str = "unknown"
    trust_level: str = "untrusted"
    user_message: str = ""         # already redacted
    assistant_response: str = ""   # already redacted
    intent_action: str = "unknown"
    intent_risk: str = "low"
    auth_decision: str = "allowed"
    blocked: bool = False
    requires_clarification: bool = False
    advisory: str | None = None
    timestamp: float = field(default_factory=time.time)
    source: str = "chat"
    tags: list = field(default_factory=list)
    importance: float = 0.5
    memory_policy: str = MEMORY_POLICY_MINIMAL

    def to_dict(self) -> dict:
        return {
            "episode_id": self.episode_id,
            "session_id": self.session_id,
            "interlocutor_id": self.interlocutor_id,
            "trust_level": self.trust_level,
            "user_message": self.user_message,
            "assistant_response": self.assistant_response,
            "intent_action": self.intent_action,
            "intent_risk": self.intent_risk,
            "auth_decision": self.auth_decision,
            "blocked": self.blocked,
            "requires_clarification": self.requires_clarification,
            "advisory": self.advisory,
            "timestamp": self.timestamp,
            "source": self.source,
            "tags": self.tags,
            "importance": self.importance,
            "memory_policy": self.memory_policy,
        }


# ---------------------------------------------------------------------------
# SynapticExtractor
# ---------------------------------------------------------------------------

PREFERENCE_PATTERNS = [
    re.compile(r'\b(preferisco|preferisci|mi piace|voglio sempre|usa sempre|usa solo|non usare|evita)\b', re.IGNORECASE),
    re.compile(r'\b(prefer|always use|never use|avoid|I want you to)\b', re.IGNORECASE),
]
CORRECTION_PATTERNS = [
    re.compile(r'\b(no,|correggi|sbagliato|non è così|non intendevo|mi hai capito male|correzione|actually|wait no)\b', re.IGNORECASE),
]
DECISION_PATTERNS = [
    re.compile(r'\b(decidiamo|ho deciso|scegliamo|useremo|andremo con|we decided|we will use|going with)\b', re.IGNORECASE),
]
NEGATIVE_PATTERNS = [
    re.compile(r'\b(non fare più|non farlo più|mai più|smettila di|stop doing|never do|don\'t do)\b', re.IGNORECASE),
]
FACT_PATTERNS = [
    re.compile(r'\b(il progetto si chiama|il repository è|il server è|the project is|the repo is|the server is)\b', re.IGNORECASE),
]
SECRET_PATTERNS = [
    re.compile(r'(passphrase|password|token|secret|api[_\s]?key|private[_\s]?key|bearer)\s*[=:]\s*\S+', re.IGNORECASE),
    re.compile(r'\b[A-Za-z0-9+/]{20,}={0,2}\b'),  # base64-like
]

TRIVIAL_MESSAGES = {"ok", "sì", "no", "grazie", "ciao", "ok grazie", "yes", "nope", "sure", "fine", "great"}


def _redact_for_storage(text: str) -> str:
    """Remove obvious secret patterns before writing to LongTermMemory."""
    if not text:
        return text
    # key=value patterns with secret-like keys
    text = re.sub(
        r'(token|passphrase|password|secret|api[_\s]?key|private[_\s]?key|bearer)\s*[=:]\s*\S+',
        r'\1=<REDACTED>',
        text,
        flags=re.IGNORECASE,
    )
    # Long base64-like strings (>20 chars)
    text = re.sub(r'[A-Za-z0-9+/]{20,}={0,2}', '<REDACTED_BASE64>', text)
    return text


@dataclass
class SynapticCandidate:
    category: str  # preference | correction | decision | negative | fact | lesson
    content: str
    confidence: float
    source_message: str


class SynapticExtractor:
    """Deterministic extractor for conversation insights. No LLM dependency."""

    def extract(self, user_message: str, trust_level: str = "untrusted") -> list:
        """Extract synaptic candidates from a user message."""
        candidates = []
        msg = user_message.strip()

        # Skip trivial messages
        if msg.lower() in TRIVIAL_MESSAGES or len(msg) < 10:
            return []

        # Skip if contains secrets
        for sp in SECRET_PATTERNS:
            if sp.search(msg):
                logger.warning("SynapticExtractor: skipping message with potential secret content")
                return []

        # For untrusted: no extraction
        policy = _get_memory_policy(trust_level)
        if policy in (MEMORY_POLICY_NONE, MEMORY_POLICY_MINIMAL):
            return []

        # Extract patterns
        for pattern in PREFERENCE_PATTERNS:
            if pattern.search(msg):
                candidates.append(SynapticCandidate("preference", msg[:200], 0.8, msg))
                break

        for pattern in CORRECTION_PATTERNS:
            if pattern.search(msg):
                candidates.append(SynapticCandidate("correction", msg[:200], 0.9, msg))
                break

        for pattern in DECISION_PATTERNS:
            if pattern.search(msg):
                candidates.append(SynapticCandidate("decision", msg[:200], 0.85, msg))
                break

        for pattern in NEGATIVE_PATTERNS:
            if pattern.search(msg):
                candidates.append(SynapticCandidate("negative", msg[:200], 0.95, msg))
                break

        if policy == MEMORY_POLICY_FULL:
            for pattern in FACT_PATTERNS:
                if pattern.search(msg):
                    candidates.append(SynapticCandidate("fact", msg[:200], 0.7, msg))
                    break

        return candidates


# ---------------------------------------------------------------------------
# ConversationMemoryStore
# ---------------------------------------------------------------------------

class ConversationMemoryStore:
    """Persists ConversationEpisode to LongTermMemory and optionally MemoryGraph."""

    def __init__(self, project_root: str | Path | None = None):
        self.project_root = Path(project_root or Path.home())
        self._extractor = SynapticExtractor()

    def persist(self, episode: ConversationEpisode) -> bool:
        """Persist an episode. Returns True if successful, False if degraded."""
        if episode.memory_policy == MEMORY_POLICY_NONE:
            return True  # nothing to persist

        try:
            from igris.core.long_term_memory import LongTermMemory
            ltm = LongTermMemory(base_path=self.project_root / ".igris" / "memory" / "long_term")

            # Build domain based on interlocutor
            domain = "conversation"
            if episode.interlocutor_id and episode.interlocutor_id != "unknown":
                domain = f"chat:{episode.interlocutor_id}"

            # Redact sensitive values before storage
            _safe_user = _redact_for_storage(episode.user_message or "")
            _safe_response = _redact_for_storage(episode.assistant_response or "")

            # Prepare content — minimal for untrusted
            if episode.memory_policy == MEMORY_POLICY_MINIMAL:
                content = {
                    "summary": (
                        f"[{episode.intent_action}/{episode.intent_risk}] "
                        f"auth={episode.auth_decision} blocked={episode.blocked}"
                    ),
                    "episode_id": episode.episode_id,
                    "interlocutor_id": episode.interlocutor_id,
                    "trust_level": episode.trust_level,
                    "intent_action": episode.intent_action,
                    "blocked": episode.blocked,
                    "timestamp": episode.timestamp,
                    "source": "chat",
                    "memory_policy": episode.memory_policy,
                }
            else:
                content = {
                    "user_message": _safe_user[:300],
                    "assistant_response": _safe_response[:300],
                    "intent_action": episode.intent_action,
                    "intent_risk": episode.intent_risk,
                    "auth_decision": episode.auth_decision,
                    "episode_id": episode.episode_id,
                    "session_id": episode.session_id,
                    "interlocutor_id": episode.interlocutor_id,
                    "trust_level": episode.trust_level,
                    "blocked": episode.blocked,
                    "timestamp": episode.timestamp,
                    "source": "chat",
                    "memory_policy": episode.memory_policy,
                }

            ltm.add_entry(
                domain=domain,
                content=content,
                source=episode.source,
                tags=episode.tags or [],
                importance=episode.importance,
            )

            # Synaptic extraction (best-effort, only for trusted+)
            if episode.memory_policy in (MEMORY_POLICY_FULL, MEMORY_POLICY_SCOPED):
                candidates = self._extractor.extract(episode.user_message, episode.trust_level)
                for candidate in candidates:
                    ltm.add_entry(
                        domain=f"synaptic:{episode.interlocutor_id}",
                        content={
                            "text": _redact_for_storage(candidate.content),
                            "category": candidate.category,
                            "confidence": candidate.confidence,
                            "source": "synaptic_extraction",
                        },
                        source="synaptic_extraction",
                        tags=[candidate.category],
                        importance=candidate.confidence,
                    )

            # Best-effort MemoryGraph integration
            self._persist_to_memory_graph(episode)

            # Best-effort rolling summary update
            try:
                _summary_mgr = ConversationSummaryManager(self.project_root)
                _summary_mgr.update_summary(episode.interlocutor_id, episode.trust_level, episode)
            except Exception as _sum_exc:
                logger.debug("Summary update skipped: %s", _sum_exc)

            return True
        except Exception as e:
            logger.warning("ConversationMemoryStore: persist failed (degraded): %s", e)
            return False

    def _persist_to_memory_graph(self, episode: ConversationEpisode) -> None:
        """Best-effort MemoryGraph integration."""
        try:
            from igris.core.memory_graph import MemoryGraph
            mg = MemoryGraph(str(self.project_root))
            mg.add_node(
                node_type="lesson",
                content={
                    "text": f"chat turn: {episode.intent_action} / {episode.trust_level}",
                    "episode_id": episode.episode_id,
                    "interlocutor_id": episode.interlocutor_id,
                },
            )
        except Exception as e:
            logger.debug("MemoryGraph integration skipped: %s", e)


# ---------------------------------------------------------------------------
# ConversationRetriever
# ---------------------------------------------------------------------------

MAX_RETRIEVAL_TOKENS = 800  # approximate limit


class ConversationRetriever:
    """Retrieves relevant conversation memory for context injection."""

    def __init__(self, project_root: str | Path | None = None):
        self.project_root = Path(project_root or Path.home())

    def retrieve_for_context(self, interlocutor_id: str, trust_level: str, limit: int = 5) -> str:
        """Retrieve relevant memory for the current interlocutor.

        Returns a compact text suitable for system prompt injection.
        Unknown/untrusted interlocutors get no sensitive memory.
        """
        policy = _get_memory_policy(trust_level)

        if policy in (MEMORY_POLICY_NONE, MEMORY_POLICY_MINIMAL):
            return ""  # no memory for untrusted

        try:
            from igris.core.long_term_memory import LongTermMemory
            ltm = LongTermMemory(base_path=self.project_root / ".igris" / "memory" / "long_term")

            synaptic_domain = f"synaptic:{interlocutor_id}"
            results = []

            # Get synaptic preferences/decisions (most useful)
            try:
                entries = ltm.get_entries(synaptic_domain, limit=limit)
                if entries:
                    results.append("**Conversational context:**")
                    for entry in entries[:3]:
                        content = entry.content
                        if isinstance(content, dict):
                            text = content.get("text", str(content))
                        else:
                            text = str(content)
                        if len(text) > 150:
                            text = text[:150] + "..."
                        results.append(f"- {text}")
            except Exception:
                pass

            if not results:
                return ""

            text = "\n".join(results)
            # Limit size
            if len(text) > MAX_RETRIEVAL_TOKENS * 4:
                text = text[:MAX_RETRIEVAL_TOKENS * 4] + "..."

            return f"\n[MEMORY CONTEXT]\n{text}\n"

        except Exception as e:
            logger.debug("ConversationRetriever: retrieval failed: %s", e)
            return ""

    def get_recent_episodes_safe(self, interlocutor_id: str, trust_level: str, limit: int = 10) -> list:
        """Get recent episodes for API consumption — no secrets."""
        policy = _get_memory_policy(trust_level)
        if policy == MEMORY_POLICY_MINIMAL:
            return []

        try:
            from igris.core.long_term_memory import LongTermMemory
            ltm = LongTermMemory(base_path=self.project_root / ".igris" / "memory" / "long_term")
            domain = f"chat:{interlocutor_id}"
            entries = ltm.get_entries(domain, limit=limit)
            safe = []
            for entry in (entries or []):
                meta = entry.content if isinstance(entry.content, dict) else {}
                safe.append({
                    "episode_id": meta.get("episode_id", ""),
                    "interlocutor_id": meta.get("interlocutor_id", interlocutor_id),
                    "intent_action": meta.get("intent_action", ""),
                    "blocked": meta.get("blocked", False),
                    "timestamp": meta.get("timestamp", entry.timestamp),
                })
            return safe
        except Exception as e:
            logger.debug("get_recent_episodes_safe failed: %s", e)
            return []


# ---------------------------------------------------------------------------
# ConversationSummaryManager
# ---------------------------------------------------------------------------

class ConversationSummaryManager:
    """Rolling summary for session and interlocutor."""

    def __init__(self, project_root: str | Path | None = None):
        self.project_root = Path(project_root or Path.home())

    def get_summary(self, interlocutor_id: str, trust_level: str) -> str | None:
        """Get current summary for this interlocutor."""
        policy = _get_memory_policy(trust_level)
        if policy == MEMORY_POLICY_MINIMAL:
            return None
        try:
            from igris.core.long_term_memory import LongTermMemory
            ltm = LongTermMemory(base_path=self.project_root / ".igris" / "memory" / "long_term")
            domain = f"summary:{interlocutor_id}"
            entries = ltm.get_entries(domain, limit=1)
            if entries:
                content = entries[0].content
                if isinstance(content, dict):
                    return content.get("text", str(content))
                return str(content)
        except Exception as e:
            logger.debug("Summary retrieval failed: %s", e)
        return None

    def update_summary(self, interlocutor_id: str, trust_level: str, episode: "ConversationEpisode") -> bool:
        """Update rolling summary for this interlocutor.

        Only for trusted/scoped/full policy — not for minimal/unknown.
        Returns True if updated, False if skipped or failed.
        """
        policy = _get_memory_policy(trust_level)
        if policy == MEMORY_POLICY_MINIMAL:
            return False  # no summary for unknown/untrusted

        try:
            from igris.core.long_term_memory import LongTermMemory
            ltm = LongTermMemory(base_path=self.project_root / ".igris" / "memory" / "long_term")
            domain = f"summary:{interlocutor_id}"

            # Build summary text from episode
            summary_text = (
                f"[{episode.intent_action}/{episode.trust_level}] "
                f"auth={episode.auth_decision} blocked={episode.blocked}"
            )
            if policy == MEMORY_POLICY_FULL and episode.user_message:
                summary_text = f"User: {_redact_for_storage(episode.user_message[:100])} | {summary_text}"

            ltm.add_entry(
                domain=domain,
                content={"text": summary_text, "interlocutor_id": interlocutor_id, "trust_level": trust_level},
                source="conversation_summary",
                tags=["summary"],
                importance=0.6,
            )
            return True
        except Exception as e:
            logger.warning("ConversationSummaryManager.update_summary failed (degraded): %s", e)
            return False
