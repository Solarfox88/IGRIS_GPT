# IGRIS_GPT — Master Roadmap Definitiva

Questa roadmap è il riferimento operativo per portare **IGRIS_GPT** alla versione definitiva: un agente personale di engineering capace di sostituire l'utente nei compiti tecnici assegnati, lavorare in autonomia su macchina locale, repository, siti web, VPS/server, GitHub, deploy, test, debugging, manutenzione e report finale.

La roadmap integra le migliori idee osservate da tre fonti di ispirazione:

- **Ruflo / Claude Flow**: orchestrazione, agenti specializzati, router, memoria, hook, plugin, provider routing, doctor/verify, dashboard, security hardening.
- **Devin**: comportamento operativo end-to-end: capire un task, esplorare, pianificare, modificare, eseguire, correggere, testare e consegnare.
- **OpenHands**: workspace operativo, terminale, file editing, loop observe-act, ambiente di esecuzione controllato; da non ereditare invece crash, fragilità e accoppiamento eccessivo.

---

## 0. Visione finale

IGRIS_GPT deve diventare un **AI Engineering Operator** personale, installabile su Ubuntu/VPS/local machine, capace di ricevere un obiettivo come:

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

### 1.2 Stabilità superiore a OpenHands
Ogni componente deve degradare in modo controllato. Nessun crash non diagnosticato deve interrompere missioni lunghe senza report e recovery.

### 1.3 Potenza governata, non limitazione sterile
IGRIS deve poter agire liberamente, ma con policy, rischio, rollback e audit. La sicurezza deve abilitare l'autonomia, non bloccarla.

### 1.4 Local-first, server-capable
Il sistema deve funzionare localmente, ma deve essere capace di operare su VPS/server tramite SSH, Docker, nginx, systemd, GitHub e provider cloud.

### 1.5 Anti-loop strutturale
Dopo 3 ripetizioni della stessa famiglia di remediation, IGRIS deve cambiare strategia o richiedere un differenziatore concreto e verificabile.

### 1.6 Deliverable eccellente
Ogni missione conclusa deve produrre risultato, verifiche, report, modifiche tracciate, eventuale rollback e memoria riusabile.

---

## 2. Architettura target: il sistema nervoso di IGRIS

IGRIS_GPT non deve basarsi su un sistema nervoso esterno come Claude Code. Deve avere un proprio **Operational Nervous System**, composto da:

```text
Goal Intake
  ↓
Mission Controller
  ↓
State Inspector
  ↓
Goal Planner / GOAP-like Planner
  ↓
Task Router
  ↓
Specialist Agents
  ↓
Tool Runtime
  ↓
Safety / Policy / Rollback Layer
  ↓
Execution / Observation / Verification
  ↓
Memory / Lessons / Decision Reports
  ↓
Teacher / Governor / Replanner
```

### 2.1 Componenti principali

| Componente | Responsabilità |
|---|---|
| Mission Controller | Mantiene obiettivo, stato, piano, progressi e stop conditions |
| State Inspector | Legge repo, file, test, server, processi, logs, Git, ambiente |
| Planner | Trasforma obiettivi in azioni con precondizioni/effetti |
| Task Router | Sceglie agenti/tool/azioni evitando loop e duplicati |
| Agent Registry | Definisce ruoli, permessi, responsabilità e tool consentiti |
| Tool Runtime | Esegue shell, filesystem, git, ssh, docker, http, browser, GitHub |
| Safety Layer | Classifica rischio, blocca comandi pericolosi, richiede rollback |
| Verification Layer | Test, lint, healthcheck, browser test, deploy validation |
| Memory Layer | Salva outcome, errori, fix, pattern, decisioni, lezioni |
| Teacher/Governor | Interviene su loop, blocchi, saturazione, piani deboli |
| Dashboard | Mostra stato, log, comandi, costi, rischi, risultati |

---

## 3. Roadmap per fasi

## Fase 1 — Hardening della base esistente

Obiettivo: rendere la base attuale affidabile, diagnosticabile e pronta per autonomia più libera.

