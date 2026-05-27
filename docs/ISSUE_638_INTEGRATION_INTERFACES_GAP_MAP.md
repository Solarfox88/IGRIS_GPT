# Issue #638 — Integration Interfaces and Gap Map

## Scope
Allineare i requisiti di `#536` (memory tree hierarchy: `chunk -> score -> topic -> global`) con la pipeline attuale, definendo:
- interfacce richieste,
- insertion points,
- gap tecnici concreti.

## Requisiti funzionali #536 (target)
1. `chunk_id` deterministico (sha256).
2. Store contenuto con write atomiche.
3. Scoring persistente e interrogabile.
4. Raggruppamento topic e top-k.
5. Digest globale e retrieval gerarchico.
6. Integrazione `ContextManager`.
7. Migrazione retrocompatibile nodi esistenti.
8. Verifica con test ripetibili.

## Mappa componenti attuali (pipeline reale)
- `igris/core/memory_chunker.py`: chunking/spezzamento contenuti.
- `igris/core/memory.py`: operazioni memoria base.
- `igris/core/memory_graph.py`: struttura/relazioni memoria.
- `igris/core/decision_memory.py`: memoria decisionale run/task.
- `igris/core/context_manager.py`: composizione contesto per reasoning.
- `igris/core/memory_validator.py`: validazioni coerenza.
- `igris/core/failure_memory.py`: pattern di fallimento.

## Interfacce richieste (contratti)
### 1) ChunkStore
- `put_chunk(content, meta) -> chunk_id`
- `get_chunk(chunk_id) -> chunk`
- `list_chunks(filters) -> list`
- Vincoli: `chunk_id` deterministico, write atomica, no collisioni silenti.

### 2) ScoreStore
- `upsert_score(chunk_id, score, signals, ts)`
- `get_scores(chunk_ids|topic|window)`
- `topk(topic, k, filters)`
- Vincoli: persistenza, query top-k efficienti, serializzazione stabile.

### 3) TopicIndex
- `assign_topics(chunk_id, topics[])`
- `topk_by_topic(topic, k)`
- `rebuild_topic_index()`
- Vincoli: consistenza con ScoreStore, gestione topic assenti.

### 4) GlobalDigest
- `build_digest(scope) -> digest`
- `retrieve(query, strategy=\"hierarchical\")`
- Vincoli: fallback keyword, segnali qualità retrieval.

### 5) ContextBridge (`ContextManager`)
- `inject_memory_hierarchy(packet, budget)`
- `select_relevant_chunks(goal, failures, recency)`
- Vincoli: budget token/char rispettato, priorità segnali failure.

## Gap tecnici concreti
1. **Contratto unificato chunk/score/topic/global non esplicito** tra moduli.
2. **`chunk_id` deterministico non formalizzato end-to-end** come interfaccia.
3. **Scoring persistente/top-k** non esposto come API interna unica.
4. **Retrieval gerarchico + fallback keyword** non definito come strategia standard.
5. **Bridge esplicito verso `ContextManager`** da formalizzare con budget policy.
6. **Migrazione nodi legacy** da specificare con passi e rollback.
7. **Test matrix di integrazione** non centralizzata su acceptance #536.

## Insertion points proposti
- `igris/core/memory_graph.py`: nodo/edge contract e gerarchia.
- `igris/core/memory.py`: adapter storage (chunk + metadata).
- `igris/core/context_manager.py`: punto d’ingresso retrieval gerarchico.
- `igris/core/memory_validator.py`: invarianti contrattuali.
- `tests/test_phase2b_integration.py` + test mirati memoria: acceptance pipeline.

## Acceptance per chiudere #638
- Interfacce sopra documentate e approvate.
- Gap list priorizzata con impatto/rischio.
- Insertion points mappati a file concreti.
- Tracciabilità completa verso requisiti #536.
