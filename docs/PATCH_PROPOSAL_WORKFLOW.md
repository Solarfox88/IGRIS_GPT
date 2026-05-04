# Patch Proposal Workflow

## Overview

IGRIS_GPT includes a controlled patch proposal system that allows proposing, reviewing, validating, and applying code modifications safely. No changes are applied without explicit validation and approval.

## What It Does

- Propose file modifications or new file creation
- Generate unified diffs for review
- Validate proposals against safety rules before applying
- Apply only validated, safe changes
- Track all actions in the agent timeline
- Persist proposals in `.igris/patches/`

## What It Does NOT Do

- **No automatic commit/push** — changes are applied to the working tree only
- **No free shell** — cannot execute arbitrary commands
- **No file editor** — only structured proposals
- **No delete** — file deletion is blocked in this version
- **No binary files** — only text files are supported
- **No files outside project root** — path traversal is blocked

## Safety Rules

Validation blocks:

| Rule | Blocked |
|------|---------|
| Path traversal | `../` escaping project root |
| Sensitive files | `.env`, `credentials.json`, `id_rsa`, etc. |
| Sensitive names | Files containing `key`, `token`, `secret`, `credential`, `password` |
| Protected dirs | `.git`, `.igris`, `logs`, `__pycache__`, `.pytest_cache`, `.venv`, `.ruff_cache`, `node_modules`, `*.egg-info` |
| Binary extensions | `.exe`, `.dll`, `.so`, `.bin`, `.whl`, `.tar`, `.gz`, `.zip`, `.png`, `.jpg`, etc. |
| Secret content | API keys, tokens, passwords detected in file content |
| Delete action | Not allowed (marked high-risk) |
| Large files | Content exceeding 500 KB |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/patches` | List all proposals |
| `POST` | `/api/patches/propose` | Create a new proposal |
| `GET` | `/api/patches/{id}` | Get proposal detail with diff |
| `POST` | `/api/patches/{id}/validate` | Run safety validation |
| `POST` | `/api/patches/{id}/apply` | Apply (only if validated) |
| `POST` | `/api/patches/{id}/reject` | Reject with reason |

### Create Proposal

```bash
curl -X POST http://localhost:7778/api/patches/propose \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Add documentation",
    "description": "Add getting started guide",
    "files": [
      {
        "path": "docs/getting-started.md",
        "action": "create",
        "after": "# Getting Started\n\nWelcome to IGRIS_GPT.\n"
      }
    ]
  }'
```

### Validate

```bash
curl -X POST http://localhost:7778/api/patches/{proposal_id}/validate
```

### Apply

```bash
curl -X POST http://localhost:7778/api/patches/{proposal_id}/apply
```

### Reject

```bash
curl -X POST http://localhost:7778/api/patches/{proposal_id}/reject \
  -H "Content-Type: application/json" \
  -d '{"reason": "Not needed at this time"}'
```

## UI

The **Patches** tab in the agentic console provides:

- List of all proposals with status badges (proposed/validated/applied/rejected)
- Form to create new proposals (title, description, file path, action, content)
- Diff preview with syntax-highlighted additions/deletions
- Validate, Apply, and Reject buttons
- Safety validation results with detailed reasons

## Recommended Workflow

1. **Propose** — Create a patch proposal via API or UI
2. **Review** — Inspect the generated diff
3. **Validate** — Run safety checks
4. **Apply** — Apply only if validation passes
5. **Test** — Run `python -m pytest -q` to verify
6. **Commit** — Manually commit changes (no auto-commit)

## Proposal Statuses

| Status | Meaning |
|--------|---------|
| `proposed` | Created, awaiting validation |
| `validated` | Passed safety checks, ready to apply |
| `applied` | Changes written to files |
| `rejected` | Rejected with reason |

## Persistence

Proposals persist in `.igris/patches/` as JSON files. This directory is gitignored and created at runtime.

## Why No Automatic Commit

Automatic commit is intentionally not implemented to:

- Allow human review before committing
- Prevent accidental commits of unsafe changes
- Keep the git history clean and intentional
- Support future Git workflow integration as a separate feature
