# IGRIS Handoff

The exact point where work resumes. Updated by every agent at the end of each task.

Last updated: 2026-08-14 (Devin desktop handoff bootstrap)

## Current next issue

**#1296 — P1: Tasks bloccate in pending — task_engine non esegue, validate restituisce 500**

## Symptoms (from issue)

- `GET /api/tasks` → 3 tasks, all `pending`
- `GET /api/os/brief` → `task_engine=null`, `mission_controller=null`
- `GET /api/diagnostics/summary` → `healthy=false`, `starvation=1`
- `POST /api/tasks/1/validate {}` → 500 Internal Server Error
- `POST /api/loop/step` → 200 but stays at step 0, does not truly advance

## Target

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
