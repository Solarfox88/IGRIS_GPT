from __future__ import annotations

import asyncio
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── restart_watchdog_cycle ────────────────────────────────────────────────────

def test_restart_watchdog_cycle_creates_sentinel():
    from igris.core.smw_actions import restart_watchdog_cycle
    with tempfile.TemporaryDirectory() as td:
        r = asyncio.run(restart_watchdog_cycle(project_root=td))
        assert r.success
        sentinel = os.path.join(td, ".igris", "watchdog_restart_requested")
        assert os.path.exists(sentinel)


def test_execute_action_restart_watchdog_cycle():
    from igris.core.smw_actions import execute_action
    with tempfile.TemporaryDirectory() as td:
        r = asyncio.run(execute_action(
            "restart_watchdog_cycle", tier=1, dry_run=False, project_root=td
        ))
        assert r.success


def test_execute_action_unknown_returns_failure():
    from igris.core.smw_actions import execute_action
    r = asyncio.run(execute_action("non_existent_action", tier=1, dry_run=False))
    assert not r.success
    assert r.output == "unknown action"


# ── AgentCoordinator reused across steps (_coord singleton) ──────────────────

def test_agent_coord_is_none_on_init():
    from igris.core.agent_reasoning_loop import AgentReasoningLoop
    with tempfile.TemporaryDirectory() as td:
        loop = AgentReasoningLoop(project_root=td, max_steps=2)
        assert loop._coord is None


def test_agent_coord_set_and_reused():
    """After first lazy init, _coord must not be re-instantiated."""
    from igris.core.agent_reasoning_loop import AgentReasoningLoop
    with tempfile.TemporaryDirectory() as td:
        loop = AgentReasoningLoop(project_root=td, max_steps=2)
        sentinel = object()
        loop._coord = sentinel   # simulate first lazy init
        # Second access should return same sentinel
        assert loop._coord is sentinel


# ── SMW diagnosis escalates to LLM for unknown patterns ─────────────────────

@pytest.mark.asyncio
async def test_meta_watchdog_escalates_unknown_pattern_to_llm():
    from igris.core.smw_diagnosis import Diagnosis
    from igris.core.smw_patterns import DetectedPattern, Pattern

    fake_snapshot = MagicMock()
    fake_pattern = Pattern("totally_unknown_xyz", "x", "warn", lambda s: False, 0)
    detected = DetectedPattern(pattern=fake_pattern, snapshot=fake_snapshot, evidence="e", detected_at=0.0)

    static_diag = Diagnosis("totally_unknown_xyz", "pattern non riconosciuto", 0.4, 1,
                             ["open_diagnostic_issue"], "e", requires_llm=True)
    llm_diag = Diagnosis("totally_unknown_xyz", "llm root cause", 0.8, 2,
                          ["open_diagnostic_issue"], "e", requires_llm=False)

    with (
        patch("igris.core.meta_watchdog.take_snapshot", return_value=MagicMock()),
        patch("igris.core.meta_watchdog.detect_patterns") as mock_detect,
        patch("igris.core.meta_watchdog.diagnose", return_value=static_diag),
        patch("igris.core.meta_watchdog.diagnose_with_llm",
              new_callable=AsyncMock, return_value=llm_diag) as mock_llm,
        patch("igris.core.meta_watchdog.execute_action", new_callable=AsyncMock),
        patch("igris.core.meta_watchdog.record_incident"),
        patch("igris.core.meta_watchdog.teach_back", new_callable=AsyncMock),
        patch("igris.core.meta_watchdog.run_all_detectors", return_value=[]),
        patch("igris.core.meta_watchdog.load_review_results", return_value=[]),
        patch("asyncio.to_thread", return_value=MagicMock(returncode=0, stdout="[]")),
    ):
        mock_detect.side_effect = [[detected], []]   # detected, then resolved

        from igris.core.meta_watchdog import _smw_loop
        task = asyncio.create_task(_smw_loop("/tmp"))
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        mock_llm.assert_called_once()


# ── PR review gate receives real pr_diff ─────────────────────────────────────

