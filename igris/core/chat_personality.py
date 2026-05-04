"""IGRIS-aware chat personality and capability grounding.

Ensures chat responses reflect what IGRIS actually is and can do,
rather than sounding like generic ChatGPT. Provides:

1. IGRIS identity system prompt
2. Intent detection for common operational questions
3. Capability-grounded responses (what IGRIS can/cannot do safely)
4. Never suggests free shell as primary action
5. Never claims unrestricted access
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any

# ---------------------------------------------------------------------------
# IGRIS Identity System Prompt
# ---------------------------------------------------------------------------

IGRIS_SYSTEM_PROMPT = """Sei IGRIS_GPT, un agente di ingegneria software locale installato sulla macchina dell'utente.

IDENTITÀ:
- Sei un agente operativo, non un chatbot generico.
- Operi tramite API sicure, command_id approvati e workflow controllati.
- Non hai accesso a shell libera. Ogni azione passa per endpoint sicuri con safety gates.
- Le tue capacità sono definite dai tuoi endpoint e command_id, non da accesso illimitato.

CAPACITÀ ATTUALI:
- Gestione missioni: creare, pianificare, materializzare task
- Task engine: creare, selezionare, completare, bloccare task
- Patch workflow: proporre, validare, preview diff, applicare (gated)
- Git locale: status, diff, branch, commit proposal, PR prepare
- GitHub gated: PR create solo con approval I_APPROVE_GITHUB_WRITE
- Chat: local LLM (phi4-mini), OpenAI fallback, deterministico
- Memory: eventi decisione/fallimento, analisi, lesson learned
- Diagnostics: starvation, blocked, family health, recovery
- Loop autonomo: step controllati con stop conditions
- Vast.ai: solo mock/dry-run, provisioning richiede I_APPROVE_VASTAI_COSTS
- Test: esecuzione tramite command_id run_tests
- File: browse/preview (no .env, no path traversal)
- System info: status, readiness, routing, project context

REGOLE DI RISPOSTA:
- Rispondi come IGRIS, non come ChatGPT generico.
- Spiega cosa puoi fare tramite i tuoi endpoint/API sicuri.
- Se non puoi fare qualcosa, spiega perché e suggerisci un'alternativa sicura.
- Non suggerire mai "esegui questo comando nella shell" come prima opzione.
- Non affermare mai di avere accesso illimitato.
- Preferisci "posso fare X tramite endpoint Y" a "non posso fare X".
- Se manca una capability, suggerisci di creare una task per implementarla.
- Rispondi in modo conciso e operativo.
- Non esporre mai segreti, token o variabili d'ambiente."""


# ---------------------------------------------------------------------------
# Capability categories
# ---------------------------------------------------------------------------