### 1.1 Baseline doctor/verify
- Implementare/rafforzare `igris doctor`.
- Verificare Python, venv, dipendenze, Ollama, OpenAI key, Git, Docker, SSH, porte, permessi.
- Generare report JSON/Markdown.
- Suggerire fix applicabili.
- Exit codes chiari.

### 1.2 Crash recovery
- Ogni loop/missing provider/error deve produrre report.
- Nessun fallimento deve sparire senza timeline event.
- Salvare stacktrace redatto.
- Introdurre `last_known_good_state`.

### 1.3 Test baseline permanente
- Mantenere e aumentare test esistenti.
- Separare unit/integration/e2e/server.
- Aggiungere smoke test reale per installazione Ubuntu.

### 1.4 Config validation
- Validare `.env`, `config.json`, paths, provider, budget, safety policy.
- Diagnosticare configurazioni incomplete.

### 1.5 Operational logs unificati
- Standardizzare timeline, execution logs, decision reports, safety events.
- Ogni azione deve avere `trace_id`, `mission_id`, `task_id`.

**Definition of Done Fase 1**
- `igris doctor` dà diagnosi utile.
- Un crash produce report utile.
- Test e smoke test passano.
- Installazione Ubuntu verificata.

---

## Fase 2 — Mission Controller definitivo

Obiettivo: passare da task isolate a missioni end-to-end.

### 2.1 Mission schema
Ogni missione deve includere:

```json
{
  "id": "mission_x",
  "goal": "Deploy site on VPS",
  "status": "planning|executing|blocked|verifying|done|failed",
  "workspace": "...",
  "target_hosts": [],
  "constraints": [],
  "success_criteria": [],
  "risk_level": "low|medium|high|critical",
  "plan": [],
  "artifacts": [],
  "rollback_plan": null,
  "final_report": null
}
```

### 2.2 Mission lifecycle
- Create mission.
- Inspect state.
- Generate plan.
- Materialize tasks.
- Execute next action.
- Observe result.
- Replan on failure.
- Verify success criteria.
- Deliver final report.

### 2.3 Long-running task resilience
- Pause/resume.
- Persistent state.
- Reconstruct context after restart.
- Prevent duplicate execution.

### 2.4 Mission dashboard
- Active mission.
- Current step.
- Reason for selected action.
- Risk/rollback.
- Recent command outputs.
- Verification status.

**Definition of Done Fase 2**
- Una missione può durare più step e sopravvivere a restart.
- Stato e prossima azione sono sempre spiegabili.
- L'utente può vedere perché IGRIS sta facendo qualcosa.

---

## Fase 3 — Planner GOAP-like con precondizioni/effetti

Obiettivo: rendere il piano più simile a Devin: non solo task list, ma percorso verso stato desiderato.

### 3.1 Action model
Ogni azione deve dichiarare:

```json
{
  "id": "configure_nginx_reverse_proxy",
  "family": "devops_deploy",
  "preconditions": ["service_running", "domain_known"],
  "effects": ["http_route_configured", "nginx_config_tested"],
  "risk": 7,
  "cost": 2,
  "requires_rollback": true,
  "tools": ["ssh", "filesystem", "shell"]
}
```

### 3.2 State model
Rappresentare stato corrente:

- repo clean/dirty;
- tests pass/fail;
- service running/stopped;
- Docker available;
- nginx available;
- domain resolves;
- SSL present;
- task families saturated;
- blocked actions;
- known failures.

### 3.3 Planner
- Generare piano iniziale.
- Calcolare azioni eleggibili.
- Evitare azioni con precondizioni mancanti.
- Penalizzare famiglie sature.
- Replan dopo fallimento.

### 3.4 Success criteria mapping
Ogni missione deve avere criteri verificabili:

- endpoint risponde 200;
- test passano;
- servizio systemd attivo;
- container healthy;
- PR creata;
- diff review passato;
- report generato.

**Definition of Done Fase 3**
- IGRIS può spiegare piano, precondizioni, effetti e motivo della prossima azione.
- Un fallimento cambia il piano invece di ripetere lo stesso passo.

---

## Fase 4 — Agent Registry e agenti specialistici

Obiettivo: trasformare il sistema da monolite a squadra coordinata.

