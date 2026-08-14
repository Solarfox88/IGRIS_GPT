# IGRIS Worklog

Chronological worklog of all agent work on IGRIS_GPT. Append a row after every task.

## Worklog policy

Every worklog entry for a non-trivial PR must mention:

- issue/PR
- pass 1–10 summary (mandatory 10-pass completion rule)
- tests
- gauntlet
- VM validation if applicable
- before/after metrics
- honest status: complete / phase-complete / blocked / needs follow-up

| Date | Issue/PR | Agent | Summary | Tests | Merge commit |
|---|---|---|---|---|---|
| 2026-?? | #1278 | Codex/Claude | auth-first onboarding gate | — | `a18b32b` |
| 2026-?? | #1280 | Codex/Claude | debug registration — normalize FastAPI errors | — | `2d6fc3a` |
| 2026-?? | #1281 | Codex/Claude | rate limiter on static assets/LAN fix | — | `f8da9d7` |
| 2026-?? | #1283/#1284 | Codex/Claude | post-login state mismatch fix | — | `e881ab5` |
| 2026-?? | #1285 | Codex/Claude | real browser auth gate | — | `59a90ed` |
| 2026-?? | #1286 | Codex/Claude | project_root mismatch fix | — | `914a665` |
| 2026-?? | #1293 | Codex/Claude | P0 auth gate on all write/side-effect endpoints | `tests/test_write_endpoint_auth_gate.py` | `359df90` |
| 2026-06-09 | #1311 / PR #1311 | Codex/Claude | gate POST /api/tools/git/commit and /api/git/commit with write auth | `tests/test_write_endpoint_auth_gate.py` (+119) | `f603e04` |
| 2026-06-09 | #1312 / PR #1331 | Codex/Claude | refactor(C1): modularize self_repair_supervisor.py — extract 4 sub-modules (PARTIAL, file still 6208 lines) | — | `ea3d70b` |
| 2026-06-09 | #1295 / PR #1332 | Codex/Claude | dangerous intent routing — never chat_only for rm -rf, issue create, sudo | `tests/test_dangerous_intent_routing.py` (+354) | `d453add` |
| 2026-06-11 | #1313 / PR #1334 | Codex/Claude | centralize secret redaction helpers (19 files) | existing redaction tests | `7d8d4c0` |
| 2026-06-11 | #1294 / PR #1335 | Codex/Claude | implement memory cross-session persistence (23 files) | `tests/test_memory_cross_session.py` | `e716f68` |
| 2026-?? | #1337 Cat-B | Codex/Claude | detect `<REDACTED>` marker in secret check | — | `5094626` |
| 2026-?? | #1337-A / PR #1339 | Codex/Claude | bypass write-auth gate in integration tests — 401 → 200 | — | `cad25e4` |
| 2026-?? | #1301-PR1 / PR #1340 | Codex/Claude | auth root lazy — eliminate import-time IGRIS_PROJECT_ROOT | — | `8cfc172` |
| 2026-?? | #1301-PR2 / PR #1341 | Codex/Claude | add Config.igris_dir property | — | `07a6885` |
| 2026-?? | #1301-PR3 / PR #1342-1343 | Codex/Claude | replace CONFIG.project_root / ".igris" with CONFIG.igris_dir; InterlocutorAudit accepts project_root | — | `659adda` / `f1402ee` |
| 2026-?? | #1301-PR4A / PR #1344 | Codex/Claude | root consistency guard tests + auth-root-model.md | — | `f65210e` / `7878a7c` |
| 2026-08-14 | — | Devin | handoff bootstrap — synced main, verified PRs #1311/#1331/#1332/#1334/#1335, audited local clones, created persistent memory files | — | (not merged — docs PR pending) |
| 2026-08-14 | — | Devin | Hyper-V VM audit — inspected `IGRIS-GPT` VM (Off) via read-only VHDX mount in WSL; found repo at `/home/igris/IGRIS_GPT` on branch `fix/1301-pr5a-auth-contract-guard` @ `b7c7e74` (= PR #1345, already pushed); 119 worktrees (prunable), 3 old stashes, no unpushed work; gauntlet 14/14 PASSED | — | (audit only, no changes) |
| 2026-08-14 | #1346 / PR #1346 | Devin | docs: add persistent IGRIS project memory (AGENTS.md + 5 memory files) | — | `553b6f0` |
| 2026-08-14 | — | Devin | VM restore — started IGRIS-GPT VM, configured static IP 192.168.1.253 via netplan, switched to IGRIS External Switch, SSH via paramiko, updated repo to main @ 553b6f0, restarted igris.service, verified http://192.168.1.253:7778 reachable; confirmed #1296 symptoms live (3 pending tasks, starvation=1, task_engine=null) | — | (infra, no code) |
| 2026-08-14 | #1296 / PR #1347 | Devin | fix(#1296): task engine reliability — add failed/approval_required statuses, attempts/last_error fields, process_one_pending_task worker, mark_running/fail_task methods, validate endpoint safe (400/404 no 500), process-one endpoint with write_auth, context_routes wires task_engine via app.state, diagnostics task_engine_state, gauntlet task_engine_reliability check (15th) | `tests/test_task_engine_reliability.py` (16/16), gauntlet 14/15 (memory_cross_session pre-existing WinError 32), regression 89/89, VM validated | `8fa9d8e` |
| 2026-08-14 | #1291 / PR #1348 | Devin | fix(#1291): code_change gating — /api/chat/intent now uses JarvisRequestRouter to classify messages; limited users get blocked=true+scope_denied=true on code_change/patching; admin gets approval_required=true; untrusted gets blocked=true; response includes blocked/approval_required/scope_denied/interlocutor_id/trust_level | `tests/test_code_change_gating.py` (12/12), regression 105/105, gauntlet 14/15 (memory_cross_session pre-existing), VM validated | `19a1dc4` |
| 2026-08-14 | #1301-PR5A / PR #1345 | Devin | docs(#1301-PR5A): auth/preflight contract guard — 13 guard tests + docs/auth-contract.md; no runtime changes; codifies auth/preflight response contract as executable invariants | `tests/test_auth_contract_guard.py` (13/13) | `54b6b60` |
| 2026-08-14 | #1314 Phase 1 / PR #1349 | Devin | fix(#1314): Phase 1 — add logging to 46 silent `except Exception:` catches in 16 `igris/core/` files; no behavior change, only observability; `logger.debug(..., exc_info=True)` before pass/continue/return | `tests/test_except_exception_cleanup.py` (9/9), regression 105/105, gauntlet 14/15 (memory_cross_session pre-existing) | `0ac7a7b` |
| 2026-08-14 | #1315 Phase 1 / PR #1350 | Devin | fix(#1315): Phase 1 — structured JSON logging; new `igris/core/structured_logging.py` with `StructuredFormatter`, `configure_structured_logging()` (env var `IGRIS_LOG_LEVEL`, file rotation 10MB/5 files); added structured logging to 7 priority modules (task_engine, tool_runtime, model_orchestrator, chat_engine, verifier_registry, unified_memory, diagnostics) | `tests/test_structured_logging.py` (10/10), regression 135/135, gauntlet 14/15 (memory_cross_session pre-existing) | `79fe072` |
| 2026-08-14 | #1316 Phase 1 / PR #1351 | Devin | fix(#1316): Phase 1 — pyright type checking; added `[tool.pyright]` to pyproject.toml (basic mode, Python 3.12, include igris/, exclude .local/); added `type-check` job to CI workflow (pyright --outputjson); added pyright to dev dependencies | `tests/test_pyright_config.py` (7/7) | `9866bf5` |
| 2026-08-14 | #1312 Phase 2 / PR #1352 | Devin | fix(#1312): Phase 2 — extract 36 pure static methods from `SelfRepairSupervisor` into `igris/core/supervisor_helpers.py` (576 lines); `self_repair_supervisor.py` reduced 6,208→6,013 lines; no behavior change, all methods delegate to extracted functions | `tests/test_supervisor_split.py` (10/10), regression 146/146, gauntlet 14/15 (memory_cross_session pre-existing) | `67c3783` |
| 2026-08-14 | checkpoint | Devin | roadmap alignment checkpoint — verified all PRs merged via GitHub API; created follow-up issues #1353–#1356; updated VM to latest main `84b39ef`; found VM Python env `.venv/bin/python`; fixed gauntlet `task_engine_reliability` check (`mkdir` without `exist_ok=True` → `[Errno 17]` on Linux); VM gauntlet now **15/15 PASSED**; corrected memory files with honest status (Phase 1 merged ≠ complete) | VM gauntlet 15/15 via `.venv/bin/python` | (pending merge) |
| 2026-08-14 | #1357 / PR #1357 | Devin | docs: align roadmap and VM validation status + fix gauntlet mkdir (#1357) | — | `bac942c` |
| 2026-08-14 | #1358 / PR #1358 | Devin | docs: make 5-pass completion rule mandatory — added 5-pass rule to AGENTS.md, ADR-0008, policy sections in all memory files | — | `f5c501c` |
| 2026-08-14 | #1355 Phase 2 | Devin | chore(#1355): pyright Phase 2 — fixed 83 type errors (174→91, 48% reduction); fixed missing imports (AgentResult, Any, os, logger, EvidenceBundle, TopicTree), platform-specific APIs (os.killpg, signal.SIGKILL, fcntl, os.statvfs, os.sys→sys), wrong attribute/method names (resource→relevant_resource, list_proposals→list_patch_proposals, MemoryTopicTree→TopicTree), wrong parameter name (cli/main.py app=→positional), added missing dataclass fields (blocked_reason, created_at, project_root), replaced dynamic proxy classes with SimpleNamespace, moved flags_list from monkey-patch to proper method; added 3 new config tests; documented CI `|| true` with Phase 2 comment | `tests/test_pyright_config.py` (10/10), regression 169/169, gauntlet 14/15 (memory_cross_session pre-existing Windows) | (pending merge) |
| 2026-08-14 | #1353 Phase 2 | Devin | chore(#1353): except Exception cleanup Phase 2 — narrowed 92 broad catches (627→535); JSON parsing→(json.JSONDecodeError, TypeError, ValueError), file I/O→(OSError, PermissionError, UnicodeDecodeError), SQLite→sqlite3.Error, subprocess→(subprocess.SubprocessError, OSError), network→(urllib.error.URLError, ConnectionError, TimeoutError, OSError), import→(ImportError, AttributeError); top-level safety boundaries kept as except Exception; added 4 new tests (count decreased, no bare pass in changed modules, proactive_engine specific types, memory_gc specific types); no bare except Exception: pass remaining | `tests/test_except_exception_cleanup.py` (13/13), regression 173/173, gauntlet 14/15 (memory_cross_session pre-existing Windows) | (pending merge) |
| 2026-08-14 | #1354 Phase 2 | Devin | chore(#1354): structured logging Phase 2 — wired `configure_structured_logging()` into `create_app()` server startup; added redaction to `StructuredFormatter` (secrets in log messages, extra fields, and exception messages are redacted using regex patterns for token/password/secret/api_key/bearer/Authorization headers/GitHub tokens/OpenAI keys); file logging now opt-in via `IGRIS_LOG_FILE` env var (default: console-only to avoid Windows file lock issues); handler cleanup on re-configure (closes file handles); added 12 new tests (redaction for secrets/auth headers/cookie/bearer/exception messages/GitHub tokens/Basic auth/API keys, server startup wiring, env var log level, handler cleanup, non-secret message preservation) | `tests/test_structured_logging.py` (22/22), regression 185/185, gauntlet 14/15 (memory_cross_session pre-existing Windows) | (pending merge) |
| 2026-08-14 | process upgrade | Devin | docs: upgrade completion rule to 10-pass quality gate — replaced mandatory 5-pass rule with mandatory 10-pass completion rule in AGENTS.md; added 12 quality hardening rules (GitHub reality beats local claims, open issue = not complete, phase ≠ parent, no silent criteria reinterpretation, no duplicated centralized logic, no fake "no behavior change", VM is runtime truth, tests must prove claim, measurable before/after, update VM after merge, PR body must include proof, memory files must be consistent); added ADR-IGRIS-0009; marked ADR-IGRIS-0008 as superseded; updated PROJECT_MEMORY, HANDOFF, OPEN_ITEMS, WORKLOG | — | (pending merge) |
| 2026-08-14 | process upgrade | Devin | docs: require traceable validation evidence — added rule 7a to AGENTS.md quality hardening (VM commit, branch, service status, gauntlet command+result, diagnostics/os-brief endpoints, post-merge VM proof); added ADR-IGRIS-0010; updated PROJECT_MEMORY, HANDOFF, OPEN_ITEMS with traceable evidence requirement | — | (pending merge) |

## Test commands reference

```
pytest tests/test_task_engine_reliability.py -q
pytest tests/test_mission_first_execution.py -q
pytest tests/test_dangerous_intent_routing.py -q
pytest tests/test_write_endpoint_auth_gate.py -q
pytest tests/test_memory_cross_session.py -q
pytest tests/test_redaction_centralized.py -q
pytest tests/test_jarvis_core_gauntlet.py -q
python -m igris.core.jarvis_core_gauntlet
```
