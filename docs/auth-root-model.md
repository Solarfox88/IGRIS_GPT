# Auth Root Model — IGRIS_GPT

_Epic #1301 — Auth & Session Single Source of Truth_

## The two root env vars

IGRIS uses two distinct project root env vars that serve different purposes and must not be mixed.

| Env var | Read by | What it governs |
|---------|---------|----------------|
| `IGRIS_PROJECT_ROOT` | auth layer (`write_auth.py`, `auth_routes.py`, `interlocutor.py`, `action_guard.py`, `routes_01.py` preflight block) | auth sessions, credentials, enrollment tokens, audit log, delegation keys, identity resolver, authorization gate |
| `PROJECT_ROOT` | workspace layer (`CONFIG.project_root`, most route handlers) | missions, tasks, memory, code navigation, reflections, crash recovery, validations, a2a artifacts |

In production these two can point to the same directory. In test environments they **must** be independently settable, and the test suite exploits this.

## The `.igris` directory

`.igris` is the runtime state directory under a project root. It is always `<project_root>/.igris`.

- **Canonical property:** `CONFIG.igris_dir == CONFIG.project_root / ".igris"` — defined in `igris/models/config.py` as a `@property`.
- Use `CONFIG.igris_dir` (not `CONFIG.project_root / ".igris"` inline) in any new workspace-layer code.
- Auth layer derives its own `.igris` path from `IGRIS_PROJECT_ROOT`, not from `CONFIG`.

## Where runtime state lives

| Artifact | Path | Root source |
|----------|------|-------------|
| Auth sessions | `IGRIS_PROJECT_ROOT/.igris/auth/sessions.json` | `IGRIS_PROJECT_ROOT` |
| Auth credentials | `IGRIS_PROJECT_ROOT/.igris/auth/credentials.json` | `IGRIS_PROJECT_ROOT` |
| Enrollment tokens | `IGRIS_PROJECT_ROOT/.igris/auth/enrollments.json` | `IGRIS_PROJECT_ROOT` |
| Audit log | `IGRIS_PROJECT_ROOT/.igris/interlocutor_audit.jsonl` | `project_root` passed to `InterlocutorAudit` (falls back to `CONFIG.igris_dir`) |
| Identity profiles | `IGRIS_PROJECT_ROOT/.igris/identity/profiles.json` | `IGRIS_PROJECT_ROOT` |
| Delegation keys | `IGRIS_PROJECT_ROOT/.igris/delegation_keys/` | `IGRIS_PROJECT_ROOT` |
| Long-term memory | `PROJECT_ROOT/.igris/memory/long_term/` | `CONFIG.igris_dir` |
| Browser artifacts | `PROJECT_ROOT/.igris/browser/artifacts/` | `CONFIG.igris_dir` |
| Execution reports | `PROJECT_ROOT/.igris/reports/` | `CONFIG.igris_dir` |
| Supervisor runs | `PROJECT_ROOT/.igris/supervisor_runs.json` | `CONFIG.igris_dir` |
| A2A task store | `PROJECT_ROOT/.igris/a2a/` | `CONFIG.igris_dir` |
| Validations | `PROJECT_ROOT/.igris/validations/` | `CONFIG.igris_dir` |

## Auth root resolution rules

### Rule 1 — auth layer uses `IGRIS_PROJECT_ROOT`, resolved lazily

```python
# igris/api/write_auth.py
def _get_auth_root() -> str:
    return os.environ.get("IGRIS_PROJECT_ROOT") or "."
```

- Read at **call time**, not at import time — env var changes after import are respected.
- Fallback `"."` = CWD. Never `Path.home()`.
- `auth_routes.py` imports and calls `_get_auth_root()` directly — no inline env reads.
- `routes_01.py` preflight reads `os.environ.get("IGRIS_PROJECT_ROOT") or "."` directly, with explicit comment explaining why it must not fall back to `CONFIG.project_root`.

### Rule 2 — workspace layer uses `CONFIG.project_root`

```python
# igris/models/config.py
project_root: Path = Field(default_factory=lambda: Path(os.getenv("PROJECT_ROOT", ".")))
```

- Captured at `Config.load()` time. Route handlers use `CONFIG.project_root` for all workspace operations.
- Do NOT use `CONFIG.project_root` to derive the auth store path.

### Rule 3 — preflight must not use `Path.home()`

`chat_interlocutor_preflight.py` is on the request hot path and must never fall back to `Path.home()`. All fallbacks in preflight use `"."`:

```python
root = project_root or "."
```

Auth-related callers always pass `project_root` explicitly (sourced from `IGRIS_PROJECT_ROOT`).