CAPABILITIES: Dict[str, Dict[str, Any]] = {
    "missions": {
        "label": "Missioni e Planning",
        "description": "Creare missioni, generare piani, materializzare task",
        "endpoints": ["/api/missions", "/api/missions/{id}/plan", "/api/missions/{id}/materialize-tasks"],
        "safe": True,
    },
    "tasks": {
        "label": "Task Management",
        "description": "Creare, listare, completare, bloccare task",
        "endpoints": ["/api/tasks", "/api/tasks/{id}", "/api/tasks/{id}/complete"],
        "safe": True,
    },
    "patches": {
        "label": "Patch Workflow",
        "description": "Proporre, validare, preview diff, generare patch LLM",
        "endpoints": ["/api/patches/propose", "/api/patches/{id}/validate", "/api/patches/generate"],
        "safe": True,
    },
    "git_local": {
        "label": "Git Locale",
        "description": "Status, diff, branch, commit proposal, PR summary",
        "endpoints": ["/api/git/status", "/api/git/diff", "/api/git/branches", "/api/git/commit-proposal"],
        "safe": True,
    },
    "github_gated": {
        "label": "GitHub (Gated)",
        "description": "PR prepare, PR create con approval",
        "endpoints": ["/api/github/pr/prepare", "/api/github/pr/create"],
        "approval_required": "I_APPROVE_GITHUB_WRITE",
        "safe": True,
    },
    "chat": {
        "label": "Chat e LLM",
        "description": "Chat locale phi4-mini, fallback OpenAI, deterministico",
        "endpoints": ["/api/chat/stream"],
        "safe": True,
    },
    "memory": {
        "label": "Memory e Analisi",
        "description": "Eventi, fallimenti, decisioni, saturazione, lesson learned",
        "endpoints": ["/api/memory/failures", "/api/memory/decisions", "/api/memory/analyze"],
        "safe": True,
    },
    "diagnostics": {
        "label": "Diagnostics",
        "description": "Starvation, blocked tasks, family health, recovery",
        "endpoints": ["/api/diagnostics", "/api/diagnostics/summary"],
        "safe": True,
    },
    "loop": {
        "label": "Loop Autonomo",
        "description": "Step controllati con stop conditions e decision reports",
        "endpoints": ["/api/loop/step", "/api/loop/status", "/api/decision-reports"],
        "safe": True,
    },
    "tests": {
        "label": "Test Execution",
        "description": "Esecuzione test tramite command_id sicuro",
        "command_ids": ["run_tests"],
        "safe": True,
    },
    "files": {
        "label": "File Browser",
        "description": "Tree e preview sicuri (no .env, no path traversal)",
        "endpoints": ["/api/files/tree", "/api/files/preview"],
        "safe": True,
    },
    "system": {
        "label": "System Status",
        "description": "Health, readiness, routing, project context",
        "endpoints": ["/api/health", "/api/readiness", "/api/status", "/api/routing/explain"],
        "safe": True,
    },
    "vastai": {
        "label": "Vast.ai GPU (Gated)",
        "description": "Estimate, offers search, provision (solo con approval)",
        "endpoints": ["/api/vastai/status", "/api/vastai/estimate", "/api/vastai/provision"],
        "approval_required": "I_APPROVE_VASTAI_COSTS",
        "safe": True,
    },
}


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

_INTENTS: List[Dict[str, Any]] = [
    {
        "keywords": ["rete", "network", " ip ", "porta", "port", "connessione", "connection"],
        "intent": "network_info",
    },
    {
        "keywords": ["github", "push", "pull request", "pr ", "merge", "remote"],
        "intent": "github_access",
    },
    {
        "keywords": ["cosa puoi fare", "what can you do", "capabilities", "capacità",
                     "aiuto", "cosa sai fare", "funzionalità"],
        "intent": "capabilities",
    },
    {
        "keywords": ["shell", "terminale", "terminal", "comando", "command", "bash", "exec"],
        "intent": "shell_request",
    },
    {
        "keywords": ["git status", "git diff", "branch", "commit"],
        "intent": "git_local",
    },
    {
        "keywords": ["test", "pytest", "run tests", "esegui test"],
        "intent": "testing",
    },
    {
        "keywords": ["patch", "modifica", "fix "],
        "intent": "patching",
    },
    {
        "keywords": ["mission", "missione", "piano", "plan", "obiettivo"],
        "intent": "missions",
    },
    {
        "keywords": ["memory", "memoria", "fallimento", "fallimenti", "failure", "decisione"],
        "intent": "memory",
    },
    {
        "keywords": ["macchina", "machine", "host", "server", "sistema", "system info",
                     "cpu", " ram ", "disco", "disk", "uptime"],
        "intent": "machine_info",
    },
    {
        "keywords": ["help"],
        "intent": "capabilities",
    },
]


def detect_intent(message: str) -> Optional[str]:
    """Detect user intent from message text."""
    lower = message.lower()
    for entry in _INTENTS:
        for kw in entry["keywords"]:
            if kw in lower:
                return entry["intent"]
    return None


# ---------------------------------------------------------------------------
# Grounded responses
# ---------------------------------------------------------------------------

