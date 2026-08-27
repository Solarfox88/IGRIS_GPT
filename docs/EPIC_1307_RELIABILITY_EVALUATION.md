# EPIC #1307 — Reliability Evaluation (2026-08-26)

## Status: PARTIALLY COMPLETE — remains OPEN

This EPIC covers 7 scope areas. Several have been addressed by recent roadmap work, but significant items remain.

## Scope evaluation

### 1. Mission recovery — PARTIALLY DONE

**Done:**
- #1321 (PR #1428): `LoopCheckpointManager` provides checkpoint persistence for reasoning loop state
- `GracefulShutdownHandler` handles graceful shutdown
- `StepWatchdog` detects step timeouts

**Remaining:**
- Mission recovery after restart (running → recoverable/failed transition)
- Timeline recovery event registration
- Final report interruption signaling
- Resume consent safety check
- High-risk mission non-auto-resume

### 2. Storage integrity — PARTIALLY DONE

**Done:**
- #1319 (PR #1427): `SchemaManager` provides SQLite schema versioning
- Per-component migration registries for memory_graph, embedding_store, memory_scorer, memory_topic_tree
- Auth sessions, profiles, audit stored in structured format

**Remaining:**
- Automated corruption detection for JSON files
- Recovery procedures for corrupted auth sessions/profiles
- Memory index integrity verification
- Evidence bundle validation
- Capability manifest validation

### 3. Backup/snapshot — DONE

**Done:**
- #1330 (PR #1431): `BackupManager` provides:
  - Scheduled backup of .igris/ → .igris/backups/
  - Retention policy (configurable, default 10)
  - Exclusion of temporary files (__pycache__, .log, .lock, checkpoints/)
  - SQLite database integrity preserved
  - Metadata written per backup

**Remaining:**
- Snapshot before migration (can be added to SchemaManager)
- Snapshot before bulk forget/delete
- Manual snapshot endpoint/CLI
- No secrets in default export (needs verification)

### 4. Restore — PARTIALLY DONE

**Done:**
- #1330 (PR #1431): `BackupManager.restore()` provides full restore from backup
- Data integrity preserved during restore

**Remaining:**
- Restore memory only
- Restore mission state only
- Dry-run restore
- Schema validation during restore
- Conflict report
- Rollback failed restore

### 5. Migration safety — DONE

**Done:**
- #1319 (PR #1427): `SchemaManager` provides:
  - Version tracking via `schema_version` table
  - Migration functions per component
  - Idempotent migrations
  - Data preservation across migrations

**Remaining:**
- Backup before migration (can integrate with BackupManager)
- Corruption handling during migration
- Migration report generation

### 6. Provider/tool resilience — PARTIALLY DONE

**Done:**
- Model orchestrator has circuit breaker and fallback chain
- Tool runtime has timeout and error handling
- Dangerous intent routing prevents unsafe operations

**Remaining:**
- LLM provider down → degraded state (not crash)
- GitHub API failure → degraded state
- DevOps backend failure → degraded state
- Browser runner failure → degraded state
- Memory backend failure → degraded state
- Verifier unavailable → degraded state
- Network timeout → degraded state

### 7. Worktree recovery — NOT DONE

**Not started:**
- Worktree dirty state detection
- Automatic cleanup
- Stash recovery
- Branch recovery

## Summary

| Scope | Status | Done by |
|---|---|---|
| 1. Mission recovery | PARTIALLY DONE | #1321 (checkpoint/shutdown) |
| 2. Storage integrity | PARTIALLY DONE | #1319 (schema versioning) |
| 3. Backup/snapshot | DONE | #1330 (BackupManager) |
| 4. Restore | PARTIALLY DONE | #1330 (full restore) |
| 5. Migration safety | DONE | #1319 (SchemaManager) |
| 6. Provider resilience | PARTIALLY DONE | Existing circuit breaker |
| 7. Worktree recovery | NOT DONE | — |

## Recommendation

#1307 should remain OPEN. The following issues could be created as follow-ups:
- Mission recovery after restart (scope 1 remaining)
- Storage corruption detection (scope 2 remaining)
- Restore partial/dry-run (scope 4 remaining)
- Provider degraded state handling (scope 6 remaining)
- Worktree recovery (scope 7)

## Follow-up issues created (Phase 2)

The following child issues were created to track remaining scope from #1307:

- #1446 — Worktree recovery — dirty state detection and automatic cleanup
- #1447 — Provider degraded states — LLM provider failover and circuit breaker
- #1448 — Partial restore — backup restore with integrity verification

These issues track the remaining scope areas that were NOT DONE in the initial
evaluation. #1307 remains OPEN until all child issues are resolved.
