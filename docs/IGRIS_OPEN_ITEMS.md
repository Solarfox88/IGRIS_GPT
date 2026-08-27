# IGRIS Open Items

Open issues and tech debt for IGRIS_GPT. Updated after every task.

Last updated: 2026-08-27 (Stabilization audit after third roadmap)

## Completion policy

Items in this file are not considered complete just because a PR was merged.

An item is complete only when:

- the issue acceptance criteria are satisfied
- the **mandatory 20-pass quality gate** has been completed
- tests/gauntlet pass
- VM validation is done when applicable — with traceable evidence (VM commit, branch, service status, gauntlet command+result, diagnostics/os-brief endpoints)
- memory files are updated
- no hidden follow-up remains
- GitHub issue state verified (open issue = not complete unless explicitly explained)

If only part of the work was done, mark the item as:

```text
Phase complete, follow-up pending.
```

## Process correction hardening

The 20-pass quality gate now includes hard correction rules (ADR-IGRIS-0012):

- never commit directly on `main`
- verify branch before every commit
- runtime-impacting work requires VM branch validation before merge
- post-merge VM validation does not replace branch validation
- if VM/SSH validation is unavailable, runtime-impacting work is blocked unless the user explicitly approves an exception
- final roadmap reports must include a per-block compliance matrix

## Process violations

| Date | Block | Violation | Impact | Repair | Status |
|---|---|---|---|---|---|
| 2026-08-16 | Block 29 | Post-merge docs update committed directly on `main` (`590d978`) | docs-only, no runtime impact | Process correction PR + compliance matrix update; direct-main guard reinforced | documented |

## Import graph validation

Core refactors must include compile/import graph validation before merge (ADR-IGRIS-0013).

Required for supervisor, task engine, memory, routing, diagnostics, auth/security, logging, and shared helper/model modules.

Supervisor refactors must import every `igris.core.supervisor*.py` module before merge.

A runtime refactor with missing import graph evidence is not complete.

## Priority issues

| Priority | Issue | Status | Next action |
|---|---|---|---|
| P1 | #1296 | **closed** (PR #1347 merged `8fa9d8e`) | Fixed — task engine worker, safe validate, honest diagnostics |
| P0 | #1300 | open (EPIC) | Live Acceptance Harness — browser/runtime E2E validation |
| P0 | #1301 | open (EPIC, active) | Auth & Session SSOT — PR1–PR5A merged (#1345 merged `54b6b60`) |
| P2 | #1291 | **closed** (PR #1348 merged `19a1dc4`) | Fixed — /api/chat/intent now gates code_change for limited users |
| P2 | #1290 | **closed** (PR #1408 Block 37 + Block 38 maintenance) | Fixed — starvation false positive corrected, 3 stale tasks processed, diagnostics now healthy=true |
| P2 | #1289 | **CLOSED** (PR #1422 merged) | Fixed — backward-compatible API path aliases added |
| P2 | #1297 | **CLOSED** (PR #1423 merged) | Fixed — verifier/reflection error messages + payload schemas |

## Tech debt

| Priority | Issue | Status | Next action |
|---|---|---|---|
| Critical | #1314 | **CLOSED** — all 5 criteria MET | except Exception: 476→47 (<50). 0 except Exception:pass. Criterion 2: 141 catches now log, 13 silent pass (ImportError etc, explicitly allowed). Tests: 7072 passed. CI: green. #1314 CLOSED. |
| Critical | #1315 | **closed** — foundation complete (PR #1375 `4877168`) | Follow-up: **#1354 CLOSED** — structured logging acceptance criteria met by architecture (all 107 loggers inherit StructuredFormatter from root "igris" logger) |
| Critical | #1316 | **CLOSED** — pyright 0 errors, CI type-check job exists and is blocking, 25 type:ignore all have comments/codes, tests pass. Closed 2026-08-26. | All criteria MET |
| Tech debt | #1312 | **closed** — supervisor split complete | Follow-up: **#1371** CLOSED — `self_repair_supervisor.py` 1,844 lines (below 2,000 target); #1356 CLOSED; follow-up **#1395** for `agent_reasoning_loop.py` (2,477 lines) |
| Refactor | #1317 (I1) | **CLOSED** (PR #1424 merged) | Routers renamed by domain — routes_01..10 → semantic names |
| Refactor | #1318 (I2) | **CLOSED** (PR #1426 merged) | app.js 2401→170 lines, 13 ES modules extracted, all <500 lines |
| Feature | #1319 (I4) | **CLOSED** (PR #1427 merged) | SchemaManager + per-component migration registries, 12 tests |
| Testing | #1320 (I5) | open | integration tests with real LLM |
| Reliability | #1321 (I6) | **CLOSED** (PR #1428 merged) | LoopCheckpointManager + GracefulShutdownHandler + StepWatchdog, 17 tests |
| Safety | #1322 (I3) | **OPEN (Phase 1 done)** | 79 calls classified (55 INFRA, 18 MIGRATE). Phase 2: migrate 18 calls to ToolRuntime |

