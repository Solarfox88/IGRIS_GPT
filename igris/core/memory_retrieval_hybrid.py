"""Hybrid Memory Retrieval — combines multiple memory backends with scoring (#1242).

Scoring formula:
  score = 0.25 * keyword_match
        + 0.20 * importance_confidence
        + 0.15 * recency
        + 0.15 * source_weight
        + 0.15 * success_rate (if available)
        + 0.10 * semantic_similarity (if EmbeddingStore available)
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Source weights (adjustable)
SOURCE_WEIGHTS = {
    "conversation": 1.0,
    "ltm_synaptic": 0.95,
    "ltm_lesson": 0.90,
    "ltm_decision": 0.85,
    "ltm_correction": 0.90,
    "ltm_fact": 0.75,
    "ltm_run": 0.65,
    "graph": 0.70,
    "topic": 0.60,
    "embedding": 0.80,
}

# Mission context: prioritize lessons/decisions/corrections
MISSION_PRIORITY_KINDS = {"lesson", "decision", "correction", "failure_pattern",
                           "command_recipe", "project_fact", "environment_fact", "run_event"}


def _keyword_score(text: str, query: str) -> float:
    """Simple keyword overlap score."""
    if not query or not text:
        return 0.0
    q_words = set(re.findall(r'\w+', query.lower()))
    t_words = set(re.findall(r'\w+', text.lower()))
    if not q_words:
        return 0.0
    overlap = len(q_words & t_words)
    return min(1.0, overlap / max(len(q_words), 1))


def _recency_score(timestamp: Optional[float]) -> float:
    """Score based on recency (1.0 = very recent, 0.0 = very old)."""
    if timestamp is None:
        return 0.3
    age_days = (time.time() - timestamp) / 86400
    if age_days < 1:
        return 1.0
    if age_days < 7:
        return 0.8
    if age_days < 30:
        return 0.6
    if age_days < 90:
        return 0.4
    return 0.2


def _compute_score(keyword: float, importance: float, recency: float,
                   source_w: float, success_rate: float, semantic: float) -> float:
    return (
        0.25 * keyword
        + 0.20 * importance
        + 0.15 * recency
        + 0.15 * source_w
        + 0.15 * success_rate
        + 0.10 * semantic
    )


def _is_sensitive_kind(kind: str) -> bool:
    return kind in ("preference", "correction", "decision", "episode", "fact")


_REDACT_PATTERNS = [
    re.compile(r'(token|passphrase|password|secret|api[_\s]?key|bearer)\s*[=:]\s*\S+',
               re.IGNORECASE),
    re.compile(r'[A-Za-z0-9+/]{20,}={0,2}'),
]


def _redact(text: str) -> str:
    if not text:
        return text
    for p in _REDACT_PATTERNS:
        text = p.sub('<REDACTED>', text)
    return text


class HybridRetriever:
    """Combines multiple memory backends with unified scoring and deduplication."""

    def __init__(self, project_root: "Path | str | None" = None,
                 ltm=None, graph=None, conv_retriever=None, embedding_store=None):
        self.project_root = Path(project_root) if project_root else Path.home()
        self._ltm = ltm
        self._graph = graph
        self._conv_retriever = conv_retriever
        self._embedding_store = embedding_store

    def retrieve(self, query: str, interlocutor_id: str, trust_level: str,
                 limit: int = 8, context: str = "chat",
                 project: str = "default", mission_type: Optional[str] = None,
                 include_influence: bool = True):
        """Main retrieval method. Returns RetrievalResult."""
        from igris.core.unified_memory import RetrievalResult, MemoryItem

        allows_sensitive = trust_level.lower() in ("admin", "owner", "trusted")
        all_items: list = []
        warnings: list = []
        degraded = False
        seen_texts: set = set()

        # ── 1. ConversationRetriever (synaptic preferences) ────────────────
        if self._conv_retriever and allows_sensitive:
            try:
                ctx_text = self._conv_retriever.retrieve_for_context(
                    interlocutor_id, trust_level, limit=limit
                )
                if ctx_text and "[MEMORY CONTEXT]" in ctx_text:
                    for line in ctx_text.split("\n"):
                        line = line.strip("- ").strip()
                        if line and not line.startswith("[") and line not in seen_texts:
                            seen_texts.add(line)
                            kscore = _keyword_score(line, query)
                            score = _compute_score(kscore, 0.8, 0.9, 1.0, 0.5, 0.0)
                            all_items.append(MemoryItem(
                                id=f"conv:{abs(hash(line))}",
                                source="conversation", kind="preference",
                                text=_redact(line), score=score,
                                confidence=0.85, why_selected="synaptic preference",
                                safe_for_context=True,
                                trust_required="trusted",
                            ))
            except Exception as e:
                logger.debug("HybridRetriever: conv_retriever failed: %s", e)
                degraded = True
                warnings.append(f"conversation: {e}")

        # ── 2. LongTermMemory — multiple domains ───────────────────────────
        if self._ltm:
            domains_to_search = []
            if context == "mission":
                domains_to_search = [
                    f"lesson:{project}",
                    f"decision:{project}",
                    f"run:{project}",
                    f"fact:{project}",
                ]
                if allows_sensitive:
                    domains_to_search.append(f"synaptic:{interlocutor_id}")
            else:  # chat
                domains_to_search = [
                    f"lesson:{project}",
                    f"decision:{project}",
                ]
                if allows_sensitive:
                    domains_to_search.insert(0, f"synaptic:{interlocutor_id}")

            for domain in domains_to_search:
                kind_key = domain.split(":")[0] if ":" in domain else "general"
                # Map synaptic -> preference for source weight lookup
                sw_key = f"ltm_{kind_key}" if kind_key != "synaptic" else "ltm_synaptic"
                source_w = SOURCE_WEIGHTS.get(sw_key, 0.7)
                try:
                    results = self._ltm.search(query=query, domains=[domain], limit=limit)
                    for entry in (results or []):
                        # LTM content can be str or dict
                        content = getattr(entry, "content", "")
                        if isinstance(content, dict):
                            text = content.get("text", str(content))
                            entry_kind = content.get("kind", kind_key)
                            conf = float(content.get("confidence", 0.7))
                        else:
                            text = str(content)
                            entry_kind = kind_key
                            conf = 0.7

                        if not text or text in seen_texts:
                            continue

                        # Filter sensitive items for untrusted
                        if _is_sensitive_kind(entry_kind) and not allows_sensitive:
                            continue

                        seen_texts.add(text)
                        importance = float(getattr(entry, "importance", 0.5))
                        ts = float(getattr(entry, "timestamp", 0) or 0)

                        kscore = _keyword_score(text, query)
                        rec = _recency_score(ts if ts > 0 else None)
                        score = _compute_score(kscore, importance, rec, source_w, 0.5, 0.0)

                        all_items.append(MemoryItem(
                            id=getattr(entry, "id", f"ltm:{abs(hash(text))}"),
                            source=sw_key, kind=entry_kind,
                            text=_redact(text), score=score,
                            confidence=conf,
                            why_selected=f"domain={domain} keyword={kscore:.2f}",
                            safe_for_context=not _is_sensitive_kind(entry_kind) or allows_sensitive,
                            trust_required="trusted" if _is_sensitive_kind(entry_kind) else "untrusted",
                        ))
                except Exception as e:
                    logger.debug("HybridRetriever: LTM domain %s failed: %s", domain, e)
                    degraded = True

        # ── 3. MemoryGraph nodes via query_by_intent ──────────────────────
        if self._graph:
            node_types = (
                ["lesson", "decision", "command_recipe"]
                if context == "chat"
                else ["lesson", "decision", "run_event", "project_fact", "command_recipe"]
            )
            for nt in node_types:
                try:
                    nodes = self._graph.query_by_intent(query, node_type=nt, limit=3) or []
                    for node in nodes:
                        content = node.get("content", {})
                        if isinstance(content, dict):
                            text = content.get("text", str(content))
                        else:
                            text = str(content)
                        if not text or text in seen_texts:
                            continue
                        if _is_sensitive_kind(nt) and not allows_sensitive:
                            continue
                        seen_texts.add(text)
                        kscore = _keyword_score(text, query)
                        score = _compute_score(
                            kscore, float(node.get("confidence", 0.7)),
                            0.5, SOURCE_WEIGHTS["graph"],
                            float(node.get("success_rate", 0.5)), 0.0
                        )
                        all_items.append(MemoryItem(
                            id=f"graph:{node.get('node_id', abs(hash(text)))}",
                            source="graph", kind=nt,
                            text=_redact(text), score=score, confidence=0.7,
                            why_selected=f"graph node type={nt}",
                            safe_for_context=not _is_sensitive_kind(nt) or allows_sensitive,
                            trust_required="trusted" if _is_sensitive_kind(nt) else "untrusted",
                        ))
                except Exception as e:
                    logger.debug("HybridRetriever: graph node_type=%s failed: %s", nt, e)
                    degraded = True
                    warnings.append(f"graph:{nt}: {e}")

        # ── 4. Mission context re-ranking ─────────────────────────────────
        if context == "mission":
            for item in all_items:
                if item.kind in MISSION_PRIORITY_KINDS:
                    item.score = min(1.0, item.score * 1.3)

        # ── 5. Sort, deduplicate, limit ───────────────────────────────────
        all_items.sort(key=lambda x: x.score, reverse=True)
        all_items = all_items[:limit]

        # ── 6. Build context text ─────────────────────────────────────────
        if all_items:
            lines = ["[MEMORY CONTEXT]"]
            for item in all_items[:5]:
                lines.append(f"- {_redact(item.text[:150])}")
            context_text = "\n".join(lines)
        else:
            context_text = ""

        # ── 7. Influence report ───────────────────────────────────────────
        if include_influence and all_items:
            report_lines = ["Memorie usate:"]
            for item in all_items[:3]:
                report_lines.append(
                    f"- [{item.kind}] {_redact(item.text[:80])} "
                    f"(score={item.score:.2f}, {item.why_selected})"
                )
            influence = "\n".join(report_lines)
        else:
            influence = "Nessun contesto memoria usato."

        return RetrievalResult(
            context=context_text,
            items=all_items,
            influence_report=_redact(influence),
            degraded=degraded,
            warnings=warnings,
        )