### 4.1 Agent registry
Creare `agent/agents/registry.py` o equivalente.

Agenti minimi:

| Agente | Compito |
|---|---|
| Coordinator | Mantiene focus e obiettivo |
| Planner | Scompone obiettivi e aggiorna piani |
| Researcher | Esplora repo, docs, log, server |
| Coder | Modifica codice |
| Tester | Test, lint, bug reproduction |
| DevOps | VPS, Docker, nginx, systemd, deploy |
| Reviewer | Diff review, regressioni, qualità |
| Security Guard | Policy, segreti, rischio, path guard |
| Teacher/Governor | Anti-loop, recovery, escalation |
| Memory Manager | Outcome, lezioni, retrieval |
| Cost Guardian | Provider, budget, costi |

### 4.2 Agent contract
Ogni agente dichiara:

- ruolo;
- input accettato;
- output atteso;
- tool consentiti;
- rischi;
- escalation.

### 4.3 Coordinator pattern
Per evitare drift, ogni missione complessa deve avere un Coordinator che valida:

- allineamento al goal;
- step corrente;
- qualità output;
- necessità di replan.

**Definition of Done Fase 4**
- Ogni step viene assegnato a un agente con ruolo chiaro.
- Nessun agente può usare tool fuori dal proprio profilo senza escalation.

---

## Fase 5 — Tool Runtime operativo reale

Obiettivo: dare a IGRIS capacità operative reali su macchina locale e server.

### 5.1 Tool da implementare/rafforzare

| Tool | Capacità |
|---|---|
| shell | Comandi locali con policy e timeout |
| filesystem | Lettura/scrittura sicura, diff, backup |
| git | status, diff, branch, commit, push, PR prep |
| github | issue, PR, review, workflow, release |
| ssh | Connessione server autorizzati |
| docker | build, compose, logs, ps, health |
| systemd | status, restart, logs, enable |
| nginx | config test, reload, sites-enabled |
| http_check | healthcheck, SSL, response body |
| browser | Playwright/browser testing |
| package_manager | pip/npm/apt con policy |
| secrets | env validation, redaction, no leak |

### 5.2 Command policy evoluta
Superare il modello solo `command_id`, mantenendo sicurezza:

- allowlist dinamica per missione;
- template di comando con parametri validati;
- classificazione rischio;
- obbligo rollback per high risk;
- dry-run se disponibile;
- timeout e output truncation.

### 5.3 Remote host registry
Definire host autorizzati:

```json
{
  "name": "prod-vps-1",
  "host": "example.com",
  "user": "deploy",
  "allowed_paths": ["/var/www", "/etc/nginx/sites-available"],
  "allowed_services": ["nginx", "myapp"],
  "requires_backup": true
}
```

**Definition of Done Fase 5**
- IGRIS può eseguire operazioni reali local/server con policy, log e rollback.
- Le azioni high risk non sono cieche.

---

## Fase 6 — Safety, rollback e autonomia governata

Obiettivo: abilitare libertà operativa senza distruttività.

### 6.1 Risk classifier
Classificare azioni:

- low: lettura, status, test;
- medium: scrittura workspace, install locale, restart dev;
- high: deploy, nginx/systemd, docker down, push;
- critical: delete, db migration, DNS, firewall, secrets, production destructive.

### 6.2 Rollback manager
Prima di azioni high risk:

- backup file config;
- snapshot diff;
- docker compose config backup;
- export DB se applicabile;
- comando di rollback documentato;
- verifica rollback applicabile.

### 6.3 Approval policy configurabile
Modalità:

- `safe`: solo low/medium automatiche;
- `operator`: high automatiche se rollback presente;
- `trusted`: più autonomia su host autorizzati;
- `manual-critical`: critical sempre richiede conferma.

### 6.4 Secret guard
- Bloccare preview `.env`.
- Redigere output.
- Rilevare API keys.
- Evitare commit di secrets.

**Definition of Done Fase 6**
- IGRIS può operare liberamente entro policy esplicite.
- Ogni modifica rischiosa ha rollback o escalation.

---

## Fase 7 — Memoria outcome-driven e learning loop

