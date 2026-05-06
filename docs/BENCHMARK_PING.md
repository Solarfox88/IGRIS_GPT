# Real Operational Benchmark — Epic #64

## Overview

First real end-to-end operational benchmark for IGRIS. The benchmark
mission is:

> "Add /api/ping endpoint that returns {"pong": true}, add test,
> execute pytest, fix errors, produce report."

## What It Measures

| Phase | Component | Validates |
|---|---|---|
| 1. code_navigation | CodeNavigator | Finds server.py, locates create_app |
| 2. context_manager | ContextManager | Builds context for goal |
| 3. reasoning_loop | AgentReasoningLoop | Runs observe-reason-act cycle |
| 4. tool_runtime | ToolRuntime | Executes git status |
| 5. risk_engine | CommandRiskEngine | Safe=allowed, dangerous=blocked |
| 6. test_execution | ToolRuntime.run_tests | Pytest runs and passes |
| 7. memory | DecisionMemory | Records and retrieves decisions |
| 8. governor | TeacherGovernor | Evaluates task families |

## Modes

### Deterministic (default)
Validates each subsystem independently without LLM. Suitable for
CI and automated testing.

### Integration
Runs the full IntegrationLayer pipeline with Mission Controller,
Reasoning Loop, Memory, Governor. Requires LLM for full operation;
falls back to degraded mode.

## API Endpoints

### GET /api/ping
The benchmark target endpoint. Returns `{"pong": true}`.

### POST /api/benchmark/run
Run the benchmark. Body: `{"mode": "deterministic"|"integration"}`.

### GET /api/benchmark/phases
List all benchmark phases and the goal.

## Benchmark Report

The benchmark produces a structured report:
- Phase pass/fail status
- Duration
- Commands executed
- Files modified
- Errors encountered
- Full mission report (integration mode)

## Definition of Done

After Epics #58-#64, IGRIS can execute the benchmark mission
passing through:
- Mission Controller
- Agent Registry / role mode
- Code Navigation
- Context Manager
- Model Orchestrator
- Agent Reasoning Loop
- Command Risk Engine
- Safety / Rollback
- Tool Runtime
- Verifier
- Memory
- Teacher / Governor
- Final Report
