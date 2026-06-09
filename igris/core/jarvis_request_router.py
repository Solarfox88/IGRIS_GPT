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
# Rules are evaluated in order; first match wins.  More specific / higher-risk
# rules MUST appear before broader catch-alls.
_CLASSIFICATION_RULES: list[tuple[re.Pattern, str, str, str, bool]] = [

    # ══ PRIORITY 0 — MEMORY UPDATE ═════════════════════════════════════════
    # Evaluated first so "ricordati che il deploy è riabilitato" doesn't trip
    # the deploy rule.
    (re.compile(r'\b(ricordati|tieni a mente|salva questa preferenza|preferisco|non voglio più|non usare più|questa correzione|da ora in poi|correggi la memoria)\b', re.I),
     RequestRoute.MEMORY_UPDATE, RequestRisk.LOW, "store", False),
    (re.compile(r'\b(remember that|save this preference|from now on|i prefer|don\'t use|correct your memory|update your memory)\b', re.I),
     RequestRoute.MEMORY_UPDATE, RequestRisk.LOW, "store", False),

    # ══ PRIORITY 1 — SHELL / SYSTEM COMMAND EXECUTION ═════════════════════
    # Any shell command with destructive flags is ALWAYS high-risk regardless
    # of trust level.  These patterns fire before broader word checks.

    # rm -rf (any form)
    (re.compile(r'\brm\s+(-\S*r\S*f|-\S*f\S*r|--recursive|--force)', re.I),
     RequestRoute.HIGH_RISK_OPERATION, RequestRisk.DESTRUCTIVE, "none", True),
    # rm with a path (without explicit -rf but clearly a file removal intent)
    (re.compile(r'\brm\b.{0,60}\b(\/|home|root|etc|usr|var|tmp|igris|prod)', re.I),
     RequestRoute.HIGH_RISK_OPERATION, RequestRisk.DESTRUCTIVE, "none", True),

    # sudo — any privileged shell invocation
    (re.compile(r'\bsudo\b', re.I),
     RequestRoute.HIGH_RISK_OPERATION, RequestRisk.DESTRUCTIVE, "none", True),

    # "esegui" / "lancia" / "run" / "execute" followed by a shell-like command
    (re.compile(
        r'\b(esegui|lancia|run|execute|avvia)\b.{0,50}'
        r'\b(rm|kill|pkill|chmod|chown|bash|sh|zsh|powershell|cmd|nc|curl|wget|python|perl|ruby|node|dd|mkfs|fdisk|parted)\b',
        re.I),
     RequestRoute.HIGH_RISK_OPERATION, RequestRisk.DESTRUCTIVE, "none", True),

    # Generic "esegui un comando shell / comando di sistema"
    (re.compile(r'\b(esegui|lancia)\b.{0,30}\b(comando|command|shell|script)\b', re.I),
     RequestRoute.HIGH_RISK_OPERATION, RequestRisk.HIGH, "none", True),
    (re.compile(r'\b(run a command|execute a command|run this command|run shell|execute shell)\b', re.I),
     RequestRoute.HIGH_RISK_OPERATION, RequestRisk.HIGH, "none", True),

    # kill / pkill / killall
    (re.compile(r'\b(kill|pkill|killall|sigkill|sigterm)\b.{0,30}\b(processo|process|pid|\d+)\b', re.I),
     RequestRoute.HIGH_RISK_OPERATION, RequestRisk.HIGH, "none", True),

    # formatta / wipe disk
    (re.compile(r'\b(formatta|wipe|mkfs|fdisk|parted|dd\s+if=)\b', re.I),
     RequestRoute.HIGH_RISK_OPERATION, RequestRisk.DESTRUCTIVE, "none", True),

    # ══ PRIORITY 2 — HIGH-RISK / DESTRUCTIVE DATABASE & FILESYSTEM ════════

    # Database destructive (Italian + English, combined)
    (re.compile(
        r'\b(cancella|elimina|rimuovi|distruggi|svuota|resetta|formatta|azzera|wipe|drop|truncate|purge|delete all|remove all|destroy)\b'
        r'.{0,40}'
        r'\b(database|db|produzione|server|tutti i file|volume|backup|tutto|prod|everything)\b',
        re.I),
     RequestRoute.HIGH_RISK_OPERATION, RequestRisk.DESTRUCTIVE, "none", True),
    (re.compile(r'\b(drop|truncate|purge|delete all|remove all|destroy|wipe)\b.{0,40}\b(database|db|prod|server|volume|everything)\b', re.I),
     RequestRoute.HIGH_RISK_OPERATION, RequestRisk.DESTRUCTIVE, "none", True),

    # ══ PRIORITY 3 — GIT DESTRUCTIVE & WRITE OPERATIONS ══════════════════

    # Destructive git
    # Note: \b removed from end of clean pattern — git clean -fd has no word boundary after f
    (re.compile(r'\bgit\s+(reset\s+--hard|clean\s+-\S*f\S*|push\s+--force|-f\s+push|push\s+-f)\b', re.I),
     RequestRoute.HIGH_RISK_OPERATION, RequestRisk.DESTRUCTIVE, "none", True),
    (re.compile(r'\b(git reset --hard|git clean -[a-z]*f|force push|push --force)\b', re.I),
     RequestRoute.HIGH_RISK_OPERATION, RequestRisk.DESTRUCTIVE, "none", True),

    # Git write (commit, push, merge, rebase, branch delete)
    (re.compile(r'\bgit\s+(push|commit|merge|rebase|branch\s+-[dD]|tag\s+-d)\b', re.I),
     RequestRoute.GITHUB_OPERATION, RequestRisk.MEDIUM, "none", True),
    (re.compile(r'\b(fai\s+(git\s+)?commit|fai\s+(git\s+)?push|committa|fai\s+push|esegui\s+(il\s+)?commit)\b', re.I),
     RequestRoute.GITHUB_OPERATION, RequestRisk.MEDIUM, "none", True),

    # ══ PRIORITY 4 — DEPLOY ═══════════════════════════════════════════════

    (re.compile(r'\b(fai deploy|esegui deploy|deploy in produzione|pubblica in prod|rilascia in prod|rollback|torna indietro)\b', re.I),
     RequestRoute.DEPLOY_OPERATION, RequestRisk.HIGH, "none", True),
    # "deploy" prefix match: catches deploya, deployare, deploying, etc.
    (re.compile(r'\bdeploy\w*\b|\b(rollback|release to prod|push to production)\b', re.I),
     RequestRoute.DEPLOY_OPERATION, RequestRisk.HIGH, "none", True),

    # ══ PRIORITY 5 — SERVER / SYSTEM OPERATION ════════════════════════════

    # With explicit target (server, service, nginx…)
    (re.compile(r'\b(riavvia|spegni|shutdown|reboot|restart)\b.{0,30}\b(server|servizio|nginx|vps|servizi|istanza|igris)\b', re.I),
     RequestRoute.SERVER_OPERATION, RequestRisk.HIGH, "none", True),
    (re.compile(r'\b(restart|reboot|shutdown)\b.{0,30}\b(server|service|nginx|vps|instance|igris)\b', re.I),
     RequestRoute.SERVER_OPERATION, RequestRisk.HIGH, "none", True),
    # systemctl / service commands
    (re.compile(r'\bsystemctl\b.{0,40}\b(restart|stop|start|disable|enable)\b', re.I),
     RequestRoute.SERVER_OPERATION, RequestRisk.HIGH, "none", True),
    (re.compile(r'\b(service\s+\w+\s+(restart|stop|start))\b', re.I),
     RequestRoute.SERVER_OPERATION, RequestRisk.HIGH, "none", True),
    # Standalone reboot/shutdown/restart/riavvia without explicit target
    # (covers "sudo reboot" after sudo is caught above, but also bare "reboot", "riavvia")
    (re.compile(r'^\s*(sudo\s+)?(reboot|shutdown|halt|poweroff|riavvia|spegni)\s*', re.I),
     RequestRoute.SERVER_OPERATION, RequestRisk.HIGH, "none", True),
    (re.compile(r'\b(reboot|halt|poweroff)\b', re.I),
     RequestRoute.SERVER_OPERATION, RequestRisk.HIGH, "none", True),

    # ══ PRIORITY 6 — GITHUB WRITE OPERATIONS ══════════════════════════════

    # PR merge / approve
    (re.compile(r'\b(mergia|unisci|approva|merge|approve)\b.{0,20}\b(pr|pull request|branch)\b', re.I),
     RequestRoute.GITHUB_OPERATION, RequestRisk.HIGH, "none", True),

    # Issue/PR creation
    (re.compile(r'\b(crea|apri|open|create|nuova|nuovo)\b.{0,30}\b(issue|ticket|bug report|pull request|pr)\b', re.I),
     RequestRoute.GITHUB_OPERATION, RequestRisk.MEDIUM, "none", True),

    # Branch creation — allow articles/det. between verb and noun ("crea un branch")
    (re.compile(r'\b(crea|apri|open|create)\b.{0,15}\b(branch)\b', re.I),
     RequestRoute.GITHUB_OPERATION, RequestRisk.MEDIUM, "none", True),
    (re.compile(r'\b(crea pr|crea pull request|apri pr|open pr|create pr)\b', re.I),
     RequestRoute.GITHUB_OPERATION, RequestRisk.MEDIUM, "none", True),

    # Issue close/reopen
    (re.compile(r'\b(chiudi|riapri|close|reopen)\b.{0,20}\b(issue|ticket|bug)\b', re.I),
     RequestRoute.GITHUB_OPERATION, RequestRisk.MEDIUM, "none", True),

    # Workflow / CI trigger — require explicit workflow/action/pipeline/ci context
    # to avoid false-positive with generic "rilancia" verbs
    (re.compile(r'\b(triggera|trigger|rilancia|riavvia|lancia|run|esegui)\b.{0,40}\b(workflow|github action|github actions|pipeline|ci/cd)\b', re.I),
     RequestRoute.GITHUB_OPERATION, RequestRisk.HIGH, "none", True),
    (re.compile(r'\b(run workflow|trigger workflow|trigger ci|trigger pipeline|trigger action|run ci)\b', re.I),
     RequestRoute.GITHUB_OPERATION, RequestRisk.HIGH, "none", True),

    # Comment / label / assign (write, medium risk)
    # Broad form: "commenta la issue", "aggiungi un commento alla issue #1"
    (re.compile(r'\b(commenta|comment on|add comment)\b.{0,40}\b(issue|pr|pull request|ticket|#\d+)\b', re.I),
     RequestRoute.GITHUB_OPERATION, RequestRisk.MEDIUM, "none", True),
    (re.compile(r'\baggiungi\b.{0,20}\b(commento|label|etichetta)\b.{0,30}\b(issue|pr|ticket|#\d+)\b', re.I),
     RequestRoute.GITHUB_OPERATION, RequestRisk.MEDIUM, "none", True),
    (re.compile(r'\b(add label|add comment|assign)\b.{0,40}\b(issue|pr|ticket|#\d+|\w+)\b', re.I),
     RequestRoute.GITHUB_OPERATION, RequestRisk.MEDIUM, "none", True),
    # Looser: "commenta issue #1293", "aggiungi label", "assegna"
    (re.compile(r'\b(commenta|aggiungi label|assegna)\b.{0,20}\b(issue|pr|ticket|#\d+)\b', re.I),
     RequestRoute.GITHUB_OPERATION, RequestRisk.MEDIUM, "none", True),

    # ══ PRIORITY 7 — FILESYSTEM WRITE / PATCH ════════════════════════════

    # Write / patch a file
    (re.compile(r'\b(scrivi|scrivere|salva|overwrite)\b.{0,30}\b(file|disco|disk|path)\b', re.I),
     RequestRoute.CODE_CHANGE, RequestRisk.MEDIUM, "none", True),
    (re.compile(r'\b(applica|apply)\b.{0,20}\b(patch|diff|modifica|cambiamento)\b', re.I),
     RequestRoute.CODE_CHANGE, RequestRisk.MEDIUM, "none", True),
    (re.compile(r'\b(write to file|write file|save to disk|apply patch|apply diff|applica questa patch)\b', re.I),
     RequestRoute.CODE_CHANGE, RequestRisk.MEDIUM, "none", True),
    # English filesystem write: "write X to disk", "write X file"
    (re.compile(r'\b(write|save)\b.{0,20}\b(file|disk|path|directory)\b', re.I),
     RequestRoute.CODE_CHANGE, RequestRisk.MEDIUM, "none", True),
    # Delete a specific file/directory (non-database)
    (re.compile(r'\b(cancella|elimina|rimuovi|delete|remove)\b.{0,30}\b(file|cartella|directory|folder|path)\b', re.I),
     RequestRoute.HIGH_RISK_OPERATION, RequestRisk.HIGH, "none", True),

    # ══ PRIORITY 8 — CODE CHANGE ══════════════════════════════════════════

    (re.compile(r'\b(modifica|aggiorna|implementa|fixa|correggi il codice|crea una pr|committa)\b', re.I),
     RequestRoute.CODE_CHANGE, RequestRisk.MEDIUM, "retrieve", True),
    (re.compile(r'\b(fix|implement|modify|update|change|refactor|create pr|commit)\b.{0,40}\b(code|file|function|class|module|test)\b', re.I),
     RequestRoute.CODE_CHANGE, RequestRisk.MEDIUM, "retrieve", True),
    # Fix/update with an explicit source-file extension mentioned
    (re.compile(r'\b(fix|implement|modify|update|change|refactor|debug|correct)\b.{0,80}\b\w+\.(py|js|ts|go|rs|java|rb|cpp|c|h|yaml|yml|toml|json)\b', re.I),
     RequestRoute.CODE_CHANGE, RequestRisk.MEDIUM, "retrieve", True),

    # ══ PRIORITY 9 — REMAINING DESTRUCTIVE ITALIAN VERBS ═════════════════
    # Catch-all for "cancella", "elimina", "distruggi" without DB/server context
    # (after the higher-priority file/db patterns above)
    (re.compile(r'\b(cancella|elimina|distruggi)\b', re.I),
     RequestRoute.HIGH_RISK_OPERATION, RequestRisk.HIGH, "none", True),

    # ══ PRIORITY 10 — READ ONLY INSPECTION ═══════════════════════════════

    (re.compile(r'\b(controlla|verifica|leggi|mostra|analizza|dai un\'?occhiata|guarda i log|stato|report|diagnostica)\b', re.I),
     RequestRoute.READ_ONLY_INSPECTION, RequestRisk.LOW, "retrieve", True),
    (re.compile(r'\b(check|verify|read|show|display|inspect|look at|analyze|status|report|diagnose|review)\b.{0,40}\b(log|report|state|status|error|output|result)\b', re.I),
     RequestRoute.READ_ONLY_INSPECTION, RequestRisk.LOW, "retrieve", True),

    # ══ PRIORITY 11 — PROJECT REASONING ══════════════════════════════════

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
        is_limited = tl == "limited"
        is_trusted = tl in _TRUSTED_LEVELS
        is_destructive = risk_val in (RequestRisk.DESTRUCTIVE, RequestRisk.HIGH,
                                       "destructive", "high")

        # Routes that limited users cannot perform (blocked outright)
        _LIMITED_BLOCKED_ROUTES = {
            RequestRoute.HIGH_RISK_OPERATION, "high_risk_operation",
            RequestRoute.DEPLOY_OPERATION, "deploy_operation",
            RequestRoute.SERVER_OPERATION, "server_operation",
        }
        # Routes that limited users cannot perform (blocked for write risk,
        # since limited scope = chat + read_own_profile only)
        _LIMITED_BLOCKED_WRITE_ROUTES = {
            RequestRoute.CODE_CHANGE, "code_change",
            RequestRoute.GITHUB_OPERATION, "github_operation",
        }

        # Block untrusted on any destructive/high-risk operation
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

        # Block untrusted on any operational route (even medium risk)
        if is_untrusted and route_val not in (
            RequestRoute.CHAT_ONLY, "chat_only",
            RequestRoute.MEMORY_UPDATE, "memory_update",
            RequestRoute.READ_ONLY_INSPECTION, "read_only_inspection",
            RequestRoute.PROJECT_REASONING, "project_reasoning",
            RequestRoute.UNKNOWN_REQUIRES_CLARIFICATION, "unknown_requires_clarification",
        ):
            return JarvisRouteDecision(
                route=RequestRoute.BLOCKED,
                risk=risk_val,
                blocked=True,
                intent_action=preflight_action or route_val,
                reason=f"Operation blocked: untrusted interlocutor cannot initiate {route_val} operations.",
                confidence=1.0,
                warnings=warnings,
                metadata={"interlocutor_id": interlocutor_id, "trust_level": tl},
            )

        # Block limited on high-risk / destructive routes
        if is_limited and route_val in _LIMITED_BLOCKED_ROUTES:
            return JarvisRouteDecision(
                route=RequestRoute.BLOCKED,
                risk=risk_val,
                blocked=True,
                intent_action=preflight_action or route_val,
                reason=(
                    f"Operation blocked: limited-trust interlocutor cannot perform "
                    f"{route_val} (risk={risk_val}). Required scope: admin or owner."
                ),
                confidence=1.0,
                warnings=warnings,
                metadata={"interlocutor_id": interlocutor_id, "trust_level": tl},
            )

        # Block limited on write-route operations (code change, GitHub write)
        # limited scope = {chat, read_own_profile} — no write permitted
        if is_limited and route_val in _LIMITED_BLOCKED_WRITE_ROUTES:
            return JarvisRouteDecision(
                route=RequestRoute.BLOCKED,
                risk=risk_val,
                blocked=True,
                intent_action=preflight_action or route_val,
                reason=(
                    f"Operation blocked: limited-trust interlocutor cannot initiate "
                    f"{route_val} operations. Required scope: admin or owner."
                ),
                confidence=1.0,
                warnings=warnings,
                metadata={"interlocutor_id": interlocutor_id, "trust_level": tl},
            )

        # High-risk and destructive operations always require explicit approval
        # (for trusted / admin / owner)
        requires_approval = risk_val in ("high", "destructive") or route_val in (
            RequestRoute.DEPLOY_OPERATION, RequestRoute.HIGH_RISK_OPERATION,
            "deploy_operation", "high_risk_operation",
        )

        # GitHub write operations (medium+ risk) require approval for trusted users too
        if route_val in (RequestRoute.GITHUB_OPERATION, "github_operation") and risk_val in ("medium", "high", "destructive"):
            requires_approval = True

        # Code change always requires approval (regardless of risk level)
        if route_val in (RequestRoute.CODE_CHANGE, "code_change"):
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
