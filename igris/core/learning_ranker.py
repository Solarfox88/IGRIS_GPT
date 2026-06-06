"""Learning Ranker — shadow-mode memory ranking with heuristic/feedback scoring (#1248).

SAFE BY DEFAULT:
- shadow_only=True: ranking is evaluative only, never replaces real retrieval order
- changed_decision=False always
- Works with empty dataset (heuristic fallback)
- No external ML dependencies
"""
from __future__ import annotations

import logging
import math
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Secret redaction ──────────────────────────────────────────────────────────

_SECRET_RE = re.compile(
    r'(token|passphrase|password|secret|api[_\s]?key|private[_\s]?key|bearer|auth[_\s]?key)'
    r'\s*[=:]\s*\S+',
    re.IGNORECASE,
)

def _redact(text: str) -> str:
    return _SECRET_RE.sub(r'\1=<REDACTED>', str(text)) if text else text

def _redact_any(val: Any) -> Any:
    if isinstance(val, dict):
        return {k: _redact_any(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [_redact_any(i) for i in val]
    elif isinstance(val, str):
        return _redact(val)
    return val


# Re-use ShadowScore / ShadowReport / ShadowDecisionSource from shadow_ml
from igris.core.shadow_ml import ShadowScore, ShadowReport, ShadowDecisionSource

# ── Source/kind weights ───────────────────────────────────────────────────────

_SOURCE_WEIGHTS: dict[str, float] = {
    "lesson": 1.0,
    "correction": 0.95,
    "decision": 0.9,
    "world_state_snapshot": 0.85,
    "capability": 0.8,
    "run_event": 0.6,
    "project_fact": 0.7,
    "memory_feedback": 0.75,
    "preference": 0.85,
    "fact": 0.65,
    "episode": 0.6,
}

_DEFAULT_SOURCE_WEIGHT = 0.5


def _source_weight(source: str) -> float:
    return _SOURCE_WEIGHTS.get(source.lower(), _DEFAULT_SOURCE_WEIGHT)


def _keyword_overlap(query: str, text: str) -> float:
    """Normalised keyword overlap [0, 1]."""
    if not query or not text:
        return 0.0
    q_words = set(re.findall(r'\w+', query.lower()))
    t_words = set(re.findall(r'\w+', text.lower()))
    if not q_words:
        return 0.0
    overlap = len(q_words & t_words)
    return min(1.0, overlap / len(q_words))


def _recency_score(metadata: dict) -> float:
    """Return [0, 1] from stored_at timestamp if available, else 0.5."""
    import time
    stored_at = metadata.get("stored_at") or metadata.get("created_at")
    if not stored_at:
        return 0.5
    try:
        age_seconds = time.time() - float(stored_at)
        half_life = 14 * 24 * 3600  # 14 days
        return math.exp(-math.log(2) * age_seconds / half_life)
    except Exception:
        return 0.5


# ── LearningRanker ────────────────────────────────────────────────────────────

class LearningRanker:
    """Shadow-mode ranking of memory items.

    Produces ShadowReport with ranked ShadowScores.
    NEVER changes operational retrieval order.
    shadow_only=True, changed_decision=False always.
    """

    def __init__(
        self,
        project_root: "str | Path | None" = None,
        unified_memory: Any = None,
    ):
        if project_root is None:
            try:
                from igris.models.config import CONFIG
                project_root = CONFIG.project_root
            except Exception:
                project_root = Path.home()
        self.project_root = Path(project_root)
        self._memory = unified_memory
        self._feedback_cache: dict | None = None

    def load_feedback_stats(self) -> dict[str, Any]:
        """Load per-item feedback statistics from UnifiedMemory if available."""
        mem = self._memory
        if mem is None:
            try:
                from igris.core.unified_memory import UnifiedMemory
                mem = UnifiedMemory(project_root=self.project_root)
                self._memory = mem
            except Exception as e:
                logger.debug("LearningRanker: UnifiedMemory unavailable: %s", e)
                return {}

        try:
            # Try to read feedback records from long-term memory
            if hasattr(mem, "_ltm") and mem._ltm is not None:
                ltm = mem._ltm
                if hasattr(ltm, "search"):
                    results = ltm.search("feedback outcome success", limit=200)
                    stats: dict[str, Any] = {}
                    for r in results or []:
                        mid = getattr(r, "id", None) or r.get("id", "") if isinstance(r, dict) else ""
                        helpful = getattr(r, "helpful", None) if not isinstance(r, dict) else r.get("helpful")
                        outcome = getattr(r, "outcome", None) if not isinstance(r, dict) else r.get("outcome")
                        if mid:
                            stats[mid] = {
                                "helpful": helpful,
                                "outcome": outcome,
                                "helpful_rate": 1.0 if helpful else 0.0,
                                "success_rate": 1.0 if outcome == "success" else 0.0,
                            }
                    return stats
        except Exception as e:
            logger.debug("LearningRanker.load_feedback_stats failed: %s", e)
        return {}

    def score_item(
        self,
        query: str,
        item: dict[str, Any],
        *,
        feedback_stats: dict[str, Any] | None = None,
    ) -> ShadowScore:
        """Score a single item against a query. Purely shadow/evaluative."""
        item_id = str(item.get("id", item.get("signal_id", str(uuid.uuid4())[:8])))
        text = str(item.get("text", item.get("summary", item.get("content", ""))))
        source = str(item.get("source", item.get("kind", "unknown")))
        confidence = float(item.get("confidence", item.get("score", 0.5)))
        importance = float(item.get("importance", item.get("score", 0.5)))
        metadata = item.get("metadata", {}) or {}
        project = str(item.get("project", ""))
        route = str(item.get("route", ""))

        features: dict[str, float] = {}

        # Signal 1: keyword overlap
        kw = _keyword_overlap(query, text)
        features["keyword_overlap"] = kw

        # Signal 2: source weight
        sw = _source_weight(source)
        features["source_weight"] = sw

        # Signal 3: item confidence/importance
        features["item_confidence"] = confidence
        features["item_importance"] = importance

        # Signal 4: recency
        rec = _recency_score(metadata)
        features["recency"] = rec

        # Signal 5: feedback stats
        helpful_rate = 0.5
        success_rate = 0.5
        fb_source = ShadowDecisionSource.HEURISTIC.value
        warnings_list: list[str] = []

        if feedback_stats and item_id in feedback_stats:
            fb = feedback_stats[item_id]
            helpful_rate = float(fb.get("helpful_rate", 0.5))
            success_rate = float(fb.get("success_rate", 0.5))
            fb_source = ShadowDecisionSource.MEMORY_FEEDBACK.value
        else:
            warnings_list.append("insufficient_feedback_data")

        features["helpful_rate"] = helpful_rate
        features["success_rate"] = success_rate

        # Signal 6: project/route match bonus
        query_lower = query.lower()
        project_match = 1.0 if project and project.lower() in query_lower else 0.5
        route_match = 1.0 if route and route.lower() in query_lower else 0.5
        features["project_match"] = project_match
        features["route_match"] = route_match

        # Weighted composite score
        score = (
            0.25 * kw +
            0.15 * sw +
            0.15 * confidence +
            0.10 * importance +
            0.10 * rec +
            0.10 * helpful_rate +
            0.10 * success_rate +
            0.05 * project_match +
            0.05 * route_match
        )
        score = max(0.0, min(1.0, score))

        score_confidence = 0.7 if fb_source == ShadowDecisionSource.MEMORY_FEEDBACK.value else 0.4

        return ShadowScore(
            item_id=item_id,
            score=round(score, 4),
            confidence=score_confidence,
            reason=_redact(f"kw={kw:.2f} src_w={sw:.2f} conf={confidence:.2f} rec={rec:.2f}"),
            source=fb_source,
            features=features,
            warnings=warnings_list,
        )

    def rank_items(
        self,
        query: str,
        items: "list[dict[str, Any]]",
        *,
        context: "dict[str, Any] | None" = None,
        shadow_only: bool = True,
        limit: "int | None" = None,
    ) -> ShadowReport:
        """Rank items in shadow mode. Returns ShadowReport, never modifies items."""
        report = ShadowReport(
            report_id=str(uuid.uuid4()),
            kind="learning_ranker",
            query=_redact(str(query)[:500]),
            shadow_only=True,
            changed_decision=False,
        )

        if not items:
            report.metrics = {
                "dataset_size": 0,
                "feedback_count": 0,
                "coverage": 0.0,
                "heuristic_fallback": True,
            }
            report.warnings.append("empty_items_list")
            report.ok = True
            return report

        try:
            feedback_stats = self.load_feedback_stats()
            feedback_count = len(feedback_stats)

            scored: list[ShadowScore] = []
            all_warnings: set[str] = set()

            for item in items:
                try:
                    ss = self.score_item(query, item, feedback_stats=feedback_stats)
                    scored.append(ss)
                    all_warnings.update(ss.warnings)
                except Exception as e:
                    logger.warning("LearningRanker.score_item failed: %s", e)
                    all_warnings.add(f"score_failed: {_redact(str(e))}")

            # Sort descending by score
            scored.sort(key=lambda s: s.score, reverse=True)

            # Apply limit
            if limit is not None and limit > 0:
                scored = scored[:limit]

            covered = sum(1 for s in scored if s.source == ShadowDecisionSource.MEMORY_FEEDBACK.value)
            coverage = covered / len(scored) if scored else 0.0
            heuristic_fallback = feedback_count == 0

            report.scores = scored
            report.metrics = {
                "dataset_size": len(items),
                "feedback_count": feedback_count,
                "coverage": round(coverage, 3),
                "heuristic_fallback": heuristic_fallback,
                "scored_count": len(scored),
            }
            report.warnings = list(all_warnings)
            if heuristic_fallback and "insufficient_feedback_data" not in report.warnings:
                report.warnings.append("insufficient_feedback_data")
            report.changed_decision = False
            report.ok = True

        except Exception as e:
            logger.warning("LearningRanker.rank_items failed: %s", e)
            report.ok = False
            report.warnings.append(f"ranking_failed: {_redact(str(e))}")

        return report

    def healthcheck(self) -> dict:
        mem_status = "unavailable"
        try:
            mem = self._memory
            if mem is None:
                from igris.core.unified_memory import UnifiedMemory
                mem = UnifiedMemory(project_root=self.project_root)
            mem_status = "ok" if mem else "unavailable"
        except Exception as e:
            logger.warning("LearningRanker.healthcheck: UnifiedMemory unavailable: %s", e)
            return {"ok": False, "unified_memory": "unavailable", "error": str(e)}
        return {"ok": True, "unified_memory": mem_status}