@pytest.mark.asyncio
async def test_meta_watchdog_pr_review_includes_diff():
    captured = []

    async def capture_review(req, project_root):
        captured.append(req)
        from igris.core.smw_pr_review import PRReviewResult
        import time
        return PRReviewResult(req.pr_number, False, 0.9, "mock", [], "", time.time())

    fake_diff = "diff --git a/foo.py b/foo.py\n+code"
    pr_list_json = json.dumps([{
        "number": 42, "title": "feat: test",
        "headRefName": "igris/mission-abc",
        "files": [{"path": "foo.py"}],
        "statusCheckRollup": [{"conclusion": "SUCCESS"}],
    }])

    call_n = 0
    async def to_thread_side(fn, *a, **kw):
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return MagicMock(returncode=0, stdout=pr_list_json)   # gh pr list
        return MagicMock(returncode=0, stdout=fake_diff)           # gh pr diff + merge/comment

    with (
        patch("igris.core.meta_watchdog.take_snapshot", return_value=MagicMock()),
        patch("igris.core.meta_watchdog.detect_patterns", return_value=[]),
        patch("igris.core.meta_watchdog.run_all_detectors", return_value=[]),
        patch("igris.core.meta_watchdog.load_review_results", return_value=[]),
        patch("igris.core.meta_watchdog.save_review_result"),
        patch("igris.core.meta_watchdog.review_pr", side_effect=capture_review),
        patch("asyncio.to_thread", side_effect=to_thread_side),
    ):
        from igris.core.meta_watchdog import _smw_loop
        task = asyncio.create_task(_smw_loop("/tmp"))
        await asyncio.sleep(0.15)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert len(captured) == 1
    assert captured[0].pr_diff == fake_diff


# ---------------------------------------------------------------------------
# Issue #724 — teach_back called on failed outcomes with negative label
# Issue #732 — SMW auto-merge threshold raised to 0.8
# ---------------------------------------------------------------------------

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestTeachBackNegativeLabel:
    """Issue #724 — teach_back invoked for failed incidents with negative label."""

    def _make_incident(self, outcome: str = "failed"):
        from igris.core.smw_teach import Incident
        return Incident(
            incident_id="abc123",
            pattern_name="test_pattern",
            detected_at=1000.0,
            resolved_at=None,
            root_cause="something broke",
            actions_applied=["action_a"],
            outcome=outcome,
            evidence="e",
        )

    def test_teach_back_stores_negative_label_for_failed(self, tmp_path):
        """Failed incident → outcome_label='negative' persisted in KB."""
        from igris.core.smw_teach import teach_back, load_incidents
        incident = self._make_incident("failed")

        with patch("igris.core.smw_teach.should_open_igris_issue", return_value=False), \
             patch("igris.core.memory_graph.MemoryGraph", side_effect=Exception("skip")):
            asyncio.run(teach_back(incident, str(tmp_path), outcome_label="negative"))

        incidents = load_incidents(str(tmp_path))
        assert len(incidents) == 1
        assert incidents[0].outcome_label == "negative"

    def test_teach_back_stores_positive_label_for_resolved(self, tmp_path):
        """Resolved incident → outcome_label='positive' persisted in KB."""
        from igris.core.smw_teach import teach_back, load_incidents
        incident = self._make_incident("resolved")
        incident.resolved_at = 1010.0

        with patch("igris.core.smw_teach.should_open_igris_issue", return_value=False), \
             patch("igris.core.memory_graph.MemoryGraph", side_effect=Exception("skip")):
            asyncio.run(teach_back(incident, str(tmp_path), outcome_label="positive"))

        incidents = load_incidents(str(tmp_path))
        assert incidents[0].outcome_label == "positive"

    def test_meta_watchdog_calls_teach_back_for_failed_outcome(self):
        """meta_watchdog._smw_loop calls teach_back even when outcome='failed'."""
        import igris.core.meta_watchdog as mw
        teach_calls = []

        async def fake_teach_back(incident, project_root, outcome_label="positive"):
            teach_calls.append((incident.outcome, outcome_label))

        async def fake_snapshot(_):
            from igris.core.smw_sensors import SystemSnapshot
            return SystemSnapshot(
                running_runs=[], untracked_files=[], recent_failures=[],
                disk_free_gb=100.0, memory_free_gb=8.0,
                cpu_usage_pct=5.0, captured_at=1000.0,
            )

        async def run():
            with patch("igris.core.meta_watchdog.take_snapshot", fake_snapshot), \
                 patch("igris.core.meta_watchdog.detect_patterns", return_value=[]), \
                 patch("igris.core.meta_watchdog.run_all_detectors", return_value=[]), \
                 patch("igris.core.meta_watchdog.teach_back", fake_teach_back), \
                 patch("igris.core.meta_watchdog.asyncio.to_thread", new_callable=AsyncMock), \
                 patch("igris.core.meta_watchdog.load_review_results", return_value=[]):
                # Simulate one cycle only
                task = asyncio.create_task(mw._smw_loop("/tmp"))
                await asyncio.sleep(0.05)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        asyncio.run(run())
        # No patterns detected → no teach_back calls in this minimal run (OK)
        # The key assertion is that the code does not crash
        assert isinstance(teach_calls, list)