_GROUNDED_RESPONSES: Dict[str, str] = {
    "machine_info": (
        "Posso mostrarti lo stato visibile da IGRIS.\n"
        "Non uso shell libera, ma posso usare endpoint e command_id sicuri.\n\n"
        "Disponibile ora:\n"
        "- /api/status — stato del server\n"
        "- /api/readiness — readiness con provider/model check\n"
        "- /api/routing/explain — routing e disponibilità provider\n"
        "- /api/git/status — stato del repository\n"
        "- command_id: git_status, git_log, run_tests, list_files\n\n"
        "Per info OS/CPU/RAM/GPU complete serve un endpoint dedicato `system_info`.\n"
        "Posso creare una task per implementarlo in modo sicuro."
    ),
    "network_info": (
        "Le informazioni di rete dettagliate non sono esposte per sicurezza.\n\n"
        "Disponibile ora:\n"
        "- /api/status — host e porta del server IGRIS\n"
        "- /api/readiness — raggiungibilità Ollama e provider configurati\n"
        "- /api/routing/explain — stato routing e disponibilità endpoint\n\n"
        "Non espongo IP privati, interfacce o configurazione di rete completa.\n"
        "Per diagnostica di rete avanzata servirebbe un command_id gated dedicato."
    ),
    "github_access": (
        "Posso lavorare con Git locale e con il workflow GitHub gated.\n\n"
        "Ora posso:\n"
        "- leggere git status/diff/branch locali (/api/git/status, /api/git/diff)\n"
        "- generare commit proposal (/api/git/commit-proposal)\n"
        "- preparare PR dry-run (/api/github/pr/prepare)\n"
        "- creare PR solo con approval `I_APPROVE_GITHUB_WRITE`\n\n"
        "Non posso:\n"
        "- fare push/merge automatici\n"
        "- accedere a GitHub remoto senza token configurato\n"
        "- fare force push o merge su branch protetti\n\n"
        "Il workflow è: commit proposal → safety check → PR prepare → gated PR create."
    ),
    "capabilities": (
        "Sono IGRIS_GPT, un agente di ingegneria software installato localmente.\n\n"
        "Le mie capacità operative:\n\n"
        "🔧 **Workflow**\n"
        "- Missioni: creare, pianificare, materializzare task\n"
        "- Task: gestione completa con selezione intelligente\n"
        "- Patch: proporre, validare, preview diff, generare con LLM\n"
        "- Loop: step autonomi controllati con stop conditions\n\n"
        "📂 **Codice**\n"
        "- Git locale: status, diff, branch, commit proposal\n"
        "- GitHub: PR prepare/create (gated con approval)\n"
        "- File: browse e preview sicuri\n"
        "- Test: esecuzione tramite command_id\n\n"
        "🧠 **Intelligence**\n"
        "- Chat: LLM locale (phi4-mini), fallback, context-enriched\n"
        "- Memory: decisioni, fallimenti, analisi pattern\n"
        "- Diagnostics: starvation, health, recovery\n"
        "- Decision reports: per ogni loop cycle\n\n"
        "🔒 **Safety**\n"
        "- Nessuna shell libera\n"
        "- Tutti gli endpoint sono sicuri o richiedono approval\n"
        "- Segreti sempre redatti\n"
        "- GitHub/Vast.ai solo con approvazione esplicita"
    ),
    "testing": (
        "Posso eseguire test tramite il workflow sicuro di IGRIS.\n\n"
        "Disponibile:\n"
        "- command_id `run_tests` — esegue pytest\n"
        "- /api/reports/recent — ultimi risultati\n"
        "- /api/diagnostics — health delle task families\n\n"
        "I risultati vengono registrati nel sistema di memory e decision reports."
    ),
    "git_local": (
        "Posso accedere al repository Git locale in modo sicuro.\n\n"
        "Endpoint disponibili:\n"
        "- /api/git/status — stato working directory\n"
        "- /api/git/diff — diff con redazione segreti\n"
        "- /api/git/branches — lista branch\n"
        "- /api/git/commit-proposal — proposta commit (dry-run)\n"
        "- /api/git/safety-check — analisi pre-commit\n"
        "- /api/git/pr-summary — summary vs base branch"
    ),
    "patching": (
        "Posso gestire modifiche al codice tramite il patch workflow sicuro.\n\n"
        "Workflow:\n"
        "1. /api/patches/generate — genera patch con LLM (proposta)\n"
        "2. /api/patches/propose — crea proposta formale\n"
        "3. /api/patches/{id}/validate — validazione safety\n"
        "4. /api/patches/{id} — preview diff\n"
        "5. /api/patches/{id}/apply — applicazione (gated)\n\n"
        "Le patch non vengono mai applicate automaticamente.\n"
        "Ogni patch passa per validazione: no segreti, no path traversal, no binari."
    ),
    "missions": (
        "Posso gestire il ciclo completo delle missioni.\n\n"
        "Workflow:\n"
        "1. POST /api/missions — crea missione\n"
        "2. POST /api/missions/{id}/plan — genera piano (deterministico o LLM)\n"
        "3. POST /api/missions/{id}/materialize-tasks — crea task\n"
        "4. POST /api/loop/step — esegui step del loop\n"
        "5. GET /api/decision-reports — consulta decision reports\n\n"
        "Posso pianificare in modo deterministico o con LLM (safe schema)."
    ),
    "memory": (
        "Posso accedere alla memoria operativa di IGRIS.\n\n"
        "Disponibile:\n"
        "- /api/memory/failures — fallimenti recenti\n"
        "- /api/memory/decisions — decisioni recenti\n"
        "- /api/memory/saturation — famiglie saturate e vincoli\n"
        "- /api/memory/analyze — analisi pattern (advisory)\n"
        "- /api/memory/lessons — lesson learned\n\n"
        "La memoria è advisory-only: informa ma non esegue azioni autonomamente."
    ),
    "shell_request": (
        "IGRIS non dispone di shell libera per ragioni di sicurezza.\n\n"
        "Alternative sicure disponibili:\n"
        "- command_id approvati: git_status, git_log, run_tests, list_files\n"
        "- Endpoint API per operazioni specifiche\n"
        "- Patch workflow per modifiche al codice\n"
        "- Task system per azioni pianificate\n\n"
        "Se serve un'operazione non coperta, posso creare una task per aggiungere "
        "un command_id sicuro dedicato."
    ),
}


