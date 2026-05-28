# Post-Subissue Evaluation — #824 Evidence Depth

Status: **passed**

## What Changed
- Added structured evidence classification in mission execution results:
  - `evidence_depth`: `missing_evidence` | `shallow_evidence` | `sufficient_evidence`
  - `evidence_tags`: `command_executed`, `artifact_changed`, `file_updated`, `report_updated`, `test_executed`, `test_passed`, `dry_run_evidence`, `missing_evidence`
- Extended execution adapter to classify evidence deterministically per action result.
- Extended action verifier with `evidence_summary` (insufficient vs sufficient evidence actions).
- Added minimal multi-step guard in quality gate:
  - multi-step mission cannot pass quality gate if successful actions are only shallow/missing evidence.
  - this is intentionally minimal and serves #825, not a full policy hardening.

## Tests Executed
- `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_mission_execution_and_gates.py` → **14 passed**
- `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_mission_orchestrator.py tests/test_mission_brain_schema_report.py tests/test_mission_understand_and_plan.py` → **7 passed**

## Replay / Delta (Targeted)
- Replay artifact: `reports/mission_brain/hardening/824/hardening_824_replay.json`
- Replayed false-completed sources:
  - `#791 M2`
  - `#792 M4`
- After #824 both are now diagnostically non-completable with:
  - `declared_status_after_824=partial`
  - `insufficient_evidence_detected=true`
  - evidence depths all `shallow_evidence`

## What Is Now Measurable
- Per-action evidence depth is now explicit and serializable.
- Multi-step insufficient evidence is now visible in quality-gate gaps.
- False-completed pattern is now observable as evidence-depth insufficiency (ready for stricter policy in #825).

## #825 Propagation Decision
- Decision: **#825 confirmed**.
- Scope refinement for #825:
  1. keep using `evidence_depth`/`evidence_tags` introduced in #824 as hard input;
  2. implement stricter multi-step thresholds and checklist coverage requirements;
  3. do not rework architecture; remain surgical.