Obiettivo: IGRIS deve migliorare nel tempo.

### 7.1 Memory stores

```text
.igris/memory/
  decisions.jsonl
  failures.jsonl
  outcomes.jsonl
  lessons.jsonl
  server_facts.jsonl
  repo_facts.jsonl
  deployment_patterns.jsonl
  saturated_families.json
```

### 7.2 Cosa salvare
- Task eseguite.
- Comandi e outcome.
- Errori e root cause.
- Fix efficaci.
- Pattern di deploy.
- Scelte di modello/provider.
- Famiglie sature.
- Success criteria riusciti/falliti.

### 7.3 Retrieval
Prima di una missione:

- cercare casi simili;
- caricare lezioni rilevanti;
- evitare errori già fatti;
- applicare pattern riusciti.

### 7.4 Vector search futura
Fase iniziale JSONL + keyword/fingerprint.
Fase avanzata embeddings locali + HNSW/SQLite/FAISS/Chroma.

**Definition of Done Fase 7**
- IGRIS ricorda fallimenti/fix e li usa per piani futuri.
- I report non sono solo archivi, ma memoria operativa.

---

## Fase 8 — Teacher/Governor anti-loop definitivo

Obiettivo: impedire loop semantici e recovery sterile.

### 8.1 Family saturation
Le famiglie da tracciare includono:

- observation;
- synthesis;
- repo_diff_discovery;
- patch_strategy;
- branch_pr_plan;
- review_gate;
- candidate_materialization;
- mastery_cycle;
- mastery_gate;
- school_report;
- grading_diagnosis;
- stabilization_audit;
- devops_deploy;
- server_diagnosis;
- test_repair;
- code_patch;
- documentation;
- security_audit;
- other.

### 8.2 Regola delle 3 ripetizioni
Dopo 3 ripetizioni recenti:

- famiglia satura;
- selettore la penalizza/esclude;
- teacher deve scegliere famiglia diversa;
- eccezione solo con differenziatore verificabile.

### 8.3 Semantic deduplication
Non basta cambiare titolo. Fingerprint deve considerare:

- famiglia;
- intent;
- file target;
- effetto atteso;
- causa del blocco;
- success criteria.

### 8.4 Forced strategy shift
Se tutte le famiglie utili sono sature:

- attivare stabilization audit;
- chiedere missing information;
- generare diagnostic task;
- cambiare livello: da patch a planning, da planning a execution, da execution a diagnosis.

**Definition of Done Fase 8**
- IGRIS non ripete task semanticamente uguali.
- Dopo 3 ripetizioni cambia strategia davvero.

---

## Fase 9 — Devin-like autonomous work sessions

Obiettivo: comportamento operativo simile a Devin.

### 9.1 Sessione di lavoro autonoma
Per ogni obiettivo:

1. comprendere richiesta;
2. creare piano;
3. esplorare repo/server;
4. eseguire step;
5. leggere errori;
6. correggere;
7. testare;
8. ripetere finché criteria passano o blocco reale;
9. consegnare report.

### 9.2 Workspace tracking
- File modificati.
- Comandi eseguiti.
- Errori incontrati.
- Tentativi falliti.
- Ipotesi formulate.
- Decisioni importanti.

### 9.3 Stop conditions
IGRIS si ferma solo se:

- successo verificato;
- policy blocca azione necessaria;
- credenziali/permessi mancanti;
- rischio critical richiede conferma;
- costo supera budget;
- impossibile avanzare con diagnosi documentata.

### 9.4 Final report
Report finale deve includere:

- obiettivo;
- cosa è stato fatto;
- file modificati;
- comandi importanti;
- test/verifiche;
- deployment/URL;
- problemi e fix;
- rischi residui;
- prossimi passi;
- rollback.

**Definition of Done Fase 9**
- IGRIS può completare task lunghi con report professionale.
- Non richiede supervisione continua per ogni micro-step.

---

## Fase 10 — DevOps/VPS/Siti web

Obiettivo: IGRIS deve operare su server e siti reali.

### 10.1 Server diagnosis
- OS, CPU, RAM, disk.
- Processi e porte.
- Docker status.
- nginx/apache status.
- systemd services.
- certbot/SSL.
- logs applicativi.

