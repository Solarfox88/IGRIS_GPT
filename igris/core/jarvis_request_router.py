"""Jarvis Request Router — classifies and routes chat/API requests (#1243).

The router is the central decision point that transforms a user request
into a structured route decision. It does NOT execute actions directly.

Routes:
  chat_only                  — conversational answer, no operation
  memory_update              — store preference/correction/decision
  read_only_inspection       — inspect state/logs/reports (non-mutating)
  project_reasoning          — analyze, plan, evaluate architecture
  code_change                — modify code, fix bugs, create PR
  server_operation           — server management (restart, config, etc.)
  github_operation           — GitHub issues/PRs/branches
  deploy_operation           — deploy, rollback, release
  high_risk_operation        — destructive/irreversible actions
  unknown_requires_clarification — ambiguous, missing target
  blocked                    — denied by security/trust policy
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Enums ─────────────────────────────────────────────────────────────────────

class RequestRoute(str, Enum):
    CHAT_ONLY = "chat_only"
    MEMORY_UPDATE = "memory_update"
    READ_ONLY_INSPECTION = "read_only_inspection"
    PROJECT_REASONING = "project_reasoning"
    CODE_CHANGE = "code_change"
    SERVER_OPERATION = "server_operation"
    GITHUB_OPERATION = "github_operation"
    DEPLOY_OPERATION = "deploy_operation"
    HIGH_RISK_OPERATION = "high_risk_operation"
    UNKNOWN_REQUIRES_CLARIFICATION = "unknown_requires_clarification"
    BLOCKED = "blocked"


class RequestRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    DESTRUCTIVE = "destructive"
    UNKNOWN = "unknown"


# ── Route Decision ─────────────────────────────────────────────────────────────

@dataclass
class JarvisRouteDecision:
    route: str
    risk: str
    intent_action: str = ""
    blocked: bool = False
    requires_clarification: bool = False
    requires_approval: bool = False
    memory_mode: str = "retrieve"   # retrieve | store | none
    mission_required: bool = False
    reasoning_required: bool = False
    target_resource: str = ""
    confidence: float = 0.0
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "route": self.route,
            "risk": self.risk,
            "intent_action": self.intent_action,
            "blocked": self.blocked,
            "requires_clarification": self.requires_clarification,
            "requires_approval": self.requires_approval,
            "memory_mode": self.memory_mode,
            "mission_required": self.mission_required,
            "reasoning_required": self.reasoning_required,
            "target_resource": self.target_resource,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "warnings": self.warnings,
        }

    @property
    def is_safe(self) -> bool:
        return not self.blocked and self.risk in (RequestRisk.LOW, RequestRisk.MEDIUM)

    @property
    def needs_human(self) -> bool:
        return self.blocked or self.requires_clarification or self.requires_approval


# ── Classification Engine ──────────────────────────────────────────────────────

# Trust levels that allow sensitive operations
_TRUSTED_LEVELS = {"admin", "owner", "trusted"}
_UNTRUSTED_LEVELS = {"untrusted", "unknown", ""}

# Pattern sets — (pattern, route, risk, memory_mode, mission_required)
_CLASSIFICATION_RULES: list[tuple[re.Pattern, str, str, str, bool]] = [
    # ── MEMORY UPDATE ───────────────────────────────────────────────────────
    # Italian
    (re.compile(r'\b(ricordati|tieni a mente|salva questa|salva questa preferenza|preferisco|non voglio più|non usare più|questa correzione|da ora in poi|correggi la memoria)\b', re.I),
     RequestRoute.MEMORY_UPDATE, RequestRisk.LOW, "store", False),
    # English
    (re.compile(r'\b(remember that|save this preference|from now on|i prefer|don\'t use|correct your memory|update your memory)\b', re.I),
     RequestRoute.MEMORY_UPDATE, RequestRisk.LOW, "store", False),

    # ── HIGH RISK / DESTRUCTIVE ─────────────────────────────────────────────
    # Italian destructive
    (re.compile(r'\b(cancella|elimina|rimuovi|distruggi|svuota|resetta|formatta|azzera|wipe)\b.{0,40}\b(database|db|produzione|server|tutti i file|volume|backup|tutto)\b', re.I),
     RequestRoute.HIGH_RISK_OPERATION, RequestRisk.DESTRUCTIVE, "none", True),
    (re.compile(r'\b(drop|truncate|purge|delete all|remove all|destroy|wipe)\b.{0,40}\b(database|db|prod|server|volume|everything)\b', re.I),
     RequestRoute.HIGH_RISK_OPERATION, RequestRisk.DESTRUCTIVE, "none", True),
    # General destructive Italian verbs
    (re.compile(r'\b(cancella|elimina|distruggi)\b', re.I),
     RequestRoute.HIGH_RISK_OPERATION, RequestRisk.HIGH, "none", True),

    # ── DEPLOY ──────────────────────────────────────────────────────────────
    (re.compile(r'\b(fai deploy|esegui deploy|deploy in produzione|pubblica in prod|rilascia|rollback|deploy|torna indietro|revert)\b', re.I),
     RequestRoute.DEPLOY_OPERATION, RequestRisk.HIGH, "none", True),
    (re.compile(r'\b(deploy|rollback|release to prod|push to production)\b', re.I),
     RequestRoute.DEPLOY_OPERATION, RequestRisk.HIGH, "none", True),

    # ── SERVER OPERATION ────────────────────────────────────────────────────
    (re.compile(r'\b(riavvia|spegni|shutdown|reboot|restart)\b.{0,30}\b(server|servizio|nginx|vps|servizi|istanza)\b', re.I),
     RequestRoute.SERVER_OPERATION, RequestRisk.HIGH, "none", True),
    (re.compile(r'\b(restart|reboot|shutdown)\b.{0,30}\b(server|service|nginx|vps|instance)\b', re.I),
     RequestRoute.SERVER_OPERATION, RequestRisk.HIGH, "none", True),

    # ── GITHUB OPERATION ────────────────────────────────────────────────────
    (re.compile(r'\b(chiudi|riapri|close|reopen)\b.{0,20}\b(issue|ticket|bug)\b', re.I),
     RequestRoute.GITHUB_OPERATION, RequestRisk.MEDIUM, "none", True),
    (re.compile(r'\b(mergia|unisci|approva|merge|approve)\b.{0,20}\b(pr|pull request|branch)\b', re.I),
     RequestRoute.GITHUB_OPERATION, RequestRisk.HIGH, "none", True),
    (re.compile(r'\b(crea branch|crea pr|crea pull request|apri pr|open pr|create branch|create pr)\b', re.I),
     RequestRoute.GITHUB_OPERATION, RequestRisk.MEDIUM, "none", True),
    (re.compile(r'\b(aggiungi label|commenta issue|assegna|add label|comment on issue|assign)\b', re.I),
     RequestRoute.GITHUB_OPERATION, RequestRisk.LOW, "none", True),

    # ── CODE CHANGE ─────────────────────────────────────────────────────────
    (re.compile(r'\b(modifica|aggiorna|implementa|fixa|correggi il codice|crea una pr|committa)\b', re.I),
     RequestRoute.CODE_CHANGE, RequestRisk.MEDIUM, "retrieve", True),
    (re.compile(r'\b(fix|implement|modify|update|change|refactor|create pr|commit)\b.{0,40}\b(code|file|function|class|module|test)\b', re.I),
     RequestRoute.CODE_CHANGE, RequestRisk.MEDIUM, "retrieve", True),

    # ── READ ONLY INSPECTION ────────────────────────────────────────────────
    (re.compile(r'\b(controlla|verifica|leggi|mostra|analizza|dai un\'?occhiata|guarda i log|stato|report|diagnostica)\b', re.I),
     RequestRoute.READ_ONLY_INSPECTION, RequestRisk.LOW, "retrieve", True),
    (re.compile(r'\b(check|verify|read|show|display|inspect|look at|analyze|status|report|diagnose|review)\b.{0,40}\b(log|report|state|status|error|output|result)\b', re.I),
     RequestRoute.READ_ONLY_INSPECTION, RequestRisk.LOW, "retrieve", True),

    # ── PROJECT REASONING ───────────────────────────────────────────────────
    (re.compile(r'\b(ragiona|valuta|analizza|prepara una strategia|trova i gap|pianifica|progetta)\b', re.I),
     RequestRoute.PROJECT_REASONING, RequestRisk.LOW, "retrieve", True),
    (re.compile(r'\b(reason about|evaluate|plan|strategize|analyze architecture|find gaps|design)\b', re.I),
     RequestRoute.PROJECT_REASONING, RequestRisk.LOW, "retrieve", True),
]

# Ambiguous triggers — short/context-free commands
_AMBIGUOUS_PATTERNS = [
    re.compile(r'^(fallo|fai|procedi|sistema|aggiusta|ok|vai|avanti)\.?\s*$', re.I),
    re.compile(r'^(do it|proceed|go ahead|fix it|handle it|ok)\s*\.?\s*$', re.I),
]

# Memory-mode keywords for soft memory update detection
_MEMORY_SOFT_PATTERNS = [
    re.compile(r'\b(ricorda|remember|preferenz|prefer|correction|correzione|non fare più)\b', re.I),
]


class JarvisRequestRouter:
    """Routes user requests to the appropriate processing path.

    Decision is based on:
    1. Preflight result (security, trust, intent from #1239)
    2. Message content classification
    3. Trust level and interlocutor identity
    4. Security policy (#1239 rules)
    """

    def __init__(
        self,
        project_root: str | Path | None = None,
        unified_memory=None,
    ):
        if project_root is None:
            try:
                from igris.models.config import CONFIG
                project_root = CONFIG.project_root
            except Exception:
                project_root = Path.home()
        self.project_root = Path(project_root)
        self._memory = unified_memory  # UnifiedMemory instance, optional

    def _get_memory(self):
        """Lazy-load UnifiedMemory if not provided."""
        if self._memory is None:
            try:
                from igris.core.unified_memory import UnifiedMemory
                self._memory = UnifiedMemory(project_root=self.project_root)
            except Exception as e:
                logger.debug("JarvisRequestRouter: UnifiedMemory unavailable: %s", e)
        return self._memory

    def classify(
        self,
        message: str,
        *,
        interlocutor_id: str = "unknown",
        trust_level: str = "untrusted",
        preflight=None,
        session_id: str = "",
        source: str = "chat",
        metadata: dict | None = None,
    ) -> JarvisRouteDecision:
        """Classify a request and return a route decision."""
        msg = (message or "").strip()
        tl = (trust_level or "untrusted").lower()
        warnings: list[str] = []

        # ── Step 1: Propagate preflight block ───────────────────────────────
        if preflight is not None:
            if getattr(preflight, "blocked", False):
                return JarvisRouteDecision(
                    route=RequestRoute.BLOCKED,
                    risk=RequestRisk.HIGH,
                    blocked=True,
                    intent_action=getattr(preflight, "intent_action", "blocked"),
                    reason=getattr(preflight, "block_reason", "preflight denied request"),
                    confidence=1.0,
                    warnings=warnings,
                )

        # ── Step 2: Check for ambiguous / context-free messages ─────────────
        for ambig in _AMBIGUOUS_PATTERNS:
            if ambig.match(msg):
                return JarvisRouteDecision(
                    route=RequestRoute.UNKNOWN_REQUIRES_CLARIFICATION,
                    risk=RequestRisk.UNKNOWN,
                    requires_clarification=True,
                    reason=f"Message {msg!r} is too ambiguous — missing target or context.",
                    confidence=0.9,
                    warnings=warnings,
                )

        # ── Step 3: Use preflight intent if available ────────────────────────
        preflight_action = getattr(preflight, "intent_action", "") if preflight else ""
        preflight_risk = getattr(preflight, "intent_risk", "low") if preflight else "low"
        preflight_advisory = getattr(preflight, "advisory", None) if preflight else None
        if preflight_advisory:
            warnings.append(f"advisory: {preflight_advisory}")

        # ── Step 4: Rule-based classification ───────────────────────────────
        matched_route = None
        matched_risk = RequestRisk.UNKNOWN
        matched_memory_mode = "retrieve"
        matched_mission = False
        matched_confidence = 0.0

        for pattern, route, risk, memory_mode, mission_req in _CLASSIFICATION_RULES:
            if pattern.search(msg):
                matched_route = route
                matched_risk = risk
                matched_memory_mode = memory_mode
                matched_mission = mission_req
                matched_confidence = 0.85
                break

        # ── Step 5: Soft memory update detection ────────────────────────────
        if matched_route is None:
            for p in _MEMORY_SOFT_PATTERNS:
                if p.search(msg):
                    matched_route = RequestRoute.MEMORY_UPDATE
                    matched_risk = RequestRisk.LOW
                    matched_memory_mode = "store"
                    matched_confidence = 0.7
                    break

        # ── Step 6: Default to chat_only ────────────────────────────────────
        if matched_route is None:
            matched_route = RequestRoute.CHAT_ONLY
            matched_risk = RequestRisk.LOW
            matched_memory_mode = "retrieve"
            matched_mission = False
            matched_confidence = 0.6

        route_val = matched_route.value if hasattr(matched_route, "value") else str(matched_route)
        risk_val = matched_risk.value if hasattr(matched_risk, "value") else str(matched_risk)

        # ── Step 7: Security policy enforcement ─────────────────────────────
        is_untrusted = tl in _UNTRUSTED_LEVELS
        is_destructive = risk_val in (RequestRisk.DESTRUCTIVE, RequestRisk.HIGH,
                                       "destructive", "high")

        if is_untrusted and is_destructive:
            return JarvisRouteDecision(
                route=RequestRoute.BLOCKED,
                risk=risk_val,
                blocked=True,
                intent_action=preflight_action or route_val,
                reason=f"Operation blocked: untrusted/unknown interlocutor cannot perform {risk_val} operations.",
                confidence=1.0,
                warnings=warnings,
                metadata={"interlocutor_id": interlocutor_id, "trust_level": tl},
            )

        # High-risk operations always require approval (even for trusted)
        requires_approval = risk_val in ("high", "destructive") or route_val in (
            RequestRoute.DEPLOY_OPERATION, RequestRoute.HIGH_RISK_OPERATION,
            "deploy_operation", "high_risk_operation"
        )

        # GitHub merge/close requires approval
        if route_val in (RequestRoute.GITHUB_OPERATION, "github_operation") and risk_val in ("high", "destructive"):
            requires_approval = True

        # Memory update for untrusted: allow as decision but flag it
        if route_val in (RequestRoute.MEMORY_UPDATE, "memory_update") and is_untrusted:
            warnings.append("untrusted memory_update — store decision produced but caller must verify before storage")

        return JarvisRouteDecision(
            route=route_val,
            risk=risk_val,
            intent_action=preflight_action or route_val,
            blocked=False,
            requires_clarification=False,
            requires_approval=requires_approval,
            memory_mode=matched_memory_mode,
            mission_required=matched_mission,
            reasoning_required=matched_mission and risk_val in ("medium", "high"),
            confidence=matched_confidence,
            reason=f"Classified as {route_val} (risk={risk_val})",
            warnings=warnings,
            metadata={"interlocutor_id": interlocutor_id, "trust_level": tl},
        )

    def route(
        self,
        message: str,
        *,
        interlocutor_id: str = "unknown",
        trust_level: str = "untrusted",
        preflight=None,
        session_id: str = "",
        source: str = "chat",
        metadata: dict | None = None,
    ) -> JarvisRouteDecision:
        """Route a request. Currently delegates to classify().

        In future versions, this will trigger side-effects based on the decision.
        """
        decision = self.classify(
            message,
            interlocutor_id=interlocutor_id,
            trust_level=trust_level,
            preflight=preflight,
            session_id=session_id,
            source=source,
            metadata=metadata,
        )

        # Best-effort memory retrieval for chat responses
        if not decision.blocked and decision.memory_mode == "retrieve":
            try:
                mem = self._get_memory()
                if mem:
                    result = mem.retrieve_for_chat(
                        query=message,
                        interlocutor_id=interlocutor_id,
                        trust_level=trust_level,
                        limit=5,
                    )
                    if result.context:
                        decision.metadata["memory_context"] = result.context
                        decision.metadata["memory_items_count"] = len(result.items)
            except Exception as e:
                logger.debug("JarvisRequestRouter: memory retrieval failed: %s", e)
                decision.warnings.append(f"memory_retrieval_degraded: {e}")

        return decision
