# Guided Actions — Intent-to-Action Suggestions

**Sprint 33 — v0.6 Human-Usable Console**

## Overview

When IGRIS chat answers an operational question, it now suggests safe next actions as clickable cards/buttons. This bridges the gap between "knowing what IGRIS can do" and "actually doing it."

## How It Works

1. **Intent Detection** — The existing personality module detects user intent from keywords
2. **Action Mapping** — Each intent maps to a curated list of `SuggestedAction` objects
3. **Response Enrichment** — Chat engine and streaming include `suggested_actions` in the response
4. **UI Rendering** — The chat panel renders actions as clickable cards below the response
5. **Execution** — Clicking a card calls the mapped safe API endpoint and shows the result

## Supported Intents and Actions

| Intent | Example Message | Actions |
|--------|----------------|---------|
| `machine_info` | "dammi info sulla macchina" | Show Status, Readiness, Project Context, Git Status, Create task |
| `network_info` | "info sulla rete" | Show Status, Readiness, Routing |
| `github_access` | "vedi il mio GitHub?" | Git Status, Git Diff, PR Summary, PR Dry Run (gated) |
| `capabilities` | "cosa puoi fare?" | Capabilities, Status, Readiness |
| `testing` | "controlla i test" | Run Tests, Recent Reports, Diagnostics |
| `git_local` | "git status" | Git Status, Diff, Branches, Safety Check |
| `patching` | "modifica il codice" | List Patches, Generate Patch, Git Diff |
| `missions` | "crea una missione" | List Missions, Decision Reports, Loop Status |
| `memory` | "mostra fallimenti" | Failures, Decisions, Saturation, Analyze Memory |
| `shell_request` | "esegui comando" | Available Commands, Git Status, Run Tests, Create Task |

## Safety

- **No free shell endpoints** — shell_request redirects to safe alternatives
- **Gated actions** — PR Dry Run requires `I_APPROVE_GITHUB_WRITE` approval
- **No secrets** — No action contains tokens, passwords, or API keys
- **Existing endpoints only** — All actions map to already-existing safe API endpoints
- **XSS-safe** — Action labels and descriptions are HTML-escaped before rendering

## API Endpoints

### GET /api/chat/actions
Returns all available actions grouped by intent.

### GET /api/chat/actions/{intent_name}
Returns actions for a specific intent. 404 if unknown.

### POST /api/chat/intent (updated)
Now includes `suggested_actions` in the response alongside intent and grounded_response.

### POST /api/sessions/{id}/messages (updated)
Now includes `suggested_actions` in the response.

## UI

Action cards appear below the assistant's response text:
- Blue border for safe actions
- Yellow border for gated actions (requires approval)
- Click to execute and show JSON result inline
- Responsive on mobile (smaller cards, wrapping)

## Gated Actions

Actions with `approval_required: true` show a "requires approval" badge and are visually distinct. The approval gate name (e.g., `I_APPROVE_GITHUB_WRITE`) is enforced server-side.