### Rule 4 — `InterlocutorAudit` accepts explicit `project_root`

```python
InterlocutorAudit(project_root=project_root)
```

When `project_root` is given, audit path = `project_root/.igris/interlocutor_audit.jsonl`.  
When not given, falls back to `CONFIG.igris_dir / "interlocutor_audit.jsonl"`.  
`path=` parameter overrides both (used by tests and legacy callers).

## Remaining `Path.home()` occurrences (documented, acceptable)

These are all in workspace/learning/memory modules — **not** in the auth or preflight path. They follow the pattern: try `CONFIG.project_root`, fall back to `Path.home()` only if `CONFIG` fails to import (i.e. catastrophic import error).

| File | Line | Pattern | Category |
|------|------|---------|----------|
| `igris/core/memory_retrieval_hybrid.py` | 104 | `Path(project_root) if project_root else Path.home()` | workspace memory |
| `igris/core/learning_ranker.py` | 96 | `except: project_root = Path.home()` | learning |
| `igris/core/verifier_registry.py` | 542 | `except: project_root = Path.home()` | verifier |
| `igris/core/jarvis_core_gauntlet.py` | 206 | `except: project_root = Path.home()` | gauntlet |
| `igris/core/context_aggregator.py` | 113 | `except: project_root = Path.home()` | context |
| `igris/core/conversation_memory.py` | 180, 302, 388 | `Path(project_root or Path.home())` | conversation memory |
| `igris/core/rank_gauntlet.py` | 51 | `Path(project_root or Path.home() / "IGRIS_GPT")` | gauntlet — note hardcoded dir |
| `igris/core/after_action_review.py` | 203 | `except: project_root = Path.home()` | learning |
| `igris/core/jarvis_request_router.py` | 327 | `except: project_root = Path.home()` | routing |
| `igris/core/shadow_ml.py` | 184, 277, 372 | `except: project_root = Path.home()` | shadow ML |
| `igris/core/mission_first.py` | 170 | `except: project_root = Path.home()` | mission |
| `igris/core/learning_feedback.py` | 64 | `except: project_root = Path.home()` | learning |
| `igris/core/unified_memory.py` | 111 | `except: project_root = Path.home()` | memory |

**Note on `rank_gauntlet.py:51`:** `Path.home() / "IGRIS_GPT"` hardcodes a project directory name. This is harmless in CI (project_root is always passed) but warrants cleanup if rank_gauntlet is used outside the IGRIS_GPT repository.

## Import-time `IGRIS_PROJECT_ROOT` captures (documented, low-risk)

Three files capture `IGRIS_PROJECT_ROOT` at module level with a `"."` fallback:

| File | Pattern |
|------|---------|
| `igris/api/routes/interlocutor.py` | `_PROJECT_ROOT = os.environ.get("IGRIS_PROJECT_ROOT", ".")` |
| `igris/core/action_guard.py` | `_PROJECT_ROOT = os.environ.get("IGRIS_PROJECT_ROOT", ".")` |
| `igris/api/routes/tts.py` | `_PROJECT_ROOT = os.environ.get("IGRIS_PROJECT_ROOT", ".")` |

These differ from `write_auth.py` (fixed in PR-1): they capture once at import time. They are acceptable because:
1. They are not on the auth session resolution path (no session lookup).
2. Their operations (identity resolution, authorization gate, TTS) read profiles/authorization from the same root that was set at server startup.
3. The `"."` fallback is consistent with the rest of the auth layer.

If test isolation requires changing `IGRIS_PROJECT_ROOT` after import, these modules must be reloaded — or avoided by passing `project_root` explicitly to the underlying classes.

## Guard tests

`tests/test_root_consistency_guard.py` encodes all of the above as executable invariants:

- `test_write_auth_get_auth_root_reads_env_lazily` — lazy resolution survives env var change
- `test_write_auth_no_module_level_project_root_capture` — no `_VAR = os.environ.get(...)` at module level in write_auth
- `test_auth_routes_uses_get_auth_root_not_direct_env` — auth_routes delegates to `_get_auth_root()`
- `test_config_igris_dir_always_equals_project_root_dot_igris` — property invariant
- `test_config_igris_dir_not_in_model_dump` — not a stored field
- `test_preflight_audit_lands_under_project_root_not_home` — end-to-end audit path
- `test_preflight_source_has_no_path_home` — static source check
- `test_routes_01_preflight_uses_igris_project_root_not_config` — routes_01 invariant
- `test_auth_root_fallback_to_dot_when_igris_project_root_unset` — fallback chain
- `test_preflight_fallback_uses_dot_not_home` — source-level check
- `test_igris_project_root_and_project_root_are_independent` — two-root independence
