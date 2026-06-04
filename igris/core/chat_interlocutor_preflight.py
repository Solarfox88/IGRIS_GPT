"""Chat interlocutor preflight — runs before every chat_llm() call.

Implements the full interlocutor-aware pipeline for conversational entry points
as part of issue #526.

Security hardening (#1239):
- Anti-spoofing: owner/system from non-local requests downgraded to unknown
- AuthorizationGate called for sensitive authorized actions
- Delegation key verify path for unknown/untrusted interlocutors
- Silent excepts replaced with logging/degraded state
- Audit write failures produce visible degraded log
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Privileged IDs that cannot be claimed from non-local HTTP requests
PRIVILEGED_IDS = {"owner", "system"}


@dataclass
class PreflightResult:
    interlocutor_id: str
    trust_level: str
    response_mode: dict
    intent_action: str
    intent_risk: str
    blocked: bool
    block_reason: str | None
    requires_clarification: bool
    clarification_question: str | None
    advisory: str | None
    system_prompt_enrichment: str
    audit_event_id: str | None = None

    @property
    def allowed(self) -> bool:
        return not self.blocked and not self.requires_clarification


SENSITIVE_CHAT_ACTIONS = {
    "deploy", "delete", "rollback", "merge_pr", "close_issue",
    "run_command", "network_diagnostic", "github_write", "github_admin",
    "browser_operation", "override", "restart_server",
}


def is_trusted_local_request(
    request_headers: dict | None = None,
    remote_addr: str | None = None,
) -> bool:
    """Returns True if request is from localhost/127.0.0.1.

    SECURITY: X-Forwarded-For headers are NEVER trusted if remote_addr is None
    or empty, as a remote attacker behind a proxy could spoof them to claim
    owner/system identity.
    """
    LOCAL_ADDRS = {"127.0.0.1", "::1", "localhost"}
    # Primary: trust only the direct connection address
    if remote_addr:
        return remote_addr in LOCAL_ADDRS
    # remote_addr is None or empty — we CANNOT safely trust X-Forwarded-For.
    # Return False unconditionally to prevent proxy-based owner spoofing.
    return False


def _resolve_privileged_identity(candidate_id: str, is_local: bool) -> str:
    """Privileged IDs (owner/system) only allowed from local/internal requests.

    If a non-local caller claims 'owner' or 'system', downgrade to 'unknown'
    to prevent spoofing attacks.
    """
    if candidate_id in PRIVILEGED_IDS:
        if is_local:
            return candidate_id  # trusted local UI
        logger.warning(
            "Anti-spoofing: privileged identity '%s' claimed from non-local request — "
            "downgraded to 'unknown'",
            candidate_id,
        )
        return "unknown"  # downgrade — cannot verify over network
    return candidate_id


def run_preflight(
    message: str,
    interlocutor_id: str | None = None,
    project_root: str | None = None,
    is_new_session: bool = False,
    is_local_request: bool = False,
    payload: dict | None = None,
) -> PreflightResult:
    """Full interlocutor-aware preflight for a chat message.

    Args:
        message: The chat message to check.
        interlocutor_id: Identity claimed by the caller.
        project_root: Path to the IGRIS project root.
        is_new_session: Whether this is the first message in a session.
        is_local_request: True if the request originated from localhost (127.0.0.1).
        payload: Raw request payload (for delegation key fields).
    """
    from pathlib import Path

    # 1. Resolve identity — with anti-spoofing for privileged IDs
    raw_id = interlocutor_id or "unknown"
    _id = _resolve_privileged_identity(raw_id, is_local=is_local_request)

    profile = None
    trust_level = "untrusted"
    try:
        from igris.core.identity_resolver import IdentityResolver
        root = project_root or str(Path.home())
        ir = IdentityResolver(root)
        profile = ir.resolve(_id)
        trust_level = str(getattr(profile, "trust_level", "untrusted")).lower()
        if hasattr(profile, "touch"):
            profile.touch()
        # Persist interaction (best-effort): update disk for non-builtin profiles
        from igris.core.identity_resolver import BUILTIN_PROFILES as _BUILTIN
        if profile.profile_id not in _BUILTIN:
            try:
                ir.update(profile)
            except Exception as _upd_exc:
                logger.debug("Profile update skipped: %s", _upd_exc)
    except Exception as _id_exc:
        logger.debug("Identity resolution failed for '%s': %s", _id, _id_exc)

    # 2. Detect state
    response_mode: dict = {
        "verbosity": "normal",
        "tone": "professional",
        "lead_with_action": False,
        "use_bullet_points": False,
        "simplify_language": False,
    }
    try:
        from igris.core.state_calibration import StateCalibration
        sc = StateCalibration()
        state = sc.detect(message)
        expertise = getattr(profile, "expertise_level", "intermediate") if profile else "intermediate"
        style = getattr(profile, "communication_style", "technical") if profile else "technical"
        mode = sc.select_response_mode(state, communication_style=style, expertise_level=expertise)
        response_mode = {
            "verbosity": mode.verbosity,
            "tone": mode.tone,
            "lead_with_action": mode.lead_with_action,
            "use_bullet_points": mode.use_bullet_points,
            "simplify_language": mode.simplify_language,
        }
    except Exception as _sc_exc:
        logger.debug("State calibration skipped: %s", _sc_exc)

    # 3. Resolve intent
    intent_action = "unknown"
    intent_risk = "low"
    ambiguous = False
    clarification_question = None
    intent = None
    try:
        from igris.core.intent_resolver import IntentResolver
        ir2 = IntentResolver()
        intent = ir2.resolve(message)
        intent_action = intent.action_type
        intent_risk = intent.risk_hint
        ambiguous = intent.ambiguous
        clarification_question = intent.clarification_question
    except Exception as _ir_exc:
        logger.debug("Intent resolution failed: %s", _ir_exc)

    # 4. Authorization for action-like intents
    blocked = False
    block_reason = None
    advisory = None

    is_sensitive = intent_action in SENSITIVE_CHAT_ACTIONS or intent_risk in ("high", "destructive")
    is_untrusted = trust_level in ("untrusted", "unknown", "")

    if is_sensitive and is_untrusted:
        # 4a. Try delegation key verification before blocking
        _dk_id = (payload or {}).get("delegation_key_id")
        _dk_pass = (payload or {}).get("delegation_key_passphrase")

        if _dk_id and _dk_pass:
            try:
                from igris.core.delegation_keys import verify_key
                root = project_root or str(Path.home())
                _ok, _dk_reason = verify_key(
                    project_root=root,
                    key_id=_dk_id,
                    raw_passphrase=_dk_pass,
                    requested_scopes=[intent_action],
                    bearer=_id,
                )
                del _dk_pass  # never keep passphrase in scope longer than needed
                if _ok:
                    del _dk_id  # cleanup key ID after successful use
                    is_untrusted = False
                    trust_level = "limited"  # delegation scope only
                    advisory = f"Proceeding via delegation key (scope: {intent_action})"
                    logger.info(
                        "Delegation key accepted for interlocutor '%s', action '%s'",
                        _id, intent_action,
                    )
                else:
                    del _dk_id
                    blocked = True
                    block_reason = (
                        f"Delegation key rejected: {_dk_reason}. "
                        "Identify yourself or provide a valid delegation key."
                    )
                    logger.warning(
                        "Delegation key rejected for interlocutor '%s': %s",
                        _id, _dk_reason,
                    )
            except Exception as _dk_exc:
                logger.warning("Delegation key verify error for '%s': %s", _id, _dk_exc)
                blocked = True
                block_reason = "Delegation key verification failed — sensitive action blocked for safety."
        else:
            blocked = True
            block_reason = (
                f"Action '{intent_action}' (risk: {intent_risk}) denied for unrecognized interlocutor. "
                "Please identify yourself or provide a delegation key."
            )
    elif is_sensitive and not is_untrusted:
        advisory = (
            f"Action '{intent_action}' is sensitive (risk: {intent_risk}). "
            "Proceeding with authorization."
        )

    # 4b. AuthorizationGate check for authorized non-blocked sensitive actions
    if is_sensitive and not is_untrusted and not blocked and profile is not None:
        try:
            from igris.core.authorization_gate import AuthorizationGate
            root = project_root or str(Path.home())
            _ag = AuthorizationGate(root)
            _scope = (
                intent.target_resource if intent is not None and hasattr(intent, "target_resource")
                else intent_action
            )
            _auth_result = _ag.check(profile, action_type=intent_action, target_resource=_scope)
            if not _auth_result.allowed:
                blocked = True
                block_reason = f"AuthorizationGate denied: {getattr(_auth_result, 'reason', 'scope not authorized')}"
                logger.warning(
                    "AuthorizationGate denied action '%s' for '%s': %s",
                    intent_action, _id, block_reason,
                )
            elif getattr(_auth_result, "requires_delegation_key", False):
                advisory = f"Action may require a delegation key: {getattr(_auth_result, 'message', '')}"
        except Exception as _ag_exc:
            logger.warning("AuthorizationGate unavailable: %s", _ag_exc)
            if is_sensitive:
                blocked = True
                block_reason = "Authorization check unavailable — sensitive action blocked for safety."

    # 4c. Judgment Layer advisory (Layer 5) — only for authorized non-blocked actions
    if not blocked and is_sensitive and not is_untrusted:
        try:
            from igris.core.judgment_layer import JudgmentLayer, OperationalContext
            _jl = JudgmentLayer()
            _ctx = OperationalContext()
            _adv = _jl.advise(
                action_type=intent_action,
                target_resource="chat",
                context=_ctx,
                trust_level=trust_level,
            )
            if _adv and not _adv.should_proceed:
                advisory = _adv.message
            elif _adv and _adv.message:
                advisory = _adv.message
        except Exception as _jl_exc:
            logger.debug("JudgmentLayer skipped: %s", _jl_exc)

    # 4d. Proactive Engine scan (Layer 7) — appended to advisory if events found
    if not blocked and not is_untrusted:
        try:
            from igris.core.proactive_engine import ProactiveEngine
            from pathlib import Path as _Path
            _pe = ProactiveEngine(project_root or str(_Path.home()))
            _scopes = list(getattr(profile, "authorized_scopes", []) or []) if profile else []
            _events = _pe.scan(
                state_snapshot={},
                authorized_scopes=_scopes or None,
                trust_level=trust_level,
            )
            if _events:
                _event_summary = "; ".join(
                    f"{e.event_type}:{e.resource}" for e in _events[:3]
                )
                proactive_hint = f"[Proactive] {_event_summary}"
                advisory = f"{advisory}\n{proactive_hint}" if advisory else proactive_hint
        except Exception as _pe_exc:
            logger.debug("ProactiveEngine skipped: %s", _pe_exc)

    # 5. Build system prompt enrichment — behavioral instructions, not just context
    profile_summary = ""
    display = getattr(profile, "display_name", _id) if profile else _id
    expertise = getattr(profile, "expertise_level", "unknown") if profile else "unknown"
    style = getattr(profile, "communication_style", "neutral") if profile else "neutral"

    if _id in ("unknown", "") or profile is None or trust_level in ("untrusted", "unknown", ""):
        # Unknown interlocutor — IGRIS must actively try to identify them
        new_session_hint = (
            "- IMPORTANTE: È la PRIMA interazione di questa sessione. "
            "Presentati come IGRIS e chiedi SUBITO chi è l'utente prima di fare altro. "
            "Esempio: 'Ciao! Sono IGRIS, il tuo agente operativo personale. "
            "Non ho ancora un profilo per te — potresti dirmi chi sei?'\n"
        ) if is_new_session else (
            "- Stai continuando una sessione con utente non identificato. "
            "Ricordagli che non lo hai ancora riconosciuto se fa richieste sensibili.\n"
        )
        profile_summary = (
            "\n[PROTOCOLLO IDENTITÀ]\n"
            "Stai ricevendo un messaggio da un utente NON IDENTIFICATO (untrusted).\n"
            "COMPORTAMENTO RICHIESTO:\n"
            f"{new_session_hint}"
            "- Non eseguire azioni sensibili (deploy, delete, comandi di sistema) finché l'identità non è verificata.\n"
            "- Per richieste innocue (informazioni, stato, domande generali) puoi rispondere normalmente.\n"
            "- Tono: neutro e accogliente, non tecnico.\n"
        )
    else:
        # Known interlocutor — greet by name if session start, calibrate response
        is_admin = trust_level in ("admin", "trusted")
        greeting_hint = (
            f"- IMPORTANTE: È la PRIMA interazione di questa sessione. "
            f"Saluta {display} per nome nella tua risposta.\n"
        ) if is_new_session and is_admin else (
            f"- Se appropriato, puoi usare il nome '{display}'.\n"
        )
        style_hint = {
            "technical": "diretto e tecnico, preferisci bullet points e codice",
            "casual": "informale e conversazionale",
            "formal": "formale e preciso",
        }.get(style, "professionale")
        expertise_hint = {
            "owner": "esperto del progetto, massima fiducia, nessun filtro inutile",
            "expert": "esperto tecnico, salta le spiegazioni base",
            "intermediate": "discretamente tecnico, spiega le scelte",
            "novice": "semplifica il linguaggio, evita tecnicismi",
        }.get(expertise, "livello intermedio")
        profile_summary = (
            f"\n[PROTOCOLLO IDENTITÀ]\n"
            f"Stai parlando con: {display}\n"
            f"Trust: {trust_level} | Expertise: {expertise} | Stile: {style}\n"
            f"{greeting_hint}"
            f"COMPORTAMENTO RICHIESTO:\n"
            f"- Stile risposta: {style_hint}.\n"
            f"- Livello dettaglio: {expertise_hint}.\n"
            f"- Verbosità: {response_mode.get('verbosity', 'normal')} | "
            f"Lead with action: {response_mode.get('lead_with_action', False)}.\n"
            f"- Usa il nome '{display}' quando appropriato.\n"
        )

    # Append advisory to system prompt if present (Layer 5 Judgment output)
    if advisory and not blocked:
        profile_summary += (
            f"\n[ADVISORY IGRIS]\n"
            f"{advisory}\n"
            f"Se il tuo giudizio lo richiede, comunica questo advisory all'utente.\n"
        )

    # 6. Audit — fix 7: use CONFIG.project_root, fix 9: log on write failure
    audit_event_id = None
    try:
        from igris.core.interlocutor_audit import InterlocutorAudit
        try:
            from igris.models.config import CONFIG
            _audit_path = None  # InterlocutorAudit will use CONFIG.project_root if we pass None
        except Exception:
            _audit_path = None
        audit = InterlocutorAudit(path=_audit_path)
        event_type = (
            "auth_denied" if blocked
            else ("auth_allowed" if is_sensitive else "identity_resolved")
        )
        audit_event_id = audit.record(
            event_type=event_type,
            interlocutor_id=_id,
            display_name=str(getattr(profile, "display_name", _id)),
            trust_level=trust_level,
            action_type=intent_action,
            target_resource="chat",
            decision="denied" if blocked else "allowed",
            reason=block_reason or advisory or "chat message",
        )
        if not audit_event_id:
            logger.warning("Audit write may have failed (degraded): no event_id returned")
    except Exception as _audit_exc:
        logger.warning("Audit write failed (degraded): %s", _audit_exc)
        audit_event_id = None

    return PreflightResult(
        interlocutor_id=_id,
        trust_level=trust_level,
        response_mode=response_mode,
        intent_action=intent_action,
        intent_risk=intent_risk,
        blocked=blocked,
        block_reason=block_reason,
        requires_clarification=ambiguous and is_sensitive,
        clarification_question=clarification_question if (ambiguous and is_sensitive) else None,
        advisory=advisory,
        system_prompt_enrichment=profile_summary,
        audit_event_id=audit_event_id,
    )


def extract_interlocutor_id(
    payload: dict | None = None,
    headers: dict | None = None,
) -> str | None:
    """Extract interlocutor_id from request payload or headers."""
    if payload:
        v = payload.get("interlocutor_id") or payload.get("user_id")
        if v:
            return str(v)
    if headers:
        # Headers are case-insensitive in HTTP but dict lookup is case-sensitive
        for key in ("x-igris-interlocutor", "X-IGRIS-Interlocutor", "X-Igris-Interlocutor"):
            v = headers.get(key)
            if v:
                return str(v)
    return None
