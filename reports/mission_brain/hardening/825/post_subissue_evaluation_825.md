# Post-Subissue Evaluation — #825 Quality Gate Multi-Step Hardening

Status: **passed**

## What Changed
- Hardened quality gate to consume `evidence_depth`/`evidence_tags` from #824 systematically.
- Added explicit quality reasons:
  - `shallow_evidence`
  - `missing_evidence`
  - `insufficient_multistep_evidence`
  - `incomplete_checklist_evidence`
- Added checklist evidence coverage evaluation:
  - multi-step requires sufficient evidence coverage per checklist item.
- Enforced rule:
  - multi-step cannot pass quality gate when one or more successful actions are shallow/missing evidence.

## Tests Executed
- `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_mission_execution_and_gates.py` → **19 passed**
- `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_mission_orchestrator.py tests/test_mission_brain_schema_report.py tests/test_mission_understand_and_plan.py tests/test_mission_validation_runner.py` → **8 passed**

## Replay / Delta
- Replay artifact: `reports/mission_brain/hardening/825/hardening_825_replay.json`
- Replayed false-completed sources:
  - `#791 M2`
  - `#792 M4`
- Result after #825:
  - both are non-completed (`partial`)
  - `false_completed_count=0`
  - `critical_false_completed_count=0`
  - explicit reasons include:
    - `insufficient_multistep_evidence`
    - `incomplete_checklist_evidence`

## Requested #825 checks coverage
1. single-step sufficient evidence → pass possible ✅
2. single-step shallow evidence → quality fail / partial ✅
3. multi-step all sufficient → pass ✅
4. multi-step at least one shallow → fail/partial ✅
5. multi-step missing evidence → fail ✅
6. checklist without sufficient evidence coverage → fail ✅
7. replay #791/M2 + #792/M4 non-completed ✅
8. mission-brain regression subset passed ✅

## #826 Propagation Decision
- Decision: **#826 confirmed**.
- Scope refinement for #826:
  1. align completion policy with manual review severity using new quality reasons;
  2. prevent auto-`completed` when manual policy would classify `partial`;
  3. keep changes surgical and deterministic.
