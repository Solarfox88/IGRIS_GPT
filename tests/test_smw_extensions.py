from __future__ import annotations

import asyncio
import tempfile
import time
from unittest.mock import patch

from igris.core.smw_pr_review import PRReviewRequest, PRReviewResult, _is_high_risk, load_review_results, review_pr, save_review_result
from igris.core.smw_weak_signals import (
    detect_cost_drift,
    detect_fix_not_sticky,
    detect_model_overkill,
    detect_repair_cycle_saturation,
    detect_systemic_capability_gap,
    get_weak_signal_summary,
    run_all_detectors,
)


def _req(**kw):
    base = dict(pr_number=1, pr_title="t", pr_diff="d", issue_description="i", changed_files=["a"], ci_passed=True, run_id="r", last_failure_class="", repair_cycles_used=0, max_repair_cycles=3, capability_signals={})
    base.update(kw)
    return PRReviewRequest(**base)


def test_is_high_risk_wrong_file_edit():
    assert _is_high_risk(_req(last_failure_class="wrong_file_edit"))


def test_is_high_risk_normal():
    assert not _is_high_risk(_req())


@patch("igris.core.smw_pr_review._call_deepseek_review")
def test_review_pr_approved(mock_call):
    mock_call.return_value = {"approved": True, "confidence": 0.9, "concerns": [], "suggestion": "ok"}
    r = asyncio.run(review_pr(_req(), "."))
    assert r.approved and r.confidence == 0.9


@patch("igris.core.smw_pr_review._call_deepseek_review")
def test_review_pr_second_opinion(mock_call):
    mock_call.side_effect = [
        {"approved": True, "confidence": 0.5, "concerns": [], "suggestion": "a"},
        {"approved": True, "confidence": 0.8, "concerns": [], "suggestion": "b"},
    ]
    r = asyncio.run(review_pr(_req(), "."))
    assert mock_call.call_count == 2
    assert r.confidence == 0.8


@patch("igris.core.smw_pr_review._call_codex_tiebreaker")
@patch("igris.core.smw_pr_review._call_deepseek_review")
def test_review_pr_tiebreaker(mock_call, mock_tie):
    mock_call.side_effect = [
        {"approved": True, "confidence": 0.5, "concerns": [], "suggestion": "a"},
        {"approved": False, "confidence": 0.7, "concerns": [], "suggestion": "b"},
    ]
    mock_tie.return_value = {"approved": True, "confidence": 0.75, "concerns": [], "suggestion": "t"}
    r = asyncio.run(review_pr(_req(), "."))
    assert r.tiebreaker_used


@patch("igris.core.smw_pr_review._call_deepseek_review", side_effect=RuntimeError("down"))
def test_review_pr_fail_open(_):
    r = asyncio.run(review_pr(_req(), "."))
    assert r.approved and r.confidence == 0.3


def test_save_and_load_review_result():
    with tempfile.TemporaryDirectory() as td:
        rr = PRReviewResult(7, True, 0.9, "m", [], "", time.time(), False)
        save_review_result(rr, td)
        got = load_review_results(td)
        assert got[0].pr_number == 7


def test_detect_model_overkill_triggered():
    runs = [{"api_escalations_used": 1} for _ in range(14)] + [{"api_escalations_used": 0} for _ in range(6)]
    assert detect_model_overkill(runs) is not None


def test_detect_model_overkill_not_triggered():
    runs = [{"api_escalations_used": 1} for _ in range(8)] + [{"api_escalations_used": 0} for _ in range(12)]
    assert detect_model_overkill(runs) is None


def test_detect_repair_cycle_saturation():
    runs = [{"repair_cycles_used": 3, "max_repair_cycles": 3} for _ in range(8)] + [{"repair_cycles_used": 1, "max_repair_cycles": 3} for _ in range(2)]
    assert detect_repair_cycle_saturation(runs) is not None


def test_detect_systemic_gap():
    runs = [{"last_failure_class": "wrong_file_edit", "issue_number": i} for i in [1, 2, 3, 4]]
    assert detect_systemic_capability_gap(runs) is not None


def test_detect_cost_drift():
    now = time.time()
    runs = [
        {"started_at": now - 1000, "api_budget_used_usd": 2.0},
        {"started_at": now - 8 * 24 * 3600, "api_budget_used_usd": 1.0},
    ]
    assert detect_cost_drift(runs) is not None


def test_detect_fix_not_sticky():
    now = time.time()
    runs = [
        {"issue_number": 42, "status": "done", "finished_at": now - 3600},
        {"issue_number": 42, "status": "open", "started_at": now},
    ]
    assert detect_fix_not_sticky(runs, ".") is not None


def test_run_all_detectors_no_signals():
    with tempfile.TemporaryDirectory() as td:
        assert run_all_detectors(td) == []


def test_get_weak_signal_summary_keys():
    with tempfile.TemporaryDirectory() as td:
        out = get_weak_signal_summary(td)
        assert "weak_signals_active" in out and "metrics" in out
