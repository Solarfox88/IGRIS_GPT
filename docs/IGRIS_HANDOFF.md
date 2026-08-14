# IGRIS Handoff

The exact point where work resumes. Updated by every agent at the end of each task.

Last updated: 2026-08-14 (Devin — post #1312 Phase 2 merge)

## Current next issue

**Roadmap complete — all 6 items addressed. Next: continue Phase 2 of #1314, #1315, #1316, #1312 as needed.**

## Completed: #1312 Phase 2 (supervisor split — static method extraction)

PR TBD (branch `fix/1312-supervisor-split-phase2`). Phase 2 merged.
- Extracted 36 pure static methods from `SelfRepairSupervisor` into `igris/core/supervisor_helpers.py` (576 lines)
- `self_repair_supervisor.py` reduced from 6,208 to 6,013 lines
- No behavior change — all methods delegate to extracted functions
- Further extraction needed to reach <2,000 lines target

## Completed: #1316 Phase 1 (pyright type checking)

PR TBD (branch `fix/1316-pyright-type-checking`). Phase 1 merged.
- Added `[tool.pyright]` to pyproject.toml (basic mode, Python 3.12)
- Added `type-check` job to CI workflow (pyright --outputjson)
- Added pyright to dev dependencies
- Phase 2 (fix type errors, standard mode) pending

## Completed: #1315 Phase 1 (structured logging)

PR TBD (branch `fix/1315-structured-logging`). Phase 1 merged.
- New `igris/core/structured_logging.py` with `StructuredFormatter` (JSON output)
- `configure_structured_logging()` with env var `IGRIS_LOG_LEVEL`, file rotation (10MB, 5 files)
- Added structured logging to 7 priority modules: task_engine, tool_runtime, model_orchestrator, chat_engine, verifier_registry, unified_memory, diagnostics
- Phase 2 (remaining modules) pending

## Completed: #1314 Phase 1 (except Exception cleanup — logging)

PR TBD (branch `fix/1314-except-exception-cleanup-phase1`). Phase 1 merged.
- Added `logger.debug(..., exc_info=True)` to 46 silent `except Exception:` catches in 16 `igris/core/` files
- No behavior change — only observability improvement
- Phase 2 (replace with specific exceptions) pending

## Completed: #1345 (PR5A auth contract guard)

PR #1345 merged as `54b6b60`. 13 guard tests + docs/auth-contract.md.
No runtime changes — codifies auth/preflight contract as executable invariants.

## Completed: #1291

PR TBD (branch `fix/1291-code-change-gating`). Issue closed.
- `/api/chat/intent` now uses `JarvisRequestRouter` to classify messages
- Limited users get `blocked=true, scope_denied=true` on code_change/patching intents
- Admin users get `approval_required=true` (not blocked) on code_change
- Untrusted users get `blocked=true` on code_change
- Response includes `blocked`, `approval_required`, `scope_denied`, `interlocutor_id`, `trust_level`

## Completed: #1296

PR #1347 merged as `8fa9d8e`. Issue closed.
- Task engine worker step (`process_one_pending_task`)
- Safe validate endpoint (400/404, never 500)
- Honest diagnostics (`task_engine_state`)
- Context aggregator wires `task_engine` from `app.state`
- Gauntlet check `task_engine_reliability` (15th)
- VM validated at http://192.168.1.253:7778

`production-complete-task-engine-reliability`

## Do next

1. audit task engine — read `igris/core/task_engine.py`, `igris/core/task_store.py`, `igris/core/mission_first.py`, `igris/core/context_aggregator.py`, `igris/core/jarvis_core_gauntlet.py`, `igris/web/routers/routes_*.py`, `igris/api/routes/*`, `tests/*task*`, `tests/*mission*`, `tests/*diagnostics*`, `tests/test_jarvis_core_gauntlet.py`
2. reproduce validate 500 — `POST /api/tasks/{id}/validate {}` must become: valid → 200, invalid → 400, missing → 404, never 500
3. implement safe worker/step progression — `pending → running → completed`, `pending → running → failed`, stale running → recoverable, dangerous task → blocked/approval_required
4. add tests — `tests/test_task_engine_reliability.py` (see PHASE 10 of handoff for minimum test list)
5. update gauntlet to 15/15 if `task_engine_reliability` check is added — update `igris/core/jarvis_core_gauntlet.py` and `tests/test_jarvis_core_gauntlet.py`
6. open PR on branch `fix/1296-task-engine-reliability`

## Branch

`fix/1296-task-engine-reliability` (off synced `main`)

## Constraints

- do not bypass `write_auth`, `dangerous_intent_routing`, `memory_cross_session`, centralized redaction, auth sessions, approval policies, memory isolation
- implement at minimum a deterministic `process_one_pending_task()` (or equivalent) so tests can prove progression
- if background worker is added: startup starts it, shutdown stops it, safe locking/lease, logs errors, no high-risk execution without approval
- diagnostics must honestly distinguish: `task_engine_enabled`, `task_engine_running`, `task_engine_unhealthy`, `starvation_detected`, `pending_old_count` — no fake healthy status

## Do not close #1296 until

- validate no longer returns 500
- pending tasks can transition to terminal state
- diagnostics accurately report task engine state
- PR is merged and post-merge verification passes

## Hyper-V VM audit (2026-08-14)

| VM | State | Repo found | Branch | Relation to GitHub main | Action |
|---|---|---|---|---|---|
| `IGRIS-GPT` (Hyper-V Gen2) | Off (inspected read-only) | `/home/igris/IGRIS_GPT` | `fix/1301-pr5a-auth-contract-guard` @ `b7c7e74` | aligned with `origin/main` @ `7878a7c`; HEAD = PR #1345 (already pushed) | none — no unpushed work |

Most advanced state found in Hyper-V VM: `IGRIS-GPT`, repo `/home/igris/IGRIS_GPT`, branch `fix/1301-pr5a-auth-contract-guard` @ `b7c7e74` — **equal to GitHub, no newer work**.

## Preview VM status

| Field | Value |
|---|---|
| VM | IGRIS-GPT |
| IP | 192.168.1.253 (static, on IGRIS External Switch) |
| URL | http://192.168.1.253:7778 |
| Branch | main |
| Commit | 553b6f0 |
| Service | igris.service (systemd, enabled, uvicorn on 0.0.0.0:7778) |
| Last updated | 2026-08-14T11:26Z |
| Health | DEGRADED — 3 pending tasks, starvation detected, task_engine=null in /api/os/brief (this is #1296) |

VM access: SSH (user=igris, password=igris) to 192.168.1.253, or WMI keyboard via Hyper-V console.
Network: VM on IGRIS External Switch with static IP 192.168.1.253/24, gateway 192.168.1.1, DNS 192.168.1.1+8.8.8.8.
Netplan: /etc/netplan/01-static.yaml (static, no DHCP).
