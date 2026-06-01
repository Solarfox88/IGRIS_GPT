# Roadmap Addendum — Audit retrospettivo Epic Perfezionamento #1071–#1078

Questo documento integra `docs/IGRIS_GPT_MASTER_ROADMAP.md` e rende esplicito un nuovo blocco obbligatorio di roadmap: **audit retrospettivo degli 8 epic di perfezionamento #1071–#1078**.

## Perché serve

Le issue e PR possono risultare `completed` perché mergeate, testate e con CI verde, ma questo non dimostra automaticamente che siano `production-complete`.

Dopo l'audit indipendente su altri blocchi recenti, sono emersi casi in cui issue già chiuse erano in realtà:

- `solid baseline`, cioè buone basi operative ma non ancora production-grade;
- `partial`, cioè incomplete rispetto all'obiettivo reale;
- corrette come acceptance minima ma non perfette rispetto al target finale IGRIS.

Quindi gli 8 epic di perfezionamento non devono essere considerati automaticamente 100% definitivi solo perché chiusi.

## Regola roadmap

Ogni epic di perfezionamento #1071–#1078 deve essere rivalutato con questa classificazione:

| Stato | Significato |
|---|---|
| `production-complete` | completo nel suo perimetro, cablato nel runtime reale, testato, senza gap sostanziali noti |
| `solid baseline` | funziona, ha test/CI, ma restano gap hardening o integrazioni incomplete |
| `partial` | implementazione incompleta o con bug/gap funzionali rispetto all'obiettivo |

## Scope dell'audit

L'audit deve verificare, per ciascuno degli 8 epic:

1. obiettivo originale dell'epic;
2. PR collegate;
3. codice reale su `main`;
4. test dedicati e CI;
5. cablaggio nel runtime reale;
6. regressioni o falsi positivi possibili;
7. sicurezza, audit, fallback e degraded mode;
8. completezza rispetto all'obiettivo finale IGRIS;
9. classificazione finale: `production-complete`, `solid baseline`, `partial`;
10. follow-up issue obbligatorie se non `production-complete`.

## Epic da auditare

| Epic | Stato attuale operativo | Audit richiesto |
|---|---|---|
| #1071 | completed/merged | verificare se production-complete o solo baseline |
| #1072 | completed/merged | verificare se production-complete o solo baseline |
| #1073 | completed/merged | verificare se production-complete o solo baseline |
| #1074 | completed/merged | verificare se production-complete o solo baseline |
| #1075 | completed/merged | verificare se production-complete o solo baseline |
| #1076 | completed/merged | verificare se production-complete o solo baseline |
| #1077 | completed/merged | verificare se production-complete o solo baseline |
| #1078 | completed/merged | verificare se production-complete o solo baseline |

## Output richiesto

Produrre una tabella finale:

| Epic | PR | Obiettivo | Test/CI | Runtime wiring | Stato reale | Gap | Follow-up |
|---|---|---|---|---|---|---|---|
| #1071 | ... | ... | ... | ... | production-complete / solid baseline / partial | ... | ... |

## Regole operative per Codex/Devin

- Non dichiarare 100% senza audit sul codice reale.
- Non basarsi solo sulla descrizione PR.
- Non considerare CI verde come sinonimo di production-complete.
- Se un epic è `solid baseline`, creare follow-up hardening.
- Se un epic è `partial`, creare/fare PR di fix prioritaria.
- Non fare refactor massivi durante l'audit.
- Ogni PR correttiva deve essere piccola, con scope chiaro e CI verde.

## Posizione nella roadmap

Questo blocco deve essere eseguito dopo il completamento del backlog tecnico corrente o prima di dichiarare IGRIS vicino al 100%.

Ordine consigliato:

1. completare #1112, #1111, #1108 se ancora aperte;
2. eseguire audit retrospettivo #1071–#1078;
3. creare follow-up per epic non production-complete;
4. solo dopo aggiornare la percentuale globale del progetto.

## Nota finale

La regola guida diventa:

```text
Issue chiusa = acceptance minima soddisfatta.
Production-complete = audit severo, runtime wiring reale, test mirati, CI verde e nessun gap sostanziale noto.
```