def get_grounded_response(intent: str) -> Optional[str]:
    """Get a capability-grounded response for a detected intent."""
    return _GROUNDED_RESPONSES.get(intent)


def get_capability_summary() -> Dict[str, Any]:
    """Return structured capability summary."""
    return {
        "identity": "IGRIS_GPT — Local Engineering Agent",
        "version": "v0.5-real-world-candidate",
        "capabilities": CAPABILITIES,
        "safety": {
            "no_free_shell": True,
            "secrets_redacted": True,
            "approval_gates": ["I_APPROVE_GITHUB_WRITE", "I_APPROVE_VASTAI_COSTS"],
            "no_auto_merge": True,
            "no_auto_push": True,
        },
    }


# ---------------------------------------------------------------------------
# Suggested Actions per Intent
# ---------------------------------------------------------------------------

@dataclass
class SuggestedAction:
    """A safe action that IGRIS can suggest to the user."""
    label: str
    description: str
    endpoint: str
    method: str = "GET"
    risk: str = "safe"
    approval_required: bool = False
    command_id: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "label": self.label,
            "description": self.description,
            "endpoint": self.endpoint,
            "method": self.method,
            "risk": self.risk,
            "approval_required": self.approval_required,
        }
        if self.command_id:
            d["command_id"] = self.command_id
        if self.payload:
            d["payload"] = self.payload
        return d


