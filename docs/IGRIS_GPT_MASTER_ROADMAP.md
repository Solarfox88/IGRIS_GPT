# IGRIS_GPT — Master Roadmap Definitiva

Questa roadmap è il riferimento operativo per portare **IGRIS_GPT** alla versione definitiva: un agente personale di engineering capace di sostituire l'utente nei compiti tecnici assegnati, lavorare in autonomia su macchina locale, repository, siti web, VPS/server, GitHub, deploy, test, debugging, manutenzione e report finale.

La roadmap integra le migliori idee osservate da tre fonti di ispirazione:

- **Devin**: comportamento operativo end-to-end: capire un task, esplorare, pianificare, modificare, eseguire, correggere, testare e consegnare.
- **Ruflo / Claude Flow**: orchestrazione, agenti specializzati, router, memoria, hook, plugin, provider routing, doctor/verify, dashboard, security hardening.
- **OpenHands**: workspace operativo, terminale, file editing, browser, loop observe-act, ambiente di esecuzione controllato; da non ereditare invece crash, fragilità e accoppiamento eccessivo.

Documenti operativi correlati (phase-2bis):
- [Issue #638 — Integration Interfaces and Gap Map](./ISSUE_638_INTEGRATION_INTERFACES_GAP_MAP.md)
- [Issue #639 — Integration Gap Matrix](./ISSUE_639_INTEGRATION_GAP_MATRIX.md)
- [Master Plan V2 — Role Routing](./MASTER_PLAN_V2_ROLE_ROUTING.md)

---

## 0. Visione finale

IGRIS_GPT deve diventare un **AI Engineering Operator personale**, installabile su Ubuntu, VM, VPS o macchina locale, capace di ricevere un obiettivo e lavorare come sostituto operativo dell'utente su repo, siti, server, deploy, debugging, test, GitHub, manutenzione e report finale.

Esempi di missioni target:

- "crea questo sito e mettilo online su questa VPS";
- "sistema questa repo, testa e apri una PR";
- "controlla perché il sito è giù e correggi";
- "configura dominio, nginx, SSL, Docker e backup";
- "analizza una codebase, trova bug, applica fix e consegna report";
- "gestisci server, deploy, aggiornamenti e rollback".

Il ciclo operativo target è:

```text
Understand → Plan → Act → Observe → Fix → Verify → Deliver → Remember
```

Con governance:

```text
Safety → Cost Control → Rollback → Anti-loop → Teacher/Governor → Audit Trail
```

---

## 1. Principi non negoziabili

### 1.1 Autonomia reale
IGRIS non deve limitarsi a suggerire. Deve poter eseguire compiti concreti sulla macchina dove è installato o su server autorizzati.

### 1.2 Potenza governata
IGRIS deve poter agire liberamente, ma non ciecamente. Ogni azione passa da policy, rischio, rollback, audit e verifica.

### 1.3 Local-first e server-capable
IGRIS deve funzionare localmente, ma deve anche operare su VPS/server tramite SSH, Docker, nginx, systemd, browser testing, GitHub e provider cloud.

### 1.4 Provider-agnostic
IGRIS non deve dipendere da un solo LLM o provider. Ogni uso di LLM passa dal **Model Orchestrator**. DeepSeek può essere un provider consigliato per costo/qualità, ma non è l'architettura. L'architettura è l'orchestratore.

### 1.5 Anti-loop strutturale
Dopo ripetizioni semantiche, IGRIS deve cambiare strategia o richiedere un differenziatore concreto e verificabile.

### 1.6 Deliverable eccellente
Ogni missione conclusa deve produrre risultato, prove, report, modifiche tracciate, eventuale rollback e memoria riusabile.

### 1.7 Stabilità superiore a OpenHands
Ogni componente deve degradare in modo controllato. Nessun crash non diagnosticato deve interrompere missioni lunghe senza report e recovery.

---

## 2. Stato post-bootstrap

I 6 epic bootstrap fondamentali sono stati proposti/completati tramite PR dedicate:

| Epic | PR | Capacità |
|---|---:|---|
| #39 Doctor/Verify/Crash Recovery | #52 | diagnostica, verify, config validation, crash reports |
| #40 Mission Controller | #53 | missioni persistenti multi-step |
| #42 Safety/Rollback/Autonomy Policy | #54 | risk, approval modes, rollback, safety event log |
| #41 Real Local/Server Tool Runtime | #55 | shell/fs/git/docker/nginx/systemd/http/test/hosts governati |
| #43 GOAP-like Planner | #56 | precondizioni, effetti, world state, replanning |
| #46 Teacher/Governor Anti-Loop | #57 | family saturation, dedup, forced strategy shift |

Questi componenti costruiscono il corpo operativo di IGRIS: missioni, safety, rollback, tool, planner, governor e diagnostica. Il prossimo gap critico è il **loop cognitivo operativo**: un ciclo in cui IGRIS costruisce contesto, invoca un LLM tramite Model Orchestrator, riceve azioni strutturate, le valida, le esegue tramite tool governati, osserva risultati, aggiorna stato/memoria e continua finché la missione è verificata o bloccata con diagnosi.

---

## 3. Architettura definitiva di IGRIS

IGRIS_GPT deve prevedere da subito l'architettura completa della versione definitiva, anche se l'implementazione procede per fasi. Non vogliamo un sistema minimo che poi diventa incoerente. Vogliamo una mappa completa e uno sviluppo incrementale.

```text
Goal Intake / User Mission
  ↓
Mission Controller
  ↓
Agent Registry + Coordinator
  ↓
State Inspector + Context Manager + Code Navigation
  ↓
GOAP Planner + Agent Reasoning Loop
  ↓
Model Orchestrator
  ↓
Structured Action Proposal
  ↓
Command Risk Engine + Safety Policy + Rollback Resolver
  ↓
Tool Runtime / DevOps Runtime / GitHub Runtime / Browser Runtime
  ↓
Verifier + Postcheck + Healthcheck
  ↓
Memory / Lessons / Outcome Store
  ↓
Teacher / Governor / Replanner
  ↓
Final Reporter / Dashboard / Artifacts
```

### 3.1 Componenti definitivi

| Componente | Responsabilità |
|---|---|
| Mission Controller | Mantiene obiettivo, stato, piano, progressi, pause/resume, stop conditions, report finale |
| Agent Registry | Definisce agenti/ruoli, permessi, tool, rischi, responsabilità, escalation e futura evoluzione multi-agent |
| Coordinator | Mantiene focus, assegna modalità/ruolo, previene drift e valida allineamento al goal |
| Agent Reasoning Loop | Ciclo cognitivo: contesto → LLM → azione strutturata → safety → tool → osservazione → memoria → prossimo step |
| Context Manager | Decide cosa vede il modello: goal, stato, file rilevanti, errori, memoria, azioni recenti, token budget |
| Code Navigation | Cerca codice, file, simboli, range di file, repo map, riferimenti e contesto tecnico |
| GOAP Planner | Fornisce stato, precondizioni, effetti, success criteria e replanning strutturale |
| Model Orchestrator | Sceglie modello/provider per reasoning, risk review, chat, memory, review, coding, fallback e cost control |
| Command Risk Engine | Classifica comandi/azioni, riconosce rischio, usa regole + LLM reviewer, applica policy e precheck |
| Safety / Policy Layer | Blocca o consente azioni in base a rischio, mode, host, path, secrets, approval e policy |
| Rollback Manager | Prepara backup, diff snapshot, restore, rollback command e verifica rollback |
| Tool Runtime | Esegue azioni locali/server: shell, filesystem, git, docker, nginx, systemd, http, test, ssh |
| GitHub Delivery | Branch, commit, PR, CI reading, issue updates, review gate, no unsafe push |
| DevOps/VPS Manager | Server registry, deploy patterns, nginx, Docker, systemd, SSL, logs, healthcheck, rollback |
| Browser/UI Testing | Playwright/browser checks, screenshot, console errors, user-flow smoke tests |
| Verifier | Verifica success criteria: test, lint, health, HTTP, SSL, logs, PR, artifacts |
| Memory / Learning | Salva outcome, failure, decisions, lessons, server facts, repo facts, deployment patterns |
| Teacher/Governor | Rileva loop, saturazioni, duplicati, fallback incoerenti, impone strategy shift |
| Dashboard / Control Room | Stato missione, piano, step corrente, rischio, rollback, logs, costi, memory, artifacts |
| Benchmark System | Misura capacità reali: bugfix, feature, test repair, deploy, rollback, PR, browser, server recovery |
| Plugin/Capability System | Estensibilità futura senza rendere monolitico il core |

---

## 4. Agent Registry definitivo

IGRIS deve prevedere un **Agent Registry** completo già nell'architettura definitiva. Questo non significa introdurre subito uno swarm parallelo complesso. Significa definire ruoli, responsabilità, tool, limiti e possibilità di evoluzione.

### 4.1 Implementazione iniziale

La prima implementazione può usare un solo Agent Reasoning Loop attivo, che assume ruoli/modalità dal registry.

```text
Single Agent Reasoning Loop
  + ruolo corrente dal registry
  + tool permessi dal ruolo
  + policy per rischio/host/path
  + prompt specifico per modalità
```

### 4.2 Evoluzione futura

L'architettura deve già prevedere la possibilità di evolvere verso multi-agent controllato:

- Coder separato da Reviewer;
- DevOps separato da Security Guard;
- Memory Manager come servizio dedicato;
- Cost Guardian come gate trasversale;
- Coordinator che orchestra agenti specialistici;
- task delegation per missioni lunghe;
- audit su quale agente/ruolo ha proposto o validato una decisione.

### 4.3 Agenti/ruoli minimi definitivi

| Agente/Ruolo | Responsabilità | Tool preferiti | Note di safety |
|---|---|---|---|
| Coordinator | Tiene focus, missione, piano, step corrente | mission, plan, state, report | può bloccare drift |
| Planner | Scompone obiettivi, aggiorna piano, valuta precondizioni | goap, state, memory | non esegue azioni rischiose |
| Researcher | Esplora repo, docs, log, server facts | search, read, grep, logs | read-only di default |
| Coder | Modifica codice e file workspace | read, write, patch, test | no system/server tools |
| Tester | Esegue test, interpreta failure, propone verifiche | run_tests, logs, read | write solo se autorizzato |
| Reviewer | Controlla diff, qualità, regressioni, secrets | git_diff, tests, secret_scan | può bloccare delivery |
| DevOps | Deploy, server, nginx, Docker, systemd, SSL | ssh, docker, nginx, systemd, http | rollback obbligatorio high risk |
| Security Guard | Valuta rischio, segreti, policy, path, comandi | risk, secrets, policy | può bloccare qualsiasi azione |
| Memory Manager | Salva/recupera lezioni, failure, pattern | memory, retrieval | non esegue shell |
| Cost Guardian | Seleziona provider, budget, escalation | routing, cost | può bloccare modelli costosi |
| Reporter | Produce report finale, artifacts, next steps | reports, logs, artifacts | no execution |

---

## 5. Model Orchestrator

Tutti gli usi di LLM devono passare dal **Model Orchestrator**. Nessun componente deve chiamare direttamente DeepSeek, OpenAI, Anthropic, Ollama o altro provider.

### 5.1 Compiti del Model Orchestrator

- scegliere modello/provider in base a task type, ruolo, rischio, budget, privacy, context size e qualità richiesta;
- usare modelli locali quando sufficienti;
- usare provider economici cloud quando conveniente;
- usare modelli forti per architecture, debugging difficile, deploy critico, security review;
- degradare in modo onesto se nessun modello adatto è disponibile;
- registrare costo, latenza, provider, fallback, outcome;
- supportare provider OpenAI-compatible.

### 5.2 Profili modello

| Profilo | Uso | Esempi |
|---|---|---|
| deterministic | safety, policy, routing banale, checks | nessun LLM |
| local_light | chat, sintesi, classificazione semplice | Ollama phi/qwen/llama |
| local_coder | code reasoning locale se hardware basta | qwen-coder/deepseek-coder locale |
| cheap_cloud_reasoning | reasoning/coding economico | DeepSeek API o provider equivalente |
| strong_cloud_reasoning | debugging difficile, architettura, review critica | OpenAI/Anthropic/Gemini forte |
| risk_reviewer | analisi rischio medium/high/unknown | scelto dal Model Orchestrator |
| embedding_memory | retrieval semantico | embeddings locali/cloud |

DeepSeek può essere un provider consigliato per il profilo `cheap_cloud_reasoning`, ma l'architettura resta provider-agnostic.

---

## 6. Command Risk Engine definitivo

IGRIS deve supportare shell completa governata. L'agente può proporre comandi non previsti, ma nessun comando raw viene eseguito direttamente. Tutte le azioni passano da normalizzazione, parsing, rischio, policy, rollback, approval, guarded execution e postcheck.

### 6.1 Politica tool-first

Ordine preferito per ogni azione:

1. **Tool strutturato**: `run_tests`, `read_file_range`, `write_file`, `git_status`, `http_check`, ecc.
2. **Template parametrizzato**: `python_pytest`, `npm_install`, `docker_compose_logs`, ecc.
3. **Raw shell proposal**: permessa come escape hatch, mai eseguita senza risk engine.

### 6.2 Pipeline del Command Risk Engine

```text
Action Proposal
  ↓
Action Normalizer
  ↓
Structured Tool available?
  ├─ yes → Tool Policy
  └─ no  → Shell Parser
            ↓
Deterministic Risk Classifier
  ↓
Contextual Policy Engine
  ↓
LLM Risk Reviewer when needed
  ↓
Rollback Requirement Resolver
  ↓
Approval Gate
  ↓
Guarded Executor
  ↓
Postcheck / Verifier
  ↓
Safety Event Log + Memory
```

### 6.3 Parsing e segnali da riconoscere

Il parser deve riconoscere almeno:

- `sudo`, `su`, privilege escalation;
- `rm`, `delete`, `unlink`, `git clean`, `git reset --hard`;
- `chmod`, `chown`, permission changes;
- `systemctl`, `service`, `journalctl`;
- `docker`, `docker compose`, `kubectl` futuro;
- `nginx`, `apache`, `certbot`;
- `apt`, `pip`, `npm`, `pnpm`, `yarn`;
- `git push`, `git force`, branch main/master;
- `curl | bash`, `wget | sh`, remote script execution;
- pipes, redirection, subshell, `&&`, `||`;
- absolute paths, paths outside workspace, wildcards;
- network calls;
- database commands and migrations;
- firewall/DNS commands;
- `.env`, secrets, keys, tokens.

### 6.4 Risk classes

| Classe | Esempi | Default |
|---|---|---|
| LOW | ls, pwd, grep, git status, file read, focused test | auto se policy ok |
| MEDIUM | workspace write, dependency install, git commit, test scripts | auto or LLM reviewer if ambiguous/raw |
| HIGH | service restart, deploy, docker down/up, nginx config, git push | rollback + reviewer + policy |
| CRITICAL | delete production, DB drop, firewall/DNS, secrets write, force push | block or explicit approval |
| UNKNOWN | parse incerto, comando complesso/ambiguo | reviewer + restrictive policy |

### 6.5 LLM Risk Reviewer

L'LLM reviewer è un secondo parere, non il decisore finale. La decisione finale resta alla policy di IGRIS.

Usarlo per:

- MEDIUM se comando raw, ambiguo, modifica dipendenze/config, usa network, o esce dai tool strutturati;
- HIGH sempre salvo casi già bloccati deterministicamente;
- CRITICAL per spiegazione/mitigazione, ma non per autorizzare automaticamente;
- UNKNOWN sempre.

Output JSON atteso:

```json
{
  "risk_assessment": "medium|high|critical|unknown",
  "reasons": [],
  "affected_paths": [],
  "affected_services": [],
  "requires_rollback": true,
  "recommended_prechecks": [],
  "recommended_postchecks": [],
  "safer_alternative": null,
  "should_execute": false
}
```

### 6.6 Precheck e postcheck

Esempi obbligatori:

- nginx/systemd: backup config, config test, service existence, rollback command;
- git push: no main/master, secret scan, diff review, branch status;
- docker compose: `docker compose config`, logs, healthcheck, rollback plan;
- dependency install: lockfile handling, workspace scope, package manager detection;
- file overwrite: backup/diff snapshot;
- server action: host registry, allowed paths/services, environment classification.

---

## 7. Agent Action Schema & Prompt Contract

Prima di implementare il loop cognitivo, serve un contratto stabile fra LLM e IGRIS.

### 7.1 Principi

- L'LLM non esegue: propone azioni strutturate.
- IGRIS valida, classifica, esegue, verifica e registra.
- Ogni azione deve avere motivo, expected effect, confidence, fallback, success check.
- Il prompt deve mostrare solo il contesto utile, non rumore.
- Il modello deve poter dire `ask_user`, `blocked`, `need_more_context`, `finish`.

### 7.2 Action types minimi

- `search_code`
- `find_files`
- `list_directory`
- `read_file_range`
- `write_file`
- `propose_patch`
- `apply_patch`
- `run_tests`
- `git_status`
- `git_diff`
- `shell_template`
- `raw_shell_proposal`
- `http_check`
- `update_plan`
- `record_memory`
- `ask_user`
- `finish`
- `blocked`

### 7.3 Schema concettuale

```json
{
  "mode": "coder|tester|reviewer|devops|planner|security|reporter",
  "action_type": "read_file_range",
  "reason": "Need to inspect existing FastAPI route pattern",
  "parameters": {},
  "expected_effect": "Find correct place to add /api/ping",
  "risk_hint": "low|medium|high|critical|unknown",
  "confidence": 0.82,
  "required_preconditions": [],
  "success_check": {},
  "fallback_if_blocked": null
}
```

---

## 8. Nuova fase P0 post-bootstrap: accendere il loop cognitivo

Dopo i 6 epic bootstrap, la priorità non è aggiungere altra architettura decorativa. La priorità è collegare i pezzi esistenti con un cervello operativo governato.

### Epic P0-A — Agent Action Schema, Prompt Contract and definitive architecture alignment

**Obiettivo:** definire il contratto completo fra LLM, Agent Registry, Model Orchestrator, tool runtime, risk engine, safety, rollback, memory e governor.

**Include:**

- action schema JSON;
- prompt template per reasoning loop;
- modalità/agenti dal Agent Registry;
- policy tool-first/template/raw shell;
- stop conditions;
- error handling;
- finish criteria;
- ask_user/escalation;
- esempi per almeno 10 scenari;
- design del Command Risk Engine v2;
- design del Model Orchestrator per reasoning/risk review.

**Definition of Done:**

- documento tecnico approvabile;
- schema validabile;
- esempi reali: read file, search, patch, test, shell template, raw shell blocked, devops high risk, finish;
- nessuna implementazione rischiosa ancora richiesta.

### Epic P0-B — Code Navigation Tools

**Obiettivo:** dare occhi all'agente.

**Tool minimi:**

- `search_code(pattern, path)`;
- `find_files(pattern)`;
- `list_directory(path, depth)`;
- `read_file_range(path, start, end)`;
- `repo_map()`;
- eventuale `find_symbol` semplice.

**Definition of Done:**

- l'agente può trovare file e codice rilevante senza leggere tutto il repo;
- secret/path guard sempre attivo;
- test unitari e integration API;
- output adatto a Context Manager.

### Epic P0-C — Context Manager

**Obiettivo:** decidere cosa vede il modello a ogni step.

**Include:**

- token budget;
- file relevance scoring;
- recent actions;
- recent errors;
- memory retrieval;
- test output summarization;
- history condenser;
- context packets per ruolo;
- privacy/cost constraints.

**Definition of Done:**

- dato goal + repo + errore, costruisce contesto utile e limitato;
- non include segreti;
- degrada senza LLM;
- supporta benchmark `/api/ping`.

### Epic P0-D — Agent Reasoning Loop

**Obiettivo:** introdurre il ciclo cognitivo operativo.

**Loop:**

```text
build_context
  → model_orchestrator.decide_action
  → validate action schema
  → risk/safety/rollback
  → tool_runtime.execute
  → observe result
  → update state/memory/mission
  → governor check
  → next step or finish
```

**Definition of Done:**

- esegue una missione semplice con più step;
- usa tool reali, non mock;
- registra decisioni, azioni, risultati;
- rispetta safety e rollback;
- può fermarsi con `finish`, `ask_user`, `blocked`, `budget_exceeded`.

### Epic P0-E — Integration Layer: old loop, Mission Controller, GOAP, Tool Runtime, Governor

**Obiettivo:** evitare sistemi paralleli scollegati.

**Include:**

- autonomous loop usa Mission Controller;
- Mission Controller può delegare a Agent Reasoning Loop;
- GOAP planner alimenta azioni/precondizioni/success criteria;
- Tool Runtime è l'unico executor;
- Governor opera sul loop reale;
- Memory registra azioni reali;
- Decision reports includono action schema, risk, tool, outcome.

**Definition of Done:**

- non esiste più un loop operativo principale basato solo sui 5 command_id;
- il nuovo loop è il percorso primario controllato;
- vecchi endpoint restano compatibili come wrapper/fallback.

### Epic P0-F — Command Risk Engine v2 with LLM Risk Reviewer

**Obiettivo:** supportare shell completa governata e azioni non previste senza sacrificare sicurezza.

**Include:**

- shell parser;
- deterministic classifier;
- contextual policy engine;
- LLM risk reviewer tramite Model Orchestrator;
- MEDIUM reviewer quando raw/ambiguous/config/network/deps;
- HIGH/UNKNOWN reviewer;
- rollback resolver;
- precheck/postcheck;
- safety event log;
- test con comandi safe, medium, high, critical, unknown.

**Definition of Done:**

- raw shell proposal non viene mai eseguita senza risk engine;
- `curl | bash`, `rm -rf`, force push, secret access sono bloccati o gated;
- medium ambiguo viene analizzato;
- high richiede rollback/policy;
- output spiega la decisione.

### Epic P0-G — Real Operational Benchmark: `/api/ping` with tests

**Obiettivo:** primo benchmark reale end-to-end.

**Missione:**

```text
Aggiungi endpoint /api/ping che ritorna {"pong": true}, aggiungi test, esegui pytest, correggi errori, produci report.
```

**Definition of Done:**

- IGRIS naviga repo;
- trova il punto giusto nel server/router;
- modifica codice;
- aggiunge test;
- esegue test;
- corregge eventuali errori;
- produce final report con file modificati, comandi, risultati, rischi residui.

---

## 9. Roadmap definitiva aggiornata

### Fase 0 — Bootstrap completato / in merge

- Doctor/Verify/Crash Recovery
- Mission Controller
- Safety/Rollback/Autonomy Policy
- Tool Runtime
- GOAP Planner
- Teacher/Governor

**Risultato:** corpo operativo, safety, missioni, tool e governance.

### Fase 1 — Contratto cognitivo e architettura completa

- Epic P0-A Agent Action Schema, Prompt Contract and definitive architecture alignment
- Agent Registry definitivo dichiarato
- Model Orchestrator rules
- Command Risk contract

**Risultato:** sappiamo esattamente come LLM, ruoli, tool, safety e orchestrator comunicano.

### Fase 2 — Occhi e memoria di lavoro

- Epic P0-B Code Navigation Tools
- Epic P0-C Context Manager

**Risultato:** IGRIS può vedere repo, trovare codice e costruire contesto utile.

### Fase 3 — Cervello operativo

- Epic P0-D Agent Reasoning Loop
- Epic P0-E Integration Layer
- Epic P0-F Command Risk Engine v2

**Risultato:** IGRIS ragiona, propone azioni, esegue tramite tool governati, osserva, corregge e aggiorna stato.

### Fase 4 — Primo benchmark reale

- Epic P0-G `/api/ping` with tests
- benchmark reporting
- failure mode analysis

**Risultato:** prova reale che IGRIS può completare una micro-feature.

### Fase 5 — Auto-sviluppo controllato

- bugfix benchmark;
- feature + test;
- docs update;
- patch multi-file;
- PR proposal;
- CI reading/fix loop;
- memory reuse.

**Risultato:** IGRIS può sviluppare parti semplici di sé con supervisione.

### Fase 6 — DevOps/VPS reale

- DevOps/VPS Manager;
- server registry;
- deploy patterns;
- nginx/Docker/systemd/SSL;
- browser verification;
- rollback reale;
- production safety profiles.

**Risultato:** IGRIS opera su server autorizzati.

### Fase 7 — Delivery professionale

- GitHub Delivery completo;
- PR, CI, review gates;
- final reports professionali;
- artifacts;
- cost reports.

**Risultato:** IGRIS consegna come collaboratore tecnico.

### Fase 8 — Memory avanzata e apprendimento

- outcome-driven memory;
- vector retrieval;
- repo facts/server facts;
- deployment pattern reuse;
- lessons scoring.

**Risultato:** IGRIS migliora col tempo sui tuoi progetti.

### Fase 9 — Dashboard Control Room

- mission live status;
- action reasoning;
- risk/rollback cards;
- server health;
- memory;
- costs;
- artifacts;
- approve/block controls.

**Risultato:** controllo umano chiaro e rapido.

### Fase 10 — Plugin/Capability system e multi-agent controllato

- plugin manifest;
- capability registry;
- optional MCP adapter;
- optional Ruflo-inspired adapters;
- multi-agent role delegation controllata;
- plugin doctor checks.

**Risultato:** IGRIS diventa estendibile senza perdere governance.

### Fase 11 — Benchmark maturità definitiva

- bug fix repo piccola;
- test repair;
- feature + test;
- deploy static site;
- deploy FastAPI;
- nginx 502;
- Docker Compose rotto;
- PR + CI;
- rollback;
- browser UI;
- server recovery;
- memory reuse.

**Risultato:** score misurabile e regressioni controllate.

---

## 10. Backlog epic aggiornato

| Priorità | Epic | Stato | Impatto |
|---|---|---|---|
| P0 | Doctor/Verify/Crash Recovery | PR #52 | Stabilità |
| P0 | Mission Controller | PR #53 | Missioni persistenti |
| P0 | Safety/Rollback/Autonomy Policy | PR #54 | Libertà governata |
| P0 | Tool Runtime locale/server | PR #55 | Azioni reali |
| P0 | GOAP-like Planner | PR #56 | Piani robusti |
| P0 | Teacher/Governor anti-loop | PR #57 | Evita loop |
| P0 | Agent Action Schema & Prompt Contract | nuovo | Contratto LLM↔IGRIS |
| P0 | Code Navigation Tools | nuovo | Occhi sul repo |
| P0 | Context Manager | nuovo | Memoria di lavoro del modello |
| P0 | Agent Reasoning Loop | nuovo | Cervello operativo |
| P0 | Integration Layer | nuovo | Collega corpo/cervello |
| P0 | Command Risk Engine v2 + LLM reviewer | nuovo | Shell completa governata |
| P0 | Real Benchmark `/api/ping` | nuovo | Prima prova reale |
| P1 | Agent Registry definitivo | esistente da rafforzare | Ruoli, capability, evoluzione multi-agent |
| P1 | Memory Learning Loop avanzato | da fare | Miglioramento continuo |
| P1 | DevOps/VPS Manager | da fare | Siti/server reali |
| P2 | Browser/UI Testing | da fare | Verifica reale UI |
| P2 | GitHub Delivery workflow | da fare | PR/CI/review |
| P2 | Dashboard Control Room | da fare | Osservabilità |
| P3 | Plugin/Capability System | futuro | Estensibilità |
| P3 | Advanced Cost/Model Routing | da rafforzare | Efficienza |
| P3 | Benchmark Suite definitiva | futuro | Misurazione qualità |

---

## 11. Prompt operativo aggiornato per Devin / ChatGPT / IGRIS

### 11.1 Prompt breve

> Implementa la prossima voce P0/P1 della roadmap `docs/IGRIS_GPT_MASTER_ROADMAP.md`. Mantieni compatibilità con la base esistente, aggiungi test, aggiorna documentazione, non introdurre shell cieca, salva report/diagnostica, e rispetta il modello Model Orchestrator → Agent Action Schema → Command Risk Engine → Safety/Rollback → Tool Runtime → Verifier → Memory/Governor.

### 11.2 Prompt per task complesso

> Agisci come principal engineer su IGRIS_GPT. Leggi `README.md`, `docs/IGRIS_GPT_MASTER_ROADMAP.md` e i documenti collegati. Implementa l'epic indicato seguendo: problema, design, schema dati, API, UI se necessaria, test, sicurezza, rollback, docs. Non fare modifiche cosmetiche. Ogni nuova capacità deve essere verificabile con test e deve degradare senza crash. Ogni uso di LLM deve passare dal Model Orchestrator. Ogni comando raw deve passare dal Command Risk Engine.

### 11.3 Prompt per IGRIS stesso

> Crea una missione interna per implementare l'epic selezionato dalla roadmap. Ispeziona lo stato del repo, genera piano con precondizioni/effetti, costruisci contesto, proponi azioni strutturate, usa solo tool consentiti dalla safety policy, verifica con test, salva decision report, aggiorna memory e produci final report.

---

## 12. Criterio finale di successo

IGRIS_GPT sarà vicino alla versione definitiva quando potrà completare con successo missioni come:

1. clonare repo nuova, installarla, diagnosticare problemi e far passare test;
2. creare feature piccola, testarla e aprire PR;
3. fare deploy di app su VPS autorizzata con nginx/SSL;
4. diagnosticare sito down e correggere;
5. produrre report finale chiaro, verificabile e con rollback;
6. ricordare errori/fix per missioni future;
7. lavorare per sessioni lunghe senza crash opachi;
8. evitare loop semantici e cambiare strategia dopo saturazione;
9. controllare costi e usare provider appropriati;
10. mostrare tutto in dashboard operativa.

Primo benchmark reale:

```text
IGRIS riceve: "aggiungi endpoint /api/ping con test".
IGRIS trova il codice, modifica, testa, corregge e produce report.
```

---

## 13. Regola guida

Aggiungere tutto ciò che aumenta autonomia reale, qualità, stabilità, sicurezza, capacità server/deploy e consegna.

Evitare tutto ciò che aggiunge dipendenze fragili, magia opaca, crash surface, tool non governati o complessità senza impatto operativo.

Architettura completa prevista da subito; implementazione incrementale, verificabile e misurata da benchmark reali.
