# Issue #639 — Integration Gap Matrix for #628

## Obiettivo
Produrre una matrice gap priorizzata per implementare `#628` in coerenza con i requisiti `#536`.

## Gap Matrix (priorità, impatto, azione)
| ID | Gap | Priorità | Impatto | Azione proposta | Done Criteria |
|---|---|---|---|---|---|
| G1 | Contratto unico `chunk->score->topic->global` assente | P0 | Alto | Introdurre contract interno e adapter | API interne stabili + test contract |
| G2 | `chunk_id` deterministico non enforce end-to-end | P0 | Alto | Standard sha256 a livello store/graph | id stabili su run ripetuti |
| G3 | Scoring/top-k non centralizzato | P1 | Alto | ScoreStore con query top-k | benchmark top-k + test coerenza |
| G4 | Retrieval gerarchico incompleto | P1 | Alto | strategia gerarchica + fallback keyword | recall minima definita + test |
| G5 | Bridge `ContextManager` non esplicito | P1 | Medio-Alto | `inject_memory_hierarchy` con budget | no regressione budget/token |
| G6 | Migrazione legacy nodes non formalizzata | P1 | Alto | migration runner + rollback plan | migrazione idempotente |
| G7 | Test integrati acceptance #536 frammentati | P1 | Medio | suite integration dedicata | pass stabile su CI locale |
| G8 | Telemetria qualità retrieval non uniforme | P2 | Medio | metriche hit-rate/fallback/escalation | report run comparabili |

## Sequenza implementativa raccomandata
1. G1 + G2 (fondazioni contrattuali).
2. G3 + G4 (core qualità retrieval).
3. G5 + G6 (integrazione contesto + migrazione).
4. G7 + G8 (test e osservabilità finali).

## Rischi principali
- Regressioni su contesto se bridge memoria non rispetta budget.
- Migrazione legacy con dati parziali o inconsistenze preesistenti.
- Drift di qualità se top-k non è calibrato per failure-driven retrieval.

## Mitigazioni
- Feature flag per attivare pipeline gerarchica gradualmente.
- Dry-run migration + snapshot rollback.
- Golden tests su issue reali (`#536`) con confronto output quality.

## KPI di uscita
- Success rate suite integrazione memoria >= 95%.
- Retry medi supervisore su task memoria in calo vs baseline.
- Riduzione fallback non utili nel contesto di reasoning.
- Tracciabilità end-to-end tra requirement #536 e output runtime.
