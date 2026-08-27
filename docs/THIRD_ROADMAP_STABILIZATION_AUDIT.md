# Third Roadmap Stabilization Audit

## Date: 2026-08-27

## Main commit: `b362778`

## Roadmap PRs verified

| PR | Issue | State | Merge date |
|---|---|---|---|
| #1441 | #1322 | MERGED | 2026-08-27T00:50:27Z |
| #1442 | #1324 | MERGED | 2026-08-27T00:54:58Z |
| #1443 | #1325 | MERGED | 2026-08-27T00:55:02Z |
| #1444 | #1323 | MERGED | 2026-08-27T00:58:17Z |
| #1445 | #1328 | MERGED | 2026-08-27T00:58:22Z |
| #1449 | #1307 | MERGED | 2026-08-27T00:58:26Z |

## Issues verified

| Issue | State | Phase | Remaining work |
|---|---|---|---|
| #1322 | OPEN | Phase 2 complete | Phase 3 — lint rule + 25 INFRASTRUCTURE imports |
| #1324 | OPEN | Phase 2 complete | Phase 3 — OTel SDK bridge/export |
| #1325 | OPEN | Phase 2 complete | Phase 3 — UI integration + Phase 4 — sandboxing |
| #1323 | OPEN | Phase 2 complete | Phase 3 — real token streaming |
| #1328 | OPEN | Phase 2 complete | Broader interaction coverage |
| #1307 | OPEN | Evaluation + children | #1446, #1447, #1448 implementation |
| #1446 | OPEN | New | Worktree recovery |
| #1447 | OPEN | New | Provider degraded states |
| #1448 | OPEN | New | Partial restore |

## CI

All 8 recent CI runs: success.

## Local tests

- compileall: PASS
- pyright: 0 errors, 915 warnings
- pytest: 7217 passed, 40 skipped, 0 failed
- targeted suites: 184 passed, 25 skipped (E2E gated)

## VM

- VM commit: `b362778`
- VM pyright: 0 errors, 910 warnings
- compileall: PASS
- gauntlet: 15/15 PASSED
- diagnostics: healthy=true, 0 findings
- os/brief: ok=true
- trace headers: x-trace-id, x-request-id on every response
- plugin API: {"plugins":[],"count":0}
- VM targeted tests: 33 passed

## Subprocess governance

- 4 migrated modules clean (no subprocess import, use governed_run)
- 25 unauthorized modules still import subprocess (INFRASTRUCTURE class)
- #1322 acceptance criteria NOT fully met — significant work remains

## Trace middleware

- X-Trace-Id and X-Request-Id on every response
- Incoming propagation verified (trace-test-audit → x-trace-id: trace-test-audit)
- Auth, static files, health endpoints unaffected

## Plugin API

- GET /api/plugins: read-only, returns {"plugins":[],"count":0}
- No execution endpoint
- No class names or sensitive paths exposed
- Sandboxing explicitly pending

## WebSocket streaming

- word_split fallback simulation documented
- Auth enforced
- start/chunk/done protocol
- /ws/loop admin-only

## Playwright E2E

- 25 tests, all skip by default (IGRIS_E2E_TESTS=1)
- Interaction tests for chat, tab navigation, status panel
- No secrets required

## #1307 child issues

| Issue | Scope | Acceptance criteria clear? | Priority | Risk |
|---|---|---|---|---|
| #1446 | Worktree recovery | Yes | Medium | Medium |
| #1447 | Provider degraded states | Yes | Medium | Medium |
| #1448 | Partial restore | Yes | Medium | Medium |

## Open concerns

1. 25 unauthorized subprocess imports remain (INFRASTRUCTURE class)
2. Memory files were not updated during third roadmap (fixed in this audit)
3. WebSocket streaming is fallback simulation, not real token streaming
4. Plugin sandboxing not implemented

## Recommended next roadmap

| Priority | Issue | Current status | Why next | Risk | Suggested scope |
|---:|---|---|---|---|---|
| 1 | #1322 Phase 3 | 16 MIGRATE calls done, 25 INFRASTRUCTURE remain | Safety gap | Medium | Lint rule + INFRASTRUCTURE migration |
| 2 | #1324 Phase 3 | Trace middleware active | Observability | Low | OTel SDK bridge/export |
| 3 | #1325 Phase 3 | API endpoint active | Extensibility | Low | Plugin UI panel |
| 4 | #1323 Phase 3 | Word streaming fallback | UX | Medium | Real token streaming via orchestrator |
| 5 | #1328 | 15 interaction tests | E2E coverage | Low | Login, task, terminal tests |
| 6 | #1446 | New | Reliability | Medium | Worktree recovery |
| 7 | #1447 | New | Reliability | Medium | Provider circuit breaker |
| 8 | #1448 | New | Reliability | Medium | Partial restore integrity |
| 9 | pyright warnings | 915 warnings | Tech debt | Low | Bounded cleanup |
| 10 | #1306 | Open | Observability | Medium | Health dashboard |