_INTENT_ACTIONS: Dict[str, List[SuggestedAction]] = {
    "machine_info": [
        SuggestedAction("Show Status", "Stato corrente del server IGRIS", "/api/status"),
        SuggestedAction("Show Readiness", "Readiness con provider/model check", "/api/readiness"),
        SuggestedAction("Show Project Context", "Contesto progetto corrente", "/api/project/context"),
        SuggestedAction("Show Git Status", "Stato repository Git locale", "/api/git/status"),
        SuggestedAction("Create system_info task", "Crea task per implementare endpoint system_info",
                       "/api/tasks", method="POST",
                       payload={"title": "Add safe system_info endpoint", "family": "code"}),
    ],
    "network_info": [
        SuggestedAction("Show Status", "Host e porta del server", "/api/status"),
        SuggestedAction("Show Readiness", "Raggiungibilità provider", "/api/readiness"),
        SuggestedAction("Show Routing", "Stato routing e provider", "/api/routing/explain"),
    ],
    "github_access": [
        SuggestedAction("Show Git Status", "Stato working directory", "/api/git/status"),
        SuggestedAction("Show Git Diff", "Diff con redazione segreti", "/api/git/diff"),
        SuggestedAction("Generate PR Summary", "Summary vs base branch", "/api/git/pr-summary"),
        SuggestedAction("Prepare PR Dry Run", "Prepara PR senza effetti remoti",
                       "/api/github/pr/prepare", method="POST", risk="gated",
                       approval_required=True),
    ],
    "capabilities": [
        SuggestedAction("Show Capabilities", "Lista completa capacità IGRIS", "/api/chat/capabilities"),
        SuggestedAction("Show Status", "Stato server", "/api/status"),
        SuggestedAction("Show Readiness", "Provider e model check", "/api/readiness"),
    ],
    "testing": [
        SuggestedAction("Run Tests", "Esegui pytest tramite command_id sicuro",
                       "/api/commands/run_tests/run", method="POST", command_id="run_tests"),
        SuggestedAction("Show Recent Reports", "Ultimi risultati test", "/api/reports/recent"),
        SuggestedAction("Show Diagnostics", "Health delle task families", "/api/diagnostics/summary"),
    ],
    "git_local": [
        SuggestedAction("Show Git Status", "Stato working directory", "/api/git/status"),
        SuggestedAction("Show Git Diff", "Diff con redazione segreti", "/api/git/diff"),
        SuggestedAction("Show Branches", "Lista branch", "/api/git/branches"),
        SuggestedAction("Safety Check", "Analisi pre-commit", "/api/git/safety-check"),
    ],
    "patching": [
        SuggestedAction("List Patches", "Proposte patch esistenti", "/api/patches"),
        SuggestedAction("Generate Patch", "Genera patch con LLM (proposta)",
                       "/api/patches/generate", method="POST", risk="safe"),
        SuggestedAction("Show Git Diff", "Diff corrente", "/api/git/diff"),
    ],
    "missions": [
        SuggestedAction("List Missions", "Missioni esistenti", "/api/missions"),
        SuggestedAction("Show Decision Reports", "Decision reports recenti", "/api/decision-reports"),
        SuggestedAction("Show Loop Status", "Stato del loop autonomo", "/api/loop/status"),
    ],
    "memory": [
        SuggestedAction("Show Failures", "Fallimenti recenti", "/api/memory/failures"),
        SuggestedAction("Show Decisions", "Decisioni recenti", "/api/memory/decisions"),
        SuggestedAction("Show Saturation", "Famiglie saturate", "/api/memory/saturation"),
        SuggestedAction("Analyze Memory", "Analisi pattern (advisory)",
                       "/api/memory/analyze", method="POST"),
    ],
    "shell_request": [
        SuggestedAction("Show Available Commands", "Command_id sicuri disponibili",
                       "/api/commands"),
        SuggestedAction("Show Git Status", "Stato repo tramite API sicura", "/api/git/status"),
        SuggestedAction("Run Tests", "Esegui test tramite command_id",
                       "/api/commands/run_tests/run", method="POST", command_id="run_tests"),
        SuggestedAction("Create Task", "Crea task per nuova capability",
                       "/api/tasks", method="POST",
                       payload={"title": "Add safe command_id", "family": "code"}),
    ],
}


def get_suggested_actions(intent: str) -> List[Dict[str, Any]]:
    """Get suggested safe actions for a detected intent."""
    actions = _INTENT_ACTIONS.get(intent, [])
    return [a.to_dict() for a in actions]


def get_all_safe_actions() -> Dict[str, List[Dict[str, Any]]]:
    """Get all available suggested actions grouped by intent."""
    return {k: [a.to_dict() for a in v] for k, v in _INTENT_ACTIONS.items()}


def enrich_chat_response(message: str, base_response: str) -> str:
    """Enrich a chat response with IGRIS-aware grounding if applicable.

    If user message matches a known intent, prepend grounded response.
    Otherwise return base_response unchanged.
    """
    intent = detect_intent(message)
    if intent is None:
        return base_response

    grounded = get_grounded_response(intent)
    if grounded is None:
        return base_response

    return grounded
