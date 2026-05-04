# Mission Planner & Task Graph

## Overview

The Mission Planner transforms high-level user missions into structured, multi-step plans with dependencies, success criteria, and task materialization. Plans are **deterministic** (no LLM required) and stored in `.igris/missions/`.

## What It Does

- **Create Mission**: Define a goal with title and description
- **Generate Plan**: Break description into ordered steps with dependencies
- **Materialize Tasks**: Convert plan steps into persistent tasks in the TaskEngine
- **Task Graph**: Visualize step dependencies as a directed graph

## What It Does NOT Do

- No automatic execution of tasks
- No LLM-based planning (deterministic keyword-based planner)
- No automatic commit/push
- No destructive actions

## How Planning Works

The planner uses a keyword-based approach:

1. **Numbered/bulleted lists**: Each line becomes a step with detected family
2. **Single description**: Auto-generates 3 steps: Analyze → Implement → Test
3. **Dependencies**: Sequential — each step depends on the previous
4. **Families**: `analyze`, `test`, `code`, `fix`, `refactor`, `docs`, `config`, `git`, `other`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/missions` | Create a new mission |
| `GET` | `/api/missions` | List all missions |
| `GET` | `/api/missions/{id}` | Get mission detail |
| `POST` | `/api/missions/{id}/plan` | Generate plan for mission |
| `POST` | `/api/missions/{id}/materialize-tasks` | Create tasks from plan |
| `GET` | `/api/missions/{id}/graph` | Get task dependency graph |

## UI

The **Mission Control** tab includes:
- Health, readiness, and project context (existing)
- Mission list with status badges
- Create mission form
- Mission detail with plan steps and action buttons
- Task graph visualization

## Workflow

1. **Create** a mission with title and description
2. **Plan** the mission → generates ordered steps
3. **Review** steps, dependencies, and success criteria
4. **Materialize** → creates persistent tasks in TaskEngine
5. **Execute** tasks manually or via future autonomous loop

## Persistence

Missions are stored as JSON in `.igris/missions/` (git-ignored).

## Safety

- All mission actions logged as timeline events
- No automatic execution
- Duplicate task titles are skipped during materialization
- Success criteria required for every step
