# External Repo Sandbox Benchmark

IGRIS_GPT's workflow verified on an external sandbox project (`tests/fixtures/sandbox_repo`).

## Sandbox Project

A simple Python calculator with:
- `calculator.py` — add, subtract, multiply, divide, percentage (known divide-by-zero bug)
- `utils.py` — format_result, validate_number helpers
- `test_calculator.py` — unit tests (one intentionally failing)
- `README.md` — project docs

## Benchmark Scenarios

### 1. Simple Python Bugfix
**Task:** Fix divide-by-zero in `calculator.divide`
**Workflow:** mission -> plan (3 steps) -> materialize -> loop step -> patch proposal -> validation -> decision report -> memory
**Result:** Full workflow completes. Patch proposes `ValueError` check.

### 2. Failing Test Repair
**Task:** Identify and fix `test_divide_by_zero`
**Workflow:** mission -> plan -> materialize -> loop -> memory failure recording -> analysis
**Result:** Failure recorded in memory, analysis detects pattern, advisory-only.

### 3. Docs Update
**Task:** Add percentage function documentation to README
**Workflow:** mission -> plan -> materialize -> loop -> patch proposal (README) -> validation
**Result:** Safe text patch created and validated.

### 4. Small Refactor
**Task:** Add docstrings and input validation
**Workflow:** mission -> plan -> materialize -> loop -> patch proposal -> validation
**Result:** Refactor patch created without breaking existing functionality.

### 5. Multi-File Safe Patch
**Task:** Add history feature across calculator.py and utils.py
**Workflow:** mission -> plan -> materialize -> loop -> multi-file patch -> validation
**Result:** Two-file patch proposal created and validated safely.

## What Each Scenario Proves

| Scenario | Mission | Plan | Tasks | Patch | Validate | Memory | Report |
|----------|---------|------|-------|-------|----------|--------|--------|
| Bugfix | Y | Y | Y | Y | Y | Y | Y |
| Test repair | Y | Y | Y | - | - | Y | Y |
| Docs update | Y | Y | Y | Y | Y | Y | Y |
| Refactor | Y | Y | Y | Y | - | Y | Y |
| Multi-file | Y | Y | Y | Y | Y | Y | Y |

## Safety Verified

- No secrets in any benchmark output
- Memory analysis always advisory-only
- Diagnostics work after benchmark runs
- Patches validated before apply
- No auto-execution of patches
