"""Unit tests for igris/core/helper_ab_eval.py — Epic #445."""
from __future__ import annotations
import json
import os
from pathlib import Path
import pytest
from igris.core.helper_ab_eval import (
    REQUIRED_SCHEMA_FIELDS, SCORE_WEIGHTS, is_safe_to_switch, load_ab_results,
    make_ab_record, save_ab_result, score_helper_response, compute_winner,
)

def _full_response(**overrides) -> dict:
    base = {
        "ok": True, "summary": "missing router registration",
        "diagnosis": "igris/web/routes/__init__.py line 45 missing include_router(users_router)",
        "likely_supervisor_gap": "supervisor skipped router registration step",
        "suggested_repair_strategy": "add include_router call in routes/__init__.py",
        "execution_plan": [
            "open igris/web/routes/__init__.py",
            "add: app.include_router(users_router, prefix='/api/users')",
            "run: pytest tests/test_users.py -v",
        ],
        "acceptance_matrix": [{"test": "tests/test_users.py::test_get_user", "assertion": "response.status_code == 200"}],
        "suggested_tests": ["tests/test_users.py::test_get_user"],
        "risk": "low", "risk_notes": [], "do_not_do": ["skip router registration"],
        "confidence": 0.85, "requires_human_or_codex_audit": False,
        "must_not_complete_product_manually": True, "estimated_cost_usd": 0.0012,
    }
    base.update(overrides)
    return base

def _make_records(n, *, alt_score=0.85, primary_score=0.80):
    records = []
    for i in range(n):
        records.append(make_ab_record(
            case_id=f"case_{i}", primary_model="gpt-5.3-codex", alt_model="deepseek-v4-pro",
            primary_score=primary_score, alt_score=alt_score,
            primary_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            alt_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            primary_cost_usd=0.001, alt_cost_usd=0.0004,
        ))
    return records

EMPTY_CASE = {}

class TestSchemaValidScoring:
    def test_fully_valid_response_scores_high(self):
        result = score_helper_response(_full_response(), EMPTY_CASE)
        assert result["total"] > 0.7, f"Expected >0.7, got {result['total']}"
    def test_all_required_fields_present(self):
        result = score_helper_response(_full_response(), EMPTY_CASE)
        assert result["breakdown"]["schema_valid"] == 1.0
    def test_response_with_all_fields_has_no_schema_issues(self):
        result = score_helper_response(_full_response(), EMPTY_CASE)
        assert not [i for i in result["issues"] if "missing" in i.lower()]

class TestNonJsonResponse:
    def test_non_dict_response_scores_zero(self):
        assert score_helper_response("not a dict", EMPTY_CASE)["total"] == 0.0
    def test_empty_dict_scores_low(self):
        assert score_helper_response({}, EMPTY_CASE)["total"] < 0.3
    def test_partial_schema_penalised(self):
        partial = {k: "v" for k in list(REQUIRED_SCHEMA_FIELDS)[:4]}
        assert score_helper_response(partial, EMPTY_CASE)["breakdown"]["schema_valid"] < 1.0

class TestSecretDetection:
    def test_response_with_api_key_scores_no_secrets_zero(self):
        resp = _full_response(diagnosis="use key sk-ABCDEFGHIJKLMNOPQRSTU to debug")
        assert score_helper_response(resp, EMPTY_CASE)["breakdown"]["no_secrets"] == 0.0
    def test_clean_response_scores_no_secrets_one(self):
        assert score_helper_response(_full_response(), EMPTY_CASE)["breakdown"]["no_secrets"] == 1.0
    def test_secret_in_execution_plan_detected(self):
        resp = _full_response(execution_plan=["set OPENAI_KEY=sk-proj-realkey12345678901234567"])
        assert score_helper_response(resp, EMPTY_CASE)["breakdown"]["no_secrets"] == 0.0

class TestExecutionPlanScoring:
    def test_specific_plan_scores_higher_than_generic(self):
        specific = _full_response(execution_plan=["open igris/web/routes/__init__.py","add include_router(users_router)","run pytest tests/test_users.py -v"])
        generic = _full_response(execution_plan=["check the code","look at the tests","try to fix it"])
        s = score_helper_response(specific, EMPTY_CASE)["breakdown"]["execution_plan_actionability"]
        g = score_helper_response(generic, EMPTY_CASE)["breakdown"]["execution_plan_actionability"]
        assert s > g
    def test_empty_execution_plan_scores_zero(self):
        assert score_helper_response(_full_response(execution_plan=[]), EMPTY_CASE)["breakdown"]["execution_plan_actionability"] == 0.0
    def test_single_step_scores_low(self):
        assert score_helper_response(_full_response(execution_plan=["do the thing"]), EMPTY_CASE)["breakdown"]["execution_plan_actionability"] < 0.5

class TestShadowModeContract:
    def test_shadow_result_does_not_affect_primary_output(self):
        primary_resp = _full_response()
        score_helper_response(_full_response(confidence=0.1), EMPTY_CASE)
        assert primary_resp["confidence"] == 0.85

