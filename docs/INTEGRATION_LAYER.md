# Integration Layer — Epic #62

## Overview

The Integration Layer connects all IGRIS subsystems into a single
governed pipeline. It is the primary path for autonomous mission
execution, replacing the old autonomous_loop while keeping legacy
APIs compatible.

## Pipeline

```
Goal
 |
 v
Mission Controller  --> create + plan mission
 |
 v
Agent Reasoning Loop  --> observe-reason-act-observe
 |  |
 |  +-- Context Manager     (what the LLM sees)
 |  +-- Model Orchestrator   (which LLM decides)
 |  +-- Agent Action Schema  (validate action)
 |  +-- Code Navigation      (safe read-only tools)
 |  +-- Tool Runtime         (governed execution)
 |
 v
Per-step checks:
 |  +-- Teacher/Governor     (anti-loop, family saturation)
 |  +-- Decision Memory      (record outcome)
 |  +-- Rollback Manager     (backup before file write)
 |  +-- Risk gate            (block raw shell until #63)
 |
 v
Verify Mission  --> success criteria check
 |
 v
MissionReport   --> full decision trace
```

## Decision Reports

Each step produces a `DecisionReport` containing:
- Action schema (what the LLM proposed)
- Model/provider used
- Risk level
- Tool used and result
- Governor decision (approve/reject/shift/escalate)
- Memory recorded flag
- Rollback ID (if file modified)

## Action Families

Actions are grouped into families for governor tracking:

| Family | Actions |
|---|---|
| code_nav | search_code, find_files, list_directory, read_file_range, repo_map, find_symbol |
| code_edit | write_file, propose_patch, apply_patch |
| test | run_tests |
| git | git_status, git_diff |
| shell | shell_template, raw_shell_proposal |
| http | http_check |
| planning | update_plan |
| memory | record_memory |
| human | ask_user |
| terminal | finish, blocked |

## API Endpoints

### POST /api/integration/run-mission
Run a full governed mission.

### GET /api/integration/pipeline-status
Check availability of all pipeline components.

### GET /api/integration/action-families
Get action type to family mapping.

## Compatibility

The old `/api/loop/run` and `/api/loop/step` endpoints remain
functional. The new integration endpoints provide the governed
pipeline with Mission Controller, Governor, Memory, and Rollback
integration.
