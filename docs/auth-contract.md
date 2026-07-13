# Auth/Preflight Response Contract — IGRIS_GPT

_Epic #1301 — Auth & Session Single Source of Truth — PR-5A_

## Result objects

### `PreflightResult` (`igris/core/chat_interlocutor_preflight.py`)

The object returned by `run_preflight()` and consumed by `routes_01.py`.

**Security rule:** `PreflightResult` must never store a raw session token. The token is consumed by `extract_session_token()` / `resolve_session_identity()` and never reaches this object.

**Fields consumed by `routes_01.py`** — these are stable and must not be removed or renamed:

| Field | Type | Default | Used for |
|-------|------|---------|----------|
| `blocked` | `bool` | (required) | gate decision — True means request is denied |
| `trust_level` | `str` | (required) | identity tier passed to downstream logging |
| `session_authenticated` | `bool` | `False` | True when session token was valid and resolved a profile |
| `session_valid` | `bool` | `False` | True when token was structurally valid (may be expired) |
| `session_reason` | `str \| None` | `None` | Human-readable auth failure reason |
| `audit_event_id` | `str \| None` | `None` | ID of the audit log entry for this request |
| `interlocutor_id` | `str` | (required) | resolved identity (server-side, not client-claimed) |
| `block_reason` | `str \| None` | (required) | reason string when blocked=True |

**Session auth defaults are `False`/`None`** — an absent or failed token is not authenticated.

**`allowed` property:** `not blocked and not requires_clarification`. This is the positive gate and must remain derivable from `blocked`.

### `SessionIdentityResult` (`igris/core/chat_interlocutor_preflight.py`)

Internal object returned by `resolve_session_identity()`. Never leaves the preflight module.

**Security rule:** Raw token NEVER stored here — only `profile_id` and status. See source comment. `profile_id` must be the resolved profile ID from the auth store, never the raw input token.

| Field | Type | Description |
|-------|------|-------------|
| `profile_id` | `str` | Resolved profile ID from auth store |
| `authenticated` | `bool` | True if session was valid and found |
| `session_valid` | `bool` | True if token was structurally valid |
| `reason` | `str` | Failure reason (empty on success) |
| `session_id` | `str` | Session record ID (empty if not resolved) |

### `WriteAuthResult` (`igris/api/write_auth.py`)

Returned by `require_write_auth()`. Callers of `require_write_auth_or_raise()` receive only an HTTP exception — they never inspect the `WriteAuthResult` directly.

**Security rule:** No raw token field. The exception detail must not contain raw tokens.

| Field | HTTP outcome |
|-------|-------------|
| `allowed=False, http_status=401` | authentication_required — no token or invalid token |
| `allowed=False, http_status=403` | scope_denied — valid token but insufficient trust level |
| `allowed=True` | request proceeds |

`as_http_exception()` produces `{"ok": False, "error": <error_code>, "message": <msg>}`. The `error_code` and `message` fields must never contain raw tokens.

## Auth-required response shapes

When `IGRIS_REQUIRE_AUTH=true` and no valid session token is present, both endpoints return a stable shape:

### Messages endpoint (`POST /api/sessions/{id}/messages`)

```json
{
  "auth_required": true,
  "auth_actions": ["login", "enroll"],
  "auth_reason": "<reason string>",
  "response": "Prima di continuare devo riconoscerti. Accedi oppure registrati.",
  "interlocutor_id": "unknown",
  "trust_level": "untrusted"
}
```

**Backward-compat contract:** `auth_required`, `auth_actions`, `auth_reason` must always be present when auth is blocked. The frontend reads these to decide whether to show the login prompt.

### Stream endpoint (`POST /api/chat/stream`)

SSE event shape when auth is blocked:
```
data: {"type": "auth_required", "auth_required": true, "auth_actions": ["login", "enroll"], "auth_reason": "<reason>", "text": "..."}

data: [DONE]
```

**Backward-compat contract:** `auth_required: true` and `auth_actions` must appear in at least one SSE event before `[DONE]`.

## Rules

1. **No raw token in result objects.** `PreflightResult`, `SessionIdentityResult`, `WriteAuthResult` must never store a raw session or bearer token in any field.

2. **No raw token in error responses.** `WriteAuthResult.as_http_exception()` detail and all `auth_required` JSON responses must not contain raw tokens.

3. **Session auth fields default to `False`/`None`.** An absent or failed token must not accidentally appear authenticated due to a missing field or wrong default.

4. **Stable field names.** The fields listed in the `PreflightResult` table above must not be renamed or removed without updating `routes_01.py` and the guard tests.

5. **`auth_required` response keys are stable.** Frontend and integration tests rely on `auth_required`, `auth_actions`, `auth_reason` being present in blocked responses.

## Guard tests

`tests/test_auth_contract_guard.py` encodes all of the above as executable invariants (13 tests):

- No `session_token` / `token` / `raw_token` field in any result dataclass
- Required `PreflightResult` fields exist and have correct defaults
- `allowed` property is inverse of `blocked`
- `resolve_session_identity()` returns `profile_id`, not the raw token
- `WriteAuthResult.as_http_exception()` produces 401/403 with correct shape
- Exception detail contains no raw token
- Messages endpoint returns `auth_required=True` with `auth_actions` and `auth_reason` when blocked
- Stream endpoint emits `auth_required` SSE event when blocked
- No raw token in `auth_required` responses
