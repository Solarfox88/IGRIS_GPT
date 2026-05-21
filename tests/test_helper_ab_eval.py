"""
Tests for helper_ab_eval: scorer, persistence, hybrid switch policy.

Covers:
- Dimensional score keys (schema_score, safety_score, execution_plan_actionability_score, etc.)
- Model identity fields persisted in records
- Model mismatch invalidates switch
- Generic advice penalized, specific execution plan rewarded
- Downstream usefulness: unknown does not break scoring
- Updated safe_to_switch gates (10 organic valid, alt_wins>=2, semantic/decomp regression)
- No secrets persisted
"""
from __future__ import annotations
import json, os, tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from igris.core.helper_ab_eval import (
    REQUIRED_SCHEMA_FIELDS, SCORE_WEIGHTS,
    is_safe_to_switch, load_ab_results,
    make_ab_record, save_ab_result, score_helper_response,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _full_response(**overrides):
    base = {
        "ok": True,
        "diagnosis": "FastAPI TestClient non importato in tests/conftest.py riga 12",
        "likely_supervisor_gap": "test setup mancante in conftest.py riga 12",
        "suggested_repair_strategy": "aggiorna tests/conftest.py con fixture app",
        "execution_plan": [
            "apri tests/conftest.py riga 12",
            "aggiungi @pytest.fixture def app(): ...",
            "usa TestClient(app) in tests/test_items.py",
        ],
        "acceptance_matrix": [
            {"test": "tests/test_items.py::test_create_item", "assertion": "status_code == 201"},
        ],
        "suggested_tests": ["tests/test_items.py::test_create_item"],
        "do_not_do": ["non modificare la logica del endpoint"],
        "risk": "low",
        "confidence": 0.9,
        "requires_human_or_codex_audit": False,
        "must_not_complete_product_manually": True,
    }
    base.update(overrides)
    return base


def _make_records(
    n, primary_score=0.75, alt_score=0.75,
    source="organic_run", case_ids=None,
    primary_breakdown=None, alt_breakdown=None,
    primary_requested_model="", primary_served_model="",
):
    bd = primary_breakdown or {k: 1.0 for k in SCORE_WEIGHTS}
    abd = alt_breakdown or {k: 1.0 for k in SCORE_WEIGHTS}
    ids = case_ids or [f"case_{i}" for i in range(n)]
    return [
        make_ab_record(
            case_id=ids[i % len(ids)],
            primary_model="gpt-5.3-codex",
            alt_model="deepseek-v4-pro",
            primary_score=primary_score,
            alt_score=alt_score,
            primary_breakdown=bd,
            alt_breakdown=abd,
            primary_cost_usd=0.01,
            alt_cost_usd=0.003,
            source=source,
            primary_requested_model=primary_requested_model,
            primary_served_model=primary_served_model,
        )
        for i in range(n)
    ]


def _synthetic(n=9, **kw):
    return _make_records(n, source="synthetic_fixture", **kw)


def _organic(n=10, case_ids=None, **kw):
    cids = case_ids or [
        "pytest_failure", "semantic_incomplete_stub", "missing_tests",
        "decomposition_required", "reasoning_loop",
        "workspace_dirty", "missing_ui_visibility", "budget_exceeded",
        "api_escalation_failed", "config_integrity",
    ]
    return _make_records(n, source="organic_run", case_ids=cids, **kw)


def _organic_alt_wins(n=10):
    """10 organic valid records where alt clearly wins."""
    cids = [
        "pytest_failure", "semantic_incomplete_stub", "missing_tests",
        "decomposition_required", "reasoning_loop",
        "workspace_dirty", "missing_ui_visibility", "budget_exceeded",
        "api_escalation_failed", "config_integrity",
    ]
    return [
        make_ab_record(
            case_id=cids[i],
            primary_model="gpt-5.3-codex",
            alt_model="deepseek-v4-pro",
            primary_score=0.60,
            alt_score=0.80,
            primary_breakdown={k: 0.8 for k in SCORE_WEIGHTS},
            alt_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            primary_cost_usd=0.01,
            alt_cost_usd=0.003,
            source="organic_run",
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# 1. Schema scoring (key: schema_score)
# ---------------------------------------------------------------------------

class TestSchemaValidScoring:
    def test_fully_valid_response_scores_high(self):
        r = score_helper_response(_full_response(), {})
        assert r["total"] >= 0.55

    def test_schema_score_key_present(self):
        r = score_helper_response(_full_response(), {})
        assert "schema_score" in r["breakdown"]
        assert r["breakdown"]["schema_score"] >= 0.9

    def test_response_with_all_fields_has_no_schema_issues(self):
        r = score_helper_response(_full_response(), {})
        schema_issues = [i for i in r["issues"] if "missing" in i]
        assert not schema_issues

    def test_score_breakdown_has_all_dimensional_keys(self):
        r = score_helper_response(_full_response(), {})
        assert "breakdown" in r
        assert "total" in r
        for key in SCORE_WEIGHTS:
            assert key in r["breakdown"], f"missing breakdown key: {key}"
        assert "anti_generic_penalty" in r["breakdown"]


class TestNonJsonResponse:
    def test_non_dict_response_scores_zero(self):
        r = score_helper_response("some markdown string", {})
        assert r["total"] == 0.0

    def test_empty_dict_scores_low(self):
        r = score_helper_response({}, {})
        assert r["total"] < 0.30

    def test_partial_schema_penalised(self):
        r = score_helper_response({"diagnosis": "something"}, {})
        assert r["breakdown"]["schema_score"] < 1.0


# ---------------------------------------------------------------------------
# 2. Secret detection
# ---------------------------------------------------------------------------

class TestSecretDetection:
    def test_response_with_api_key_scores_no_secrets_zero(self):
        resp = _full_response(diagnosis="use sk-proj-abc123 key to fix this sk-secretXYZabc123def456ghi789")
        r = score_helper_response(resp, {})
        assert r["breakdown"]["no_secrets"] == 0.0

    def test_clean_response_scores_no_secrets_one(self):
        r = score_helper_response(_full_response(), {})
        assert r["breakdown"]["no_secrets"] == 1.0

    def test_secret_in_execution_plan_detected(self):
        resp = _full_response(execution_plan=["set env sk-proj-realkey12345678901234567", "run tests"])
        r = score_helper_response(resp, {})
        assert r["breakdown"]["no_secrets"] == 0.0


# ---------------------------------------------------------------------------
# 3. Execution plan scoring (key: execution_plan_actionability_score)
# ---------------------------------------------------------------------------

class TestExecutionPlanScoring:
    def test_specific_plan_scores_higher_than_generic(self):
        specific = _full_response(execution_plan=[
            "apri tests/conftest.py riga 5",
            "aggiungi @pytest.fixture def app(): ...",
            "sostituisci client = TestClient(app)",
        ])
        generic = _full_response(execution_plan=[
            "check the tests",
            "review the code",
            "try running again",
        ])
        r_specific = score_helper_response(specific, {})
        r_generic = score_helper_response(generic, {})
        assert r_specific["breakdown"]["execution_plan_actionability_score"] > \
               r_generic["breakdown"]["execution_plan_actionability_score"]

    def test_empty_execution_plan_scores_zero(self):
        r = score_helper_response(_full_response(execution_plan=[]), {})
        assert r["breakdown"]["execution_plan_actionability_score"] == 0.0

    def test_single_step_scores_low(self):
        r = score_helper_response(_full_response(execution_plan=["fix the test"]), {})
        assert r["breakdown"]["execution_plan_actionability_score"] <= 0.3


# ---------------------------------------------------------------------------
# 4. Anti-generic penalty
# ---------------------------------------------------------------------------

class TestAntiGenericPenalty:
    def test_generic_advice_penalized(self):
        generic = _full_response(execution_plan=[
            "add more tests",
            "check the logs",
            "review the implementation",
        ])
        r = score_helper_response(generic, {})
        assert r["breakdown"]["anti_generic_penalty"] < 0.0

    def test_specific_execution_plan_no_penalty(self):
        specific = _full_response(execution_plan=[
            "apri tests/conftest.py riga 5",
            "aggiungi fixture app in tests/conftest.py",
            "esegui pytest tests/test_items.py::test_create_item",
        ])
        r = score_helper_response(specific, {})
        assert r["breakdown"]["anti_generic_penalty"] >= -0.05

    def test_generic_advice_reduces_total_score(self):
        generic_plan = _full_response(execution_plan=[
            "add more tests",
            "check the logs",
            "review the implementation",
            "ensure the schema matches",
        ])
        specific_plan = _full_response(execution_plan=[
            "edit tests/conftest.py line 12",
            "run pytest tests/test_users.py::test_get_user",
            "assert status_code == 200 in tests/test_users.py",
        ])
        r_generic = score_helper_response(generic_plan, {})
        r_specific = score_helper_response(specific_plan, {})
        assert r_specific["total"] > r_generic["total"]

    def test_penalty_capped_at_minus_020(self):
        very_generic = _full_response(execution_plan=[
            "add more tests",
            "check the logs",
            "review the implementation",
            "ensure the schema matches",
            "fix the failing test",
            "check the code",
            "review and fix",
            "make sure it works",
        ])
        r = score_helper_response(very_generic, {})
        assert r["breakdown"]["anti_generic_penalty"] >= -0.20


# ---------------------------------------------------------------------------
# 5. Safety score (key: safety_score)
# ---------------------------------------------------------------------------

class TestSafetyScore:
    def test_safety_score_key_present(self):
        r = score_helper_response(_full_response(), {})
        assert "safety_score" in r["breakdown"]

    def test_must_not_complete_product_manually_false_reduces_safety(self):
        resp = _full_response(must_not_complete_product_manually=False)
        r = score_helper_response(resp, {})
        assert r["breakdown"]["safety_score"] < 1.0


# ---------------------------------------------------------------------------
# 6. Shadow mode contract
# ---------------------------------------------------------------------------

class TestShadowModeContract:
    def test_shadow_result_does_not_affect_primary_output(self):
        primary = _full_response(diagnosis="primary diagnosis in tests/conftest.py")
        shadow = _full_response(diagnosis="shadow diagnosis — different advice")
        r_primary = score_helper_response(primary, {})
        r_shadow = score_helper_response(shadow, {})
        assert r_primary["total"] > 0
        assert r_shadow["total"] > 0
        assert primary["diagnosis"] != shadow["diagnosis"]


# ---------------------------------------------------------------------------
# 7. Model identity fields in records
# ---------------------------------------------------------------------------

class TestModelIdentityFields:
    def test_model_identity_fields_persisted(self):
        rec = make_ab_record(
            case_id="pytest_failure",
            primary_model="gpt-5.3-codex",
            alt_model="deepseek-v4-pro",
            primary_score=0.75,
            alt_score=0.70,
            primary_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            alt_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            primary_cost_usd=0.01,
            alt_cost_usd=0.003,
            primary_requested_model="gpt-5.3-codex",
            primary_resolved_model="gpt-5.4-mini",
            primary_provider_response_model="gpt-5.4-mini",
            primary_served_model="gpt-5.4-mini",
            primary_provider="openai",
            alt_requested_model="deepseek-v4-pro",
            alt_resolved_model="deepseek-v4-pro",
            alt_provider="deepseek",
            api_helper_mode="codex_only",
        )
        assert rec["primary_requested_model"] == "gpt-5.3-codex"
        assert rec["primary_resolved_model"] == "gpt-5.4-mini"
        assert rec["primary_served_model"] == "gpt-5.4-mini"
        assert rec["primary_provider"] == "openai"
        assert rec["alt_requested_model"] == "deepseek-v4-pro"
        assert rec["alt_provider"] == "deepseek"
        assert rec["api_helper_mode"] == "codex_only"

    def test_model_mismatch_detected_when_requested_ne_resolved(self):
        rec = make_ab_record(
            case_id="pytest_failure",
            primary_model="gpt-5.3-codex",
            alt_model="deepseek-v4-pro",
            primary_score=0.75,
            alt_score=0.70,
            primary_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            alt_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            primary_cost_usd=0.01,
            alt_cost_usd=0.003,
            primary_requested_model="gpt-5.3-codex",
            primary_resolved_model="gpt-5.4-mini",  # different -> mismatch
        )
        assert rec["ab_validity"] == "model_mismatch"

    def test_valid_when_requested_matches_resolved(self):
        rec = make_ab_record(
            case_id="pytest_failure",
            primary_model="gpt-5.3-codex",
            alt_model="deepseek-v4-pro",
            primary_score=0.75,
            alt_score=0.70,
            primary_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            alt_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            primary_cost_usd=0.01,
            alt_cost_usd=0.003,
            primary_requested_model="deepseek-v4-pro",
            primary_resolved_model="deepseek-v4-pro",
        )
        assert rec["ab_validity"] == "valid"

    def test_valid_when_no_identity_fields_provided(self):
        rec = make_ab_record(
            case_id="pytest_failure",
            primary_model="gpt-5.3-codex",
            alt_model="deepseek-v4-pro",
            primary_score=0.75,
            alt_score=0.70,
            primary_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            alt_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            primary_cost_usd=0.01,
            alt_cost_usd=0.003,
        )
        assert rec["ab_validity"] == "valid"


# ---------------------------------------------------------------------------
# 8. Downstream usefulness fields
# ---------------------------------------------------------------------------

class TestDownstreamUsefulnessFields:
    def test_downstream_defaults_to_unknown(self):
        rec = make_ab_record(
            case_id="pytest_failure",
            primary_model="gpt-5.3-codex",
            alt_model="deepseek-v4-pro",
            primary_score=0.75,
            alt_score=0.70,
            primary_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            alt_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            primary_cost_usd=0.01,
            alt_cost_usd=0.003,
        )
        assert rec["downstream"]["next_run_outcome"] == "unknown"
        assert rec["downstream"]["same_failure_repeated"] is None
        assert rec["downstream"]["repair_cycles_saved"] is None

    def test_downstream_unknown_does_not_break_is_safe_to_switch(self):
        records = _organic(10)
        result = is_safe_to_switch(records)
        assert isinstance(result["safe_to_switch"], bool)

    def test_downstream_custom_values_persisted(self):
        rec = make_ab_record(
            case_id="pytest_failure",
            primary_model="gpt-5.3-codex",
            alt_model="deepseek-v4-pro",
            primary_score=0.75,
            alt_score=0.70,
            primary_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            alt_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            primary_cost_usd=0.01,
            alt_cost_usd=0.003,
            downstream={
                "next_run_outcome": "success",
                "same_failure_repeated": False,
                "repair_cycles_saved": 1,
                "diff_produced_after_advice": True,
            },
        )
        assert rec["downstream"]["next_run_outcome"] == "success"
        assert rec["downstream"]["same_failure_repeated"] is False
        assert rec["downstream"]["repair_cycles_saved"] == 1


# ---------------------------------------------------------------------------
# 9. AB persistence
# ---------------------------------------------------------------------------

class TestABPersistence:
    def test_save_and_load_roundtrip(self, tmp_path):
        p = str(tmp_path / "ab.json")
        rec = _make_records(1)[0]
        save_ab_result(rec, p)
        loaded = load_ab_results(p)
        assert len(loaded) == 1
        assert loaded[0]["primary_model"] == "gpt-5.3-codex"

    def test_multiple_records_accumulate(self, tmp_path):
        p = str(tmp_path / "ab.json")
        for rec in _make_records(3):
            save_ab_result(rec, p)
        assert len(load_ab_results(p)) == 3

    def test_secrets_redacted_in_persistence(self, tmp_path):
        p = str(tmp_path / "ab.json")
        rec = _make_records(1)[0]
        rec["primary_breakdown"]["debug"] = "sk-proj-secretkeyABCDEF1234567890"
        save_ab_result(rec, p)
        raw = Path(p).read_text()
        assert "sk-proj-secretkeyABCDEF1234567890" not in raw
        assert "[REDACTED]" in raw

    def test_model_identity_fields_in_persisted_record(self, tmp_path):
        p = str(tmp_path / "ab_identity.json")
        rec = make_ab_record(
            case_id="pytest_failure",
            primary_model="gpt-5.3-codex",
            alt_model="deepseek-v4-pro",
            primary_score=0.75,
            alt_score=0.70,
            primary_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            alt_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            primary_cost_usd=0.01,
            alt_cost_usd=0.003,
            primary_requested_model="gpt-5.3-codex",
            primary_served_model="gpt-5.3-codex",
            primary_provider="openai",
            api_helper_mode="codex_only",
        )
        save_ab_result(rec, p)
        loaded = load_ab_results(p)
        assert loaded[0]["primary_requested_model"] == "gpt-5.3-codex"
        assert loaded[0]["primary_provider"] == "openai"
        assert loaded[0]["api_helper_mode"] == "codex_only"
        assert loaded[0]["ab_validity"] == "valid"

    def test_no_secrets_persisted(self, tmp_path):
        p = str(tmp_path / "ab_nosecrets.json")
        rec = make_ab_record(
            case_id="pytest_failure",
            primary_model="gpt-5.3-codex",
            alt_model="deepseek-v4-pro",
            primary_score=0.75,
            alt_score=0.70,
            primary_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            alt_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            primary_cost_usd=0.01,
            alt_cost_usd=0.003,
        )
        rec["debug_leak"] = "sk-proj-secretkeyABCDEF1234567890"
        save_ab_result(rec, p)
        raw = Path(p).read_text()
        assert "sk-proj-secretkeyABCDEF1234567890" not in raw


# ---------------------------------------------------------------------------
# 10. Switch policy — model mismatch gate
# ---------------------------------------------------------------------------

class TestSwitchPolicyModelMismatch:
    def test_model_mismatch_blocks_switch(self):
        mismatch_records = [
            make_ab_record(
                case_id=f"case_{i}",
                primary_model="gpt-5.3-codex",
                alt_model="deepseek-v4-pro",
                primary_score=0.70,
                alt_score=0.80,
                primary_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
                alt_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
                primary_cost_usd=0.01,
                alt_cost_usd=0.003,
                source="organic_run",
                primary_requested_model="gpt-5.3-codex",
                primary_resolved_model="gpt-5.4-mini",  # mismatch
            )
            for i in range(10)
        ]
        result = is_safe_to_switch(mismatch_records)
        assert result["safe_to_switch"] is False
        assert any("model_mismatch" in r for r in result["reasons"])

    def test_model_mismatch_count_reported(self):
        mismatch = _organic(5)
        for r in mismatch:
            r["ab_validity"] = "model_mismatch"
        valid = _organic(10)
        result = is_safe_to_switch(mismatch + valid)
        assert result.get("model_mismatch_count", 0) == 5


# ---------------------------------------------------------------------------
# 11. Switch policy — updated gates
# ---------------------------------------------------------------------------

class TestSwitchPolicyNewGates:
    def test_no_records_never_safe(self):
        r = is_safe_to_switch([])
        assert r["safe_to_switch"] is False

    def test_need_10_organic_valid_records(self):
        r = is_safe_to_switch(_organic(9))
        assert r["safe_to_switch"] is False
        assert any("10 organic" in reason for reason in r["reasons"])

    def test_safe_to_switch_false_when_alt_wins_zero(self):
        records = _organic_alt_wins(10)
        for r in records:
            r["primary_score"] = 0.80
            r["alt_score"] = 0.60
            r["winner"] = "primary"
        result = is_safe_to_switch(records)
        assert result["safe_to_switch"] is False

    def test_safe_to_switch_false_when_candidate_avg_below_primary(self):
        records = _organic(10, primary_score=0.80, alt_score=0.60)
        result = is_safe_to_switch(records)
        assert result["safe_to_switch"] is False
        assert any("avg alt" in r for r in result["reasons"])

    def test_safe_to_switch_false_when_semantic_incomplete_regression(self):
        records = _organic(10)
        records[0]["case_id"] = "semantic_incomplete_stub"
        records[0]["winner"] = "primary"
        records[0]["primary_score"] = 0.80
        records[0]["alt_score"] = 0.50
        result = is_safe_to_switch(records)
        assert result["safe_to_switch"] is False
        assert any("semantic_incomplete" in r for r in result["reasons"])

    def test_safe_to_switch_false_when_decomposition_required_regression(self):
        records = _organic(10)
        records[0]["case_id"] = "decomposition_required_large"
        records[0]["winner"] = "primary"
        records[0]["primary_score"] = 0.80
        records[0]["alt_score"] = 0.50
        result = is_safe_to_switch(records)
        assert result["safe_to_switch"] is False
        assert any("decomposition_required" in r for r in result["reasons"])

    def test_only_organic_not_safe_if_less_than_10(self):
        r = is_safe_to_switch(_organic(5))
        assert r["safe_to_switch"] is False

    def test_insufficient_failure_class_diversity_blocks(self):
        organic = _make_records(10, source="organic_run", case_ids=["case_a", "case_b"])
        r = is_safe_to_switch(organic)
        assert r["safe_to_switch"] is False
        assert any("failure_class" in reason for reason in r["reasons"])

    def test_safety_failure_blocks_switch(self):
        bad_bd = {k: 1.0 for k in SCORE_WEIGHTS}
        bad_bd["safety_score"] = 0.0
        records = _organic(10, alt_breakdown=bad_bd)
        r = is_safe_to_switch(records)
        assert r["safe_to_switch"] is False

    def test_low_alt_score_blocks_switch(self):
        records = _organic(10, primary_score=0.80, alt_score=0.60)
        r = is_safe_to_switch(records)
        assert r["safe_to_switch"] is False

    def test_critical_regression_blocks_switch(self):
        records = _organic(10)
        records.append(make_ab_record(
            case_id="decomposition_required_large_goal",
            primary_model="gpt-5.3-codex", alt_model="deepseek-v4-pro",
            primary_score=0.80, alt_score=0.10,
            primary_breakdown={k: 1.0 for k in SCORE_WEIGHTS},
            alt_breakdown={k: 0.1 for k in SCORE_WEIGHTS},
            primary_cost_usd=0.01, alt_cost_usd=0.003,
            source="organic_run",
        ))
        r = is_safe_to_switch(records)
        assert r["safe_to_switch"] is False
        assert any("critical" in reason for reason in r["reasons"])

    def test_switch_never_auto_enabled_in_records(self):
        for rec in _organic(10):
            assert rec["safe_to_switch"] is False

    def test_failure_classes_covered_reported(self):
        cids = [
            "pytest_failure", "semantic_incomplete", "missing_tests",
            "decomposition_required", "reasoning_loop",
            "workspace_dirty", "missing_ui_visibility", "budget_exceeded",
            "api_escalation_failed", "config_integrity",
        ]
        organic = _make_records(10, source="organic_run", case_ids=cids)
        r = is_safe_to_switch(organic)
        assert len(r["failure_classes_covered"]) >= 3

    def test_organic_count_reported(self):
        r = is_safe_to_switch(_organic(10))
        assert r["organic_count"] == 10

    def test_model_mismatch_count_in_result(self):
        result = is_safe_to_switch(_organic(10))
        assert "model_mismatch_count" in result

    def test_report_includes_model_mismatch_records(self):
        mismatch = _make_records(3, source="organic_run")
        for r in mismatch:
            r["ab_validity"] = "model_mismatch"
        valid = _organic(10)
        result = is_safe_to_switch(mismatch + valid)
        assert result["model_mismatch_count"] == 3


# ---------------------------------------------------------------------------
# 12. AB disabled
# ---------------------------------------------------------------------------

class TestABDisabled:
    def test_ab_disabled_returns_false(self):
        records = _make_records(0)
        result = is_safe_to_switch(records)
        assert result["safe_to_switch"] is False
        assert result["organic_count"] == 0
