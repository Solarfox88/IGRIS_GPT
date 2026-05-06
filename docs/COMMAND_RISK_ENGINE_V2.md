# Command Risk Engine v2 — Epic #63

## Overview

Multi-level risk classification and governance for shell commands.
Enables governed shell access without sacrificing security.

## Policy Hierarchy

1. **Structured Tool** → always preferred (safe, typed, validated)
2. **Template parametrized** → safer than raw (known shape, validated params)
3. **Raw shell proposal** → escape hatch, fully gated through risk engine

## Pipeline

```
Raw Shell Proposal
        |
        v
  parse_command()       → ParsedCommand (flags, patterns)
        |
        v
  classify_command_risk()  → deterministic: LOW/MEDIUM/HIGH/CRITICAL/UNKNOWN
        |
        v
  LLM Risk Review       → advisory only (via Model Orchestrator)
  (for MEDIUM/HIGH/UNKNOWN)
        |
        v
  resolve_final_risk()  → max(deterministic, llm)
        |
        v
  apply_policy()        → allowed | blocked | needs_approval
```

## Risk Levels

| Level | Policy | Examples |
|---|---|---|
| LOW | Allowed | ls, cat, grep, git status, pytest |
| MEDIUM | Allowed with logging | pip install, curl, redirect, subshell |
| HIGH | Needs approval + rollback | sudo, rm, systemctl, docker, nginx, git push |
| CRITICAL | Blocked | force push, curl\|bash, rm -rf *, DROP TABLE, iptables, .env access |
| UNKNOWN | Needs approval | Unrecognized commands |

## Shell Parser

Detects 24+ dangerous patterns:
- sudo/su, rm/delete/unlink, chmod/chown
- systemctl/service, docker/compose, nginx/apache/certbot
- apt/pip/npm/pnpm/yarn, git push/reset/clean/force
- curl\|bash, pipes, redirects, subshells, chains
- absolute paths, wildcards, network calls
- database commands/destructive, firewall, DNS
- .env/secrets/keys/tokens access

## LLM Risk Reviewer

- Called for MEDIUM, HIGH, UNKNOWN deterministic classifications
- Uses Model Orchestrator (no direct provider calls)
- Output is advisory JSON with risk, reasons, affected paths/services,
  rollback needs, prechecks, postchecks, safer alternative
- **Final decision always stays with IGRIS Policy Engine**
- Falls back to deterministic classification if LLM unavailable

## API Endpoints

### POST /api/risk/evaluate
Evaluate a raw shell command.

### POST /api/risk/evaluate-template
Evaluate a parametrized shell template.

### POST /api/risk/parse
Parse a command into components.

### GET /api/risk/levels
List all risk levels.

## Template Risk Reduction

Parametrized templates receive a one-level risk reduction:
- HIGH → MEDIUM
- MEDIUM → LOW
- Templates validate parameters before rendering
