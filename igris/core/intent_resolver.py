"""
Intent Resolver — deterministic, LLM-free intent resolution (issue #526).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class IntentResolution:
    action_type: str
    target_resource: str
    urgency: str  # low | normal | high | critical
    implied_authorization: bool
    confidence: float
    ambiguous: bool
    clarification_question: str | None
    extracted_entities: dict[str, Any] = field(default_factory=dict)
    risk_hint: str = "low"  # low | medium | high | destructive


class IntentResolver:
    """Deterministic rule-based intent resolver. No LLM dependency."""

    DESTRUCTIVE_PATTERNS = [
        (r'\b(delete|remove|destroy|drop|wipe|purge|force.?push|reset.?hard)\b', 'destructive'),
        # Italian destructive
        (r'\b(cancella|elimina|rimuovi|svuota|pulisci|azzera|resetta|distruggi)\b', 'destructive'),
        (r'\b(deploy|rollback)\b', 'high'),
        (r'\b(restart|reboot|shutdown)\b', 'high'),
        # Italian high risk
        (r'\b(riavvia)\b', 'high'),
        (r'\b(fai\s+deploy|esegui\s+deploy|avvia\s+deploy)\b', 'high'),
        (r'\b(fai\s+rollback|esegui\s+rollback)\b', 'high'),
        (r'\b(merge|close.issue|approve.pr)\b', 'medium'),
    ]

    ACTION_PATTERNS = [
        (r'\b(restart|reboot)\b.*\b(server|vps|machine|instance)\b', 'restart_server'),
        # Italian restart server
        (r'\b(riavvia)\b.*\b(server|servizio|servizi|sistema)\b', 'restart_server'),
        (r'\b(riavvia)\b', 'restart_server'),
        (r'\b(deploy)\b', 'deploy'),
        # Italian deploy
        (r'\b(fai|esegui|avvia)\b.*\b(deploy|deployment)\b', 'deploy'),
        (r'\b(delete|remove)\b', 'delete'),
        # Italian delete
        (r'\b(cancella|elimina|rimuovi|svuota|pulisci)\b.*\b(branch|file|cartella|directory|database|db)\b', 'delete'),
        (r'\b(cancella|elimina|rimuovi)\b', 'delete'),
        (r'\b(merge)\b.*\bpr\b', 'merge_pr'),
        # Italian merge
        (r'\b(mergia|unisci)\b.*\b(pr|pull.request|branch)\b', 'merge_pr'),
        (r'\b(close)\b.*\bissue\b', 'close_issue'),
        # Italian close issue
        (r'\b(chiudi)\b.*\b(issue|ticket|bug)\b', 'close_issue'),
        (r'\b(read|show|get|list)\b.*\b(issue|pr|pull.request)\b', 'read_github'),
        (r'\b(run|execute)\b.*\btest', 'run_tests'),
        # Italian run tests
        (r'\b(lancia|esegui|avvia)\b.*\b(test|testing)\b', 'run_tests'),
        (r'\b(inspect|check|tail|show)\b.*\blog', 'inspect_logs'),
        # Italian inspect logs
        (r'\b(controlla|ispeziona|guarda|vedi)\b.*\b(log|logs)\b', 'inspect_logs'),
        (r'\b(network|ping|traceroute|dns)\b', 'network_diagnostic'),
        # Italian network
        (r'\b(controlla|verifica)\b.*\b(rete|network|dns|ping|connessione)\b', 'network_diagnostic'),
        (r'\b(browser|screenshot|navigate)\b', 'browser_check'),
        (r'\b(rollback)\b', 'rollback'),
        # Italian rollback
        (r'\b(fai|esegui)\b.*\b(rollback|revert)\b', 'rollback'),
    ]

    TARGET_PATTERNS = [
        (r'\bpr\s*#?(\d+)\b', 'pr', 1),
        (r'\bissue\s*#?(\d+)\b', 'issue', 1),
        (r'\bticket\s*#?(\d+)\b', 'issue', 1),
        (r'\bbranch\s+([a-zA-Z0-9/_-]+)\b', 'branch', 1),
        (r'\b(?:repo|repository)\s+([a-zA-Z0-9/_-]+)\b', 'repo', 1),
        (r'\bserver\s+([a-zA-Z0-9._-]+)\b', 'server', 1),
    ]

    URGENCY_PATTERNS = [
        (r'\b(urgent|asap|immediately|critical|emergency|now)\b', 'critical'),
        # Italian critical
        (r'\b(urgente|subito|immediatamente|adesso|criticamente)\b', 'critical'),
        (r'\b(important|quickly|soon|high.priority)\b', 'high'),
        # Italian high
        (r'\b(importante|presto|veloce)\b', 'high'),
        (r'\b(when.you.can|low.priority|eventually)\b', 'low'),
    ]

    def resolve(self, message: str, state_urgency: str | None = None) -> IntentResolution:
        msg_lower = message.lower()

        action_type = "unknown"
        confidence = 0.3
        for pattern, action in self.ACTION_PATTERNS:
            if re.search(pattern, msg_lower):
                action_type = action
                confidence = 0.85
                break

        target_resource = "unknown"
        extracted_entities: dict[str, Any] = {}
        for pattern, kind, group in self.TARGET_PATTERNS:
            m = re.search(pattern, msg_lower)
            if m:
                target_resource = f"{kind}:{m.group(group)}"
                extracted_entities[kind] = m.group(group)
                break

        risk_hint = "low"
        for pattern, risk in self.DESTRUCTIVE_PATTERNS:
            if re.search(pattern, msg_lower):
                risk_hint = risk
                break

        urgency = state_urgency or "normal"
        for pattern, urg in self.URGENCY_PATTERNS:
            if re.search(pattern, msg_lower):
                urgency = urg
                break

        ambiguous = action_type == "unknown" or (
            target_resource == "unknown"
            and action_type not in (
                "run_tests", "network_diagnostic", "browser_check", "inspect_logs",
                "rollback", "restart_server",
            )
        )

        clarification_question = None
        if ambiguous:
            if action_type == "unknown":
                clarification_question = "Could you clarify what action you want me to perform?"
            elif target_resource == "unknown":
                clarification_question = f"What is the target resource for '{action_type}'?"

        implied_authorization = risk_hint in ("low",) and not ambiguous

        return IntentResolution(
            action_type=action_type,
            target_resource=target_resource,
            urgency=urgency,
            implied_authorization=implied_authorization,
            confidence=confidence,
            ambiguous=ambiguous,
            clarification_question=clarification_question,
            extracted_entities=extracted_entities,
            risk_hint=risk_hint,
        )