### 10.2 Deploy patterns
Supportare:

- static site;
- Node/React/Vite;
- Python/FastAPI;
- Docker Compose;
- WordPress/PHP;
- reverse proxy nginx;
- systemd service;
- SSL certbot.

### 10.3 Healthcheck
- HTTP 200.
- SSL valid.
- response time.
- container healthy.
- logs no fatal.
- service enabled/running.

### 10.4 Backup/rollback
- backup config nginx;
- backup compose/env template;
- rollback symlink release;
- restart previous service;
- restore previous config.

**Definition of Done Fase 10**
- IGRIS può fare deploy e manutenzione su VPS autorizzata con verifica e rollback.

---

## Fase 11 — GitHub e delivery professionale

Obiettivo: consegna tracciata come collaboratore tecnico.

### 11.1 Git workflow
- Branch per missione.
- Commit piccoli e descrittivi.
- Pre-commit safety check.
- Pull/rebase prima push.
- PR summary.

### 11.2 GitHub issues/PR
- Leggere issue.
- Creare branch da issue.
- Aprire PR.
- Aggiornare issue con report.
- Leggere CI.
- Correggere CI failure.

### 11.3 Review gate
Prima di consegnare:

- diff review;
- test pass;
- secrets check;
- rollback note;
- docs update se necessario.

**Definition of Done Fase 11**
- IGRIS consegna lavoro via PR/commit con qualità controllabile.

---

## Fase 12 — Browser/UI testing

Obiettivo: verificare siti/app come utente reale.

### 12.1 Browser automation
- Aprire URL.
- Screenshot.
- Controllare testo/elementi.
- Form submit.
- Login flow se credenziali fornite.
- Console errors.

### 12.2 Visual evidence
- Salvare screenshot prima/dopo.
- Allegare al report.

### 12.3 UI regression smoke
- Homepage.
- Navigation.
- Main CTA.
- Login/logout.
- Dashboard.

**Definition of Done Fase 12**
- IGRIS può dimostrare che il sito funziona, non solo che il server risponde.

---

## Fase 13 — Cost/model routing avanzato

Obiettivo: usare il modello giusto al costo giusto.

### 13.1 Provider tiers
- Deterministic/no LLM.
- Local Ollama.
- Cheap cloud model.
- Strong model.
- Specialist model.

### 13.2 Routing policy
- Task semplice: deterministic/local.
- Code patch media: cheap/standard.
- Architecture/security/deploy critical: strong model + review.
- Repeated failure: escalate model.

### 13.3 Budget
- Costo per missione.
- Costo giornaliero/mensile.
- Stop/escalation sopra soglia.
- Report costi.

**Definition of Done Fase 13**
- IGRIS controlla costi senza perdere qualità sui task critici.

---

## Fase 14 — Dashboard Control Room

Obiettivo: rendere IGRIS osservabile e controllabile.

### 14.1 Vista missione
- Goal.
- Stato.
- Piano.
- Step corrente.
- Perché questa azione.
- Rischio.
- Rollback.
- Ultimi output.

### 14.2 Vista server
- Hosts autorizzati.
- Health.
- Servizi.
- Deploy recenti.

### 14.3 Vista memory
- Lezioni recenti.
- Fallimenti.
- Saturazioni.
- Pattern efficaci.

### 14.4 Vista safety/cost
- Azioni bloccate.
- Policy.
- Budget.
- Provider usati.

**Definition of Done Fase 14**
- L'utente può capire in 30 secondi cosa sta facendo IGRIS e perché.

---

## Fase 15 — Plugin/capability system

Obiettivo: rendere IGRIS estendibile senza monolite fragile.

### 15.1 Capability manifest
Ogni plugin dichiara:

```json
{
  "name": "docker_ops",
  "capabilities": ["docker_ps", "docker_logs", "docker_compose_up"],
  "risk": "medium|high",
  "tools": [],
  "requires": ["docker_available"],
  "tests": []
}
```

