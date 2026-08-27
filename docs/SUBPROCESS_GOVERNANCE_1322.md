# Subprocess Governance Policy (#1322)

## Overview

This document describes the subprocess governance policy for IGRIS_GPT,
established by issue #1322 and enforced by `scripts/check_subprocess_governance.py`.

## Problem

`igris/core/` had 80+ direct subprocess calls bypassing `ToolRuntime`. This means:
- No risk classification
- No secret guard
- No audit trail
- No rollback tracking
- No output redaction

## Solution

### Phase 1 (PR #1433) — Audit
Classified every subprocess call as INFRASTRUCTURE, MIGRATE, or AUTHORIZED.

### Phase 2 (PR #1441) — Migration
Migrated 16 MIGRATE-classified calls from 4 modules to `governed_run()` in `tool_runtime.py`.

### Phase 3 (this PR) — Lint rule
AST-based governance check that prevents future unauthorized subprocess imports.

## Policy

### Always allowed (3 modules)

These are the authorized execution gateways:

| Module | Rationale |
|---|---|
| `igris/core/tool_runtime.py` | Authorized executor — `governed_run()` and `ToolRuntime` |
| `igris/core/devops_manager.py` | Authorized DevOps command runner |
| `igris/core/supervisor_backend.py` | Authorized supervisor execution backend |

### Infrastructure allowed (25 modules)

These modules use subprocess for legitimate infrastructure commands (git, gh,
system queries) that are not user-facing tool execution. They are allowlisted
pending Phase 4 evaluation/migration.

See `scripts/check_subprocess_governance.py` for the full list with rationale.

### Forbidden (4 modules)

These modules were migrated in Phase 2 to use `governed_run()` and must never
import subprocess again:

| Module | Migration |
|---|---|
| `igris/core/mbop_runner.py` | 6 calls migrated to `governed_run()` |
| `igris/core/smw_actions.py` | 7 calls migrated to `governed_run()` |
| `igris/core/smw_diagnosis.py` | 1 call migrated to `governed_run()` |
| `igris/core/smw_teach.py` | 2 calls migrated to `governed_run()` |

## Enforcement

### CI integration

The governance check runs as a separate CI job (`subprocess-governance`) on
every push and pull request. It fails if:
- Any new file imports subprocess outside the allowlist
- Any forbidden module reintroduces subprocess

### Pytest enforcement

`tests/test_subprocess_governance_1322.py` provides 13 tests verifying:
- Current repo passes the check
- Migrated modules don't import subprocess
- Migrated modules use `governed_run()`
- Unauthorized imports are detected
- Forbidden modules are detected
- Allowed modules pass
- Policy is internally consistent

## Remaining work

#1322 acceptance criteria require "Only authorized modules import subprocess."
Currently 25 INFRASTRUCTURE modules still import subprocess outside the 3
authorized executors. These are allowlisted with rationale but must be
evaluated for migration in Phase 4.

### Phase 4 — INFRASTRUCTURE evaluation

Each of the 25 INFRASTRUCTURE modules should be evaluated:
- Can the subprocess call be replaced by `governed_run()`?
- Is the call truly infrastructure (git, gh, system query)?
- Should the module be added to the authorized set?

Until Phase 4 is complete, #1322 remains OPEN.