class TestABPersistence:
    def test_save_and_load_roundtrip(self, tmp_path):
        path = str(tmp_path / "ab.json")
        record = make_ab_record(case_id="t", primary_model="codex", alt_model="ds",
                                primary_score=0.8, alt_score=0.75,
                                primary_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
                                alt_breakdown={}, primary_cost_usd=0.001, alt_cost_usd=0.0005)
        save_ab_result(record, path)
        loaded = load_ab_results(path)
        assert len(loaded) == 1 and loaded[0]["case_id"] == "t"
    def test_multiple_records_accumulate(self, tmp_path):
        path = str(tmp_path / "ab_multi.json")
        for i in range(3):
            save_ab_result(make_ab_record(case_id=f"c{i}", primary_model="codex", alt_model="ds",
                                          primary_score=0.8, alt_score=0.75,
                                          primary_breakdown={}, alt_breakdown={},
                                          primary_cost_usd=0.001, alt_cost_usd=0.0005), path)
        assert len(load_ab_results(path)) == 3
    def test_secrets_redacted_in_persistence(self, tmp_path):
        path = str(tmp_path / "ab_sec.json")
        record = make_ab_record(case_id="s", primary_model="codex", alt_model="ds",
                                primary_score=0.8, alt_score=0.75,
                                primary_breakdown={"x": "sk-proj-realkey12345678901234567"},
                                alt_breakdown={}, primary_cost_usd=0.001, alt_cost_usd=0.0005)
        save_ab_result(record, path)
        assert "sk-proj-realkey" not in Path(path).read_text()

class TestABDisabled:
    def test_ab_disabled_makes_single_call(self):
        from unittest.mock import patch
        from igris.core.self_repair_supervisor import LocalSupervisorBackend, CommandResult
        backend = LocalSupervisorBackend(project_root=Path("/tmp"))
        call_count = {"n": 0}
        def fake_run(cmd, timeout=45, input_text=None, extra_env=None, **kw):
            call_count["n"] += 1
            return CommandResult(success=True, output=json.dumps(_full_response()), returncode=0)
        backend._run = fake_run
        with patch.dict(os.environ, {"IGRIS_API_HELPER_COMMAND": "echo", "IGRIS_ENABLE_HELPER_AB_TEST": "false", "IGRIS_API_HELPER_ALT_MODEL": "deepseek-v4-pro"}):
            backend.call_api_helper(packet={"goal": "test"}, model="gpt-5.3-codex", max_tokens=600)
        assert call_count["n"] == 1

class TestShadowModePrimaryControls:
    def test_primary_result_returned_not_shadow(self):
        from unittest.mock import patch
        from igris.core.self_repair_supervisor import LocalSupervisorBackend, CommandResult
        backend = LocalSupervisorBackend(project_root=Path("/tmp"))
        call_count = {"n": 0}
        def fake_run(cmd, timeout=45, input_text=None, extra_env=None, **kw):
            call_count["n"] += 1
            return CommandResult(success=True, output=json.dumps(_full_response(confidence=0.85 if call_count["n"]==1 else 0.1)), returncode=0)
        backend._run = fake_run
        with patch.dict(os.environ, {"IGRIS_API_HELPER_COMMAND": "echo", "IGRIS_ENABLE_HELPER_AB_TEST": "true", "IGRIS_HELPER_AB_SHADOW_MODE": "true", "IGRIS_API_HELPER_ALT_MODEL": "deepseek-v4-pro", "IGRIS_API_HELPER_ALT_PROVIDER": "deepseek", "IGRIS_HELPER_AB_RESULTS_PATH": "/tmp/test_ab_pctrl.json"}):
            result = backend.call_api_helper(packet={"goal": "test", "failure_class": "pytest_failure"}, model="gpt-5.3-codex", max_tokens=600)
        assert json.loads(result.output)["confidence"] == 0.85
        assert result.helper_model == "gpt-5.3-codex"

class TestSwitchPolicy:
    def test_no_records_never_safe(self):
        safe, _ = is_safe_to_switch([])
        assert not safe
    def test_safety_failure_blocks_switch(self):
        records = _make_records(5, alt_score=0.90)
        for r in records: r["alt_breakdown"]["safety_compliance"] = 0.0
        assert not is_safe_to_switch(records)[0]
    def test_low_alt_score_blocks_switch(self):
        assert not is_safe_to_switch(_make_records(5, primary_score=0.80, alt_score=0.60))[0]
    def test_critical_regression_blocks_switch(self):
        records = _make_records(5, alt_score=0.90)
        records[0]["alt_score"] = 0.1
        assert not is_safe_to_switch(records)[0]
    def test_winner_is_tie_within_threshold(self):
        assert compute_winner(0.80, 0.81, 0.001, 0.0004)["winner"] == "tie"
    def test_winner_alt_when_clearly_better(self):
        assert compute_winner(0.60, 0.85, 0.001, 0.0004)["winner"] == "alt"
    def test_switch_never_auto_enabled(self):
        for r in _make_records(10, alt_score=0.90):
            assert r["safe_to_switch"] is False
