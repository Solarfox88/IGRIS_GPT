# IGRIS Open Items

Open issues and tech debt for IGRIS_GPT. Updated after every task.

Last updated: 2026-08-14

## Priority issues

| Priority | Issue | Status | Next action |
|---|---|---|---|
| P1 | #1296 | **closed** (PR #1347 merged `8fa9d8e`) | Fixed — task engine worker, safe validate, honest diagnostics |
| P0 | #1300 | open (EPIC) | Live Acceptance Harness — browser/runtime E2E validation |
| P0 | #1301 | open (EPIC, active) | Auth & Session SSOT — PR1–PR5A merged (#1345 merged `54b6b60`) |
| P2 | #1291 | **closed** (PR TBD) | Fixed — /api/chat/intent now gates code_change for limited users |
| P2 | #1290 | open | diagnostics starvation — task_engine/mission_controller unavailable (overlaps with #1296, partially fixed by #1347) |
| P2 | #1289 | open | API path inconsistency — `/api/github/prs`, `/api/github/issues`, `/api/git/log` do not exist |
| P2 | #1297 | open | Verifier/Reflection payload contract undocumented, misleading error |

## Tech debt

| Priority | Issue | Status | Next action |
|---|---|---|---|
| Critical | #1314 | **partial** (Phase 1 merged) | 476 generic `except Exception` — Phase 1: added logging to 46 silent catches in `igris/core/`; Phase 2: replace with specific exceptions (pending) |
| Critical | #1315 | **partial** (Phase 1 merged) | zero structured logging in `igris/core/` — Phase 1: StructuredFormatter + logging in 7 priority modules; Phase 2: remaining modules (pending) |
| Critical | #1316 | **partial** (Phase 1 merged) | no mypy/pyright type checking in CI — Phase 1: pyright basic mode configured + CI job added; Phase 2: fix type errors + standard mode (pending) |
| Tech debt | #1312 | **partial** (Phase 2 merged) | supervisor split — Phase 1: 8 sub-modules; Phase 2: 36 static methods extracted to supervisor_helpers.py; `self_repair_supervisor.py` still 6,013 lines (target <2000). Further extraction needed. |
| Refactor | #1317 (I1) | open | router anonymous routes `routes_01..10` — rename by domain |
| Refactor | #1318 (I2) | open | `app.js` monolithic 2401 lines — modularize into ES modules |
| Feature | #1319 (I4) | open | SQLite migration system / schema versioning |
| Testing | #1320 (I5) | open | integration tests with real LLM |
| Reliability | #1321 (I6) | open | graceful shutdown / crash recovery of loop state |
| Safety | #1322 (I3) | open | 80 direct subprocess calls bypass ToolRuntime |

## Milestones (M1–M8)

| Milestone | Issue | Status |
|---|---|---|
| M1 WebSocket streaming | #1323 | open |
| M2 OpenTelemetry / distributed tracing | #1324 | open |
| M3 Plugin system for extensible tools | #1325 | open |
| M4 Multi-tenancy with RBAC | #1326 | open |
| M5 Docker Compose production-ready | #1327 | open |
| M6 Playwright E2E tests | #1328 | open |
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
| Reliability / Crash Recovery / Backup / Migration Safety | #1307 | open |
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
