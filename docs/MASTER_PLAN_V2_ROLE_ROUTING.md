# Master Plan V2 — Role Routing and Execution Strategy

Issue di riferimento: `#685` (master), `#638`, `#639`, `#682`, `#684`.

## 1. Delta ufficiale: piano iniziale -> piano V2 adottato
| Area | Piano iniziale | Piano V2 adottato | Razionale |
|---|---|---|---|
| Planner | DeepSeek-R1 fisso | `gpt-5.4-mini` | miglior tradeoff qualità/costo/latenza nei benchmark reali |
| Implementer | DeepSeek coder unico | `deepseek-v4-flash` primario, `deepseek-v4-pro` strong fallback | flash più economico/veloce; pro usato su casi complessi |
| Critic | non separato chiaramente | `gpt-4o-mini` (economico) / `gpt-4o` (veloce) | quality gate dedicato e costo contenuto |
| Escalation strong | R1+Coder | `gpt-5.4` | qualità più alta e più stabile su escalation |
| Retry | ripetizioni più lineari | retry adattivo + escalation anticipata | riduzione tentativi ciechi e latenza inutile |
| Scope provider | DeepSeek-only rigido | routing multi-provider data-driven | massimizza qualità operativa reale |

## 2. Matrice ruoli runtime (target)
| Ruolo/Fase | Primario | Fallback |
|---|---|---|
| Rank/Planner | `gpt-5.4-mini` | `gpt-5.4` |
| Repair/Implementer | `deepseek-v4-flash` | `deepseek-v4-pro` |
| Critic/Review gate | `gpt-4o-mini` | `gpt-4o` |
| Escalation strong | `gpt-5.4` | `deepseek-v4-pro` |

## 3. Policy decisionale minima
1. Errore banale (`syntax/import/indent/undefined`) -> massimo 1 retry rapido.
2. Errore logico/funzionale -> escalation anticipata (no loop cieco).
3. Quality gate non soddisfatto -> reject, refine o escalate.
4. Budget guard sempre attivo con costo `all-attempts` (retry inclusi).

## 4. Stato implementazione (tracking)
| Item | Stato |
|---|---|
| Documentazione interfacce/gap #638 | Done |
| Matrice gap priorizzata #639 | Done |
| Override routing per fase in helper/runtime | Done |
| Benchmark planner/implementer/critic/escalation su #536 | Done |
| Chiusura loop roadmap + allineamento remoto/locale | In progress |

## 5. Cosa resta prima di far ripartire #536 in modo stabile
1. Merge su `main` delle issue-documento e routing finale.
2. Verifica smoke run supervisore con nuova matrice ruoli.
3. Avvio run su `#536` con monitoraggio KPI (quality/costo/tempo/retry).

## 6. Nota su DeepSeek v4 Pro
`deepseek-v4-pro` non viene scartato. È componente strategico di fallback/escalation quando il `flash` non raggiunge qualità sufficiente nei repair complessi.