### 15.2 Plugin iniziali
- core;
- git_ops;
- github_ops;
- devops_ops;
- docker_ops;
- nginx_ops;
- browser_ops;
- memory_ops;
- safety_ops;
- cost_ops;
- docs_ops.

### 15.3 Plugin health
- Ogni plugin ha doctor check.
- Ogni plugin può essere disabilitato senza rompere core.

**Definition of Done Fase 15**
- Nuove capacità si aggiungono senza modificare l'orchestratore centrale.

---

## Fase 16 — Benchmark realistici

Obiettivo: misurare IGRIS contro task reali.

### 16.1 Benchmark categories
- Bug fix repo piccola.
- Test repair.
- Add feature.
- Deploy static site.
- Deploy FastAPI app.
- Debug nginx 502.
- Fix Docker Compose.
- Open PR.
- Generate docs.

### 16.2 Metrics
- Success rate.
- Time to completion.
- Number of loops.
- Cost.
- Test pass.
- Human intervention count.
- Rollback availability.
- Report quality.

### 16.3 Regression gates
Una nuova feature non deve peggiorare stabilità.

**Definition of Done Fase 16**
- IGRIS ha benchmark ripetibili e score confrontabile nel tempo.

---

## 4. Epic backlog sintetico

| Priorità | Epic | Fonte ispirazione | Impatto |
|---|---|---|---|
| P0 | Doctor/verify e crash recovery | Ruflo/OpenHands lessons | Stabilità |
| P0 | Mission Controller | Devin | Autonomia end-to-end |
| P0 | Tool Runtime locale/server | Devin/OpenHands | Azioni reali |
| P0 | Safety/Rollback | Ruflo + necessità VPS | Libertà governata |
| P1 | GOAP-like Planner | Ruflo/Devin | Piani robusti |
| P1 | Agent Registry | Ruflo | Specializzazione |
| P1 | Memory Learning Loop | Ruflo/IGRIS storico | Miglioramento continuo |
| P1 | Teacher/Governor anti-loop | IGRIS storico | Evita loop semantici |
| P1 | DevOps/VPS manager | Obiettivo utente | Siti/server reali |
| P2 | Browser testing | Devin/OpenHands | Verifica reale UI |
| P2 | GitHub delivery | Devin | PR/CI/review |
| P2 | Dashboard Control Room | Ruflo | Osservabilità |
| P3 | Plugin system | Ruflo | Estensibilità |
| P3 | Advanced cost routing | Ruflo | Efficienza |
| P3 | Benchmarks | Devin quality target | Misurazione |

---

## 5. Prompt operativo per Devin / ChatGPT / IGRIS

### 5.1 Prompt breve

> Implementa la prossima voce P0/P1 della roadmap `docs/IGRIS_GPT_MASTER_ROADMAP.md`. Mantieni compatibilità con la base esistente, aggiungi test, aggiorna documentazione, non introdurre esecuzione arbitraria non governata, salva report/diagnostica, e rispetta il modello Safety/Rollback/Memory/Teacher.

### 5.2 Prompt per task complesso

> Agisci come principal engineer su IGRIS_GPT. Leggi `README.md`, `docs/IGRIS_GPT_MASTER_ROADMAP.md` e i documenti collegati. Implementa l'epic indicato seguendo: problema, design, schema dati, API, UI se necessaria, test, sicurezza, rollback, docs. Non fare modifiche cosmetiche. Ogni nuova capacità deve essere verificabile con test e deve degradare senza crash.

### 5.3 Prompt per IGRIS stesso

> Crea una missione interna per implementare l'epic selezionato dalla roadmap. Ispeziona lo stato del repo, genera piano con precondizioni/effetti, materializza task, esegui solo azioni consentite dalla safety policy, verifica con test, salva decision report, aggiorna memory e produci final report.

---

## 6. Criterio finale di successo

IGRIS_GPT sarà considerato vicino alla versione definitiva quando potrà completare con successo missioni come:

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

---

## 7. Regola guida

Aggiungere tutto ciò che aumenta autonomia reale, qualità, stabilità, sicurezza, capacità server/deploy e consegna.

Evitare tutto ciò che aggiunge dipendenze fragili, magia opaca, crash surface, tool non governati o complessità senza impatto operativo.
