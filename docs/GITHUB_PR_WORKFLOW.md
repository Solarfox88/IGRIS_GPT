# GitHub PR Workflow — Gated, No Auto-Merge

IGRIS_GPT provides a controlled GitHub workflow with explicit approval gates for all remote/destructive operations.

## Safety Principles

1. **No push to main/master** — protected branches are always blocked
2. **No force push** — not implemented, not available
3. **No auto-merge** — no merge endpoint exists
4. **Approval required** — all write operations require `I_APPROVE_GITHUB_WRITE`
5. **Safety checks enforced** — secrets, runtime artifacts, and sensitive files block operations
6. **Branch allowlist** — only recognized prefixes (devin/, feature/, fix/, etc.)

## Approval Token

All gated operations require:

```
approval = "I_APPROVE_GITHUB_WRITE"
```

Without this token, operations are rejected with a clear error message.

## Endpoints

### POST /api/git/commit

Gated commit with safety checks.

**Request:**
```json
{
  "message": "feat: add new feature",
  "approval": "I_APPROVE_GITHUB_WRITE"
}
```

**Gates:**
- Not on protected branch (main/master)
- Approval token present
- Safety check passes (no secrets, no runtime artifacts, files staged)

### POST /api/github/pr/prepare

Prepare PR body from branch info. Does NOT create the PR.

**Request:**
```json
{
  "base": "main",
  "title": "Optional PR title",
  "extra_context": "Optional additional context"
}
```

**Returns:** title, body, branch, diffstat, commit_count, warnings

### POST /api/github/pr/create

Gated PR creation. Currently mock/gated (no real GitHub API calls).

**Request:**
```json
{
  "title": "PR Title",
  "body": "PR description",
  "base": "main",
  "approval": "I_APPROVE_GITHUB_WRITE"
}
```

**Gates:**
- Approval token present
- Not from protected branch
- Branch matches allowlist
- No secret content in diff

### GET /api/github/pr/status

Read-only PR readiness status.

**Returns:**
```json
{
  "branch": "devin/feature-x",
  "on_protected_branch": false,
  "commits_ahead": 3,
  "commits_behind": 0,
  "safety_check_passed": true,
  "branch_valid": true,
  "can_push": true,
  "can_create_pr": true,
  "merge_endpoint_available": false,
  "auto_merge_available": false
}
```

## Branch Allowlist

Only branches matching these prefixes can be pushed or used for PRs:

| Prefix | Example |
|--------|---------|
| devin/ | devin/feature-name |
| feature/ | feature/new-ui |
| fix/ | fix/bug-123 |
| bugfix/ | bugfix/issue-45 |
| hotfix/ | hotfix/security-patch |
| sprint/ | sprint/v04-work |
| release/ | release/v1.0 |
| chore/ | chore/deps-update |
| docs/ | docs/readme-update |

## What's NOT Available

| Operation | Status | Reason |
|-----------|--------|--------|
| Push to main | Blocked | Protected branch |
| Force push | Not implemented | Safety risk |
| Auto-merge | Not implemented | Requires manual review |
| Merge endpoint | Not implemented | No auto-merge by design |
| Direct API calls | Gated/mock | Real API requires token + approval |

## Security

- All responses redact secrets (API keys, tokens)
- Runtime artifacts blocked from staging
- Sensitive filenames blocked
- Branch names sanitized
- No secrets in PR body or commit messages