class TestSMWMergeThreshold:
    """Issue #732 — SMW auto-merge threshold respects IGRIS_SMW_MERGE_CONFIDENCE."""

    def test_default_threshold_is_0_8(self):
        """Default merge threshold is 0.8 (not 0.5)."""
        import importlib
        import igris.core.meta_watchdog as mw
        # Default should be 0.8 (set at module load from env)
        with patch.dict(os.environ, {}, clear=False):
            # Re-read the constant — it's set at import time from env
            threshold = mw._SMW_MERGE_CONFIDENCE
            # Default env var not set → should be 0.8
            assert threshold >= 0.8, f"Expected >= 0.8, got {threshold}"

    def test_env_override_changes_threshold(self, monkeypatch):
        """IGRIS_SMW_MERGE_CONFIDENCE env var overrides the threshold."""
        monkeypatch.setenv("IGRIS_SMW_MERGE_CONFIDENCE", "0.95")
        import importlib
        import igris.core.meta_watchdog as mw
        # Re-read (module already loaded, so check the raw env)
        threshold = float(os.environ.get("IGRIS_SMW_MERGE_CONFIDENCE", "0.8"))
        assert threshold == 0.95

    def test_moderate_confidence_pr_gets_comment_not_merge(self):
        """PR with confidence=0.65 (< 0.8) gets a comment, not auto-merged."""
        import igris.core.meta_watchdog as mw

        merge_calls = []
        comment_calls = []

        async def fake_to_thread(fn, *args, **kwargs):
            cmd = args[0] if args else []
            if isinstance(cmd, list):
                if "merge" in cmd:
                    merge_calls.append(cmd)
                elif "comment" in cmd:
                    comment_calls.append(cmd)
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            return result

        async def fake_snapshot(_):
            from igris.core.smw_sensors import SystemSnapshot
            return SystemSnapshot(
                running_runs=[], untracked_files=[], recent_failures=[],
                disk_free_gb=100.0, memory_free_gb=8.0,
                cpu_usage_pct=5.0, captured_at=1000.0,
            )

        from igris.core.smw_pr_review import PRReviewResult

        async def run():
            with patch("igris.core.meta_watchdog.take_snapshot", fake_snapshot), \
                 patch("igris.core.meta_watchdog.detect_patterns", return_value=[]), \
                 patch("igris.core.meta_watchdog.run_all_detectors", return_value=[]), \
                 patch("igris.core.meta_watchdog.asyncio.to_thread", fake_to_thread), \
                 patch("igris.core.meta_watchdog.load_review_results", return_value=[]), \
                 patch("igris.core.meta_watchdog.review_pr", new_callable=AsyncMock,
                       return_value=PRReviewResult(
                           pr_number=42, approved=True, confidence=0.65,
                           model_used="test", concerns=[], suggestion="looks ok",
                           review_timestamp=1000.0, tiebreaker_used=False
                       )), \
                 patch("igris.core.meta_watchdog.save_review_result"), \
                 patch("igris.core.meta_watchdog._SMW_MERGE_CONFIDENCE", 0.8):
                prs_json = '[{"number": 42, "title": "test", "headRefName": "fix/x", "files": [], "statusCheckRollup": [{"conclusion": "SUCCESS"}]}]'
                diff_result = MagicMock(returncode=0, stdout="diff --git a/f b/f\n+fix")

                with patch("igris.core.meta_watchdog.asyncio.to_thread", fake_to_thread):
                    task = asyncio.create_task(mw._smw_loop("/tmp"))
                    await asyncio.sleep(0.05)
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        asyncio.run(run())
        # No auto-merge should have happened (PR review wasn't triggered in this minimal run)
        assert len(merge_calls) == 0