## Milestones (M1–M8)

| Milestone | Issue | Status |
|---|---|---|
| M1 WebSocket streaming | #1323 | **OPEN (Phase 1 done)** | /ws/chat + /ws/loop implemented. Phase 2: token-by-token LLM streaming |
| M2 OpenTelemetry / distributed tracing | #1324 | **OPEN (Phase 1 done)** | TraceContext + TraceSpan implemented. Phase 2: FastAPI middleware |
| M3 Plugin system for extensible tools | #1325 | **OPEN (Phase 1 done)** | ToolPlugin + PluginRegistry + discovery. Phase 2: API endpoint |
| M4 Multi-tenancy with RBAC | #1326 | open |
| M5 Docker Compose production-ready | #1327 | open |
| M6 Playwright E2E tests | #1328 | **OPEN (Phase 1 done)** | tests/e2e/ with 15 gated tests. Phase 2: interaction tests |
| M7 Rate limiting per-user | #1329 | open |
| M8 Backup automatico `.igris/` | #1330 | open |

## EPICs (P1)

| EPIC | Issue | Status |
|---|---|---|
| Memory Governance | #1302 | open |
| People Catalog | #1303 | open |
| Mission Control UX / Approval Center / Evidence Viewer | #1304 | open |
| Verifier Hard Gates / Capability Manifest | #1305 | open |
| Observability / Health Dashboard | #1306 | open |
| Reliability / Crash Recovery / Backup / Migration Safety | #1307 | **OPEN (evaluation done)** | 2/7 scope done, 4/7 partial, 1/7 not started. See docs/EPIC_1307_RELIABILITY_EVALUATION.md |
| Jarvis Red-Team Gauntlet | #1308 | open |
| Model Role Matrix / Benchmarking | #1309 | open |
| Product Documentation / Operator Runbooks | #1310 | open |

## Feature / research

| Issue | Status | Notes |
|---|---|---|
| #1333 | open | Live Graph Reactor UI |
| #682 | open | model role definition (Planner/Implementer/Critic/Escalation) |
| #625 | open | Vast.ai V100/GV100/RTX3090/RTX4090 tests |
| #620 | open | evaluate PrintingPress.dev |
| #527 | open | IGRIS as Personal OS paradigm |
| #352 | open | evaluate candidate reasoning models |
| #1271 | open | People Catalog / Person Registry — separate from identity/auth |
| #1355 | **CLOSED** — pyright 0 errors, CI blocking (PR #1384) | Closed 2026-08-15 |
| #1353 | **CLOSED** — Final cleanup: 76→49→47 except Exception (target <50 MET). 28 catches narrowed. 0 except Exception: pass. PR #1416 merged 982785c. #1353 closed 2026-08-26. | Closed |
| #1417 | **CLOSED** — 141 catches now log with debug, 13 silent pass kept (ImportError etc). PR #1419 merged b23a0a0. | Closed |
| #1371 | **CLOSED** — supervisor split complete, 1,844 lines (below 2,000) | Closed 2026-08-15 |
| #1395 | **CLOSED** (PR #1425 merged `403e2e0`) | agent_reasoning_loop.py 2477→1968 lines, 2 modules extracted |
## Third roadmap phase-complete items (2026-08-27)

| Issue | Phase completed | Remaining work | Child issues |
|---|---|---|---|
| #1322 | Phase 2 — 16 MIGRATE calls migrated to governed_run() | Phase 3 — lint rule + 25 INFRASTRUCTURE imports | — |
| #1324 | Phase 2 — FastAPI trace middleware (X-Trace-Id, X-Request-Id) | Phase 3 — OTel SDK bridge/export, Phase 4 — UI dashboard | — |
| #1325 | Phase 2 — /api/plugins read-only endpoint | Phase 3 — UI integration, Phase 4 — sandboxing | — |
| #1323 | Phase 2 — word-by-word streaming (fallback simulation) | Phase 3 — real token streaming via orchestrator, Phase 4 — HTTP fallback | — |
| #1328 | Phase 2 — 15 interaction tests (chat, tab, status) | Broader coverage — login, task, terminal, file browse | — |
| #1307 | Evaluation + 3 child issues created | #1446, #1447, #1448 implementation | #1446, #1447, #1448 |

## New child issues (2026-08-27)

| Issue | Scope | Priority | Risk |
|---|---|---|---|
| #1446 | Worktree recovery — dirty state detection | Medium | Medium |
| #1447 | Provider degraded states — circuit breaker | Medium | Medium |
| #1448 | Partial restore — integrity verification | Medium | Medium |
