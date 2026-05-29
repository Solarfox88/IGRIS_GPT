"""Tests for igris/core/judgment_layer.py (issue #526)."""
from __future__ import annotations

import pytest

from igris.core.judgment_layer import Advisory, JudgmentLayer, OperationalContext


class TestJudgmentLayer:
    def _layer(self):
        return JudgmentLayer()

    def test_non_sensitive_action_proceeds(self):
        layer = self._layer()
        ctx = OperationalContext()
        adv = layer.advise("list_files", "project", ctx, trust_level="trusted")
        assert adv.should_proceed is True
        assert adv.reason == "non_sensitive"
        assert adv.requires_confirmation is False

    def test_no_concerns_proceeds(self):
        layer = self._layer()
        ctx = OperationalContext(hour_of_day=10)
        adv = layer.advise("restart_server", "server_1", ctx, trust_level="trusted")
        assert adv.should_proceed is True
        assert adv.reason == "no_concerns"

    def test_active_backup_issues_advisory(self):
        layer = self._layer()
        ctx = OperationalContext(
            active_backups=[{"name": "db_backup", "pct": 60, "eta_sec": 240}],
            hour_of_day=10,
        )
        adv = layer.advise("restart_server", "server_1", ctx, trust_level="trusted")
        assert adv.should_proceed is True
        assert adv.reason == "advisory_issued"
        assert "backup" in adv.message.lower()
        assert adv.requires_confirmation is True

    def test_admin_advisory_does_not_require_confirmation(self):
        layer = self._layer()
        ctx = OperationalContext(
            active_backups=[{"name": "db", "pct": 50, "eta_sec": 300}],
            hour_of_day=10,
        )
        adv = layer.advise("restart_server", "server_1", ctx, trust_level="admin")
        assert adv.should_proceed is True
        assert adv.requires_confirmation is False

    def test_ci_running_issues_advisory(self):
        layer = self._layer()
        ctx = OperationalContext(ci_running=True, hour_of_day=10)
        adv = layer.advise("deploy", "server_1", ctx, trust_level="trusted")
        assert adv.reason == "advisory_issued"
        assert "ci" in adv.message.lower()

    def test_open_prs_on_delete_branch_issues_advisory(self):
        layer = self._layer()
        ctx = OperationalContext(open_prs=["#123", "#124"], hour_of_day=10)
        adv = layer.advise("delete_branch", "feature_branch", ctx, trust_level="trusted")
        assert adv.reason == "advisory_issued"
        assert "#123" in adv.message

    def test_night_time_issues_advisory(self):
        layer = self._layer()
        ctx = OperationalContext(hour_of_day=2)
        adv = layer.advise("deploy", "server_1", ctx, trust_level="trusted")
        assert adv.reason == "advisory_issued"
        assert "02" in adv.message

    def test_advisory_blocking_is_always_false(self):
        layer = self._layer()
        ctx = OperationalContext(
            active_backups=[{"name": "db", "pct": 1, "eta_sec": 9999}],
            ci_running=True,
            open_prs=["#999"],
            hour_of_day=3,
            run_in_progress=True,
        )
        adv = layer.advise("delete_branch", "main", ctx, trust_level="limited")
        assert adv.blocking is False

    def test_run_in_progress_issues_advisory(self):
        layer = self._layer()
        ctx = OperationalContext(run_in_progress=True, hour_of_day=10)
        adv = layer.advise("restart_server", "server_1", ctx, trust_level="trusted")
        assert adv.reason == "advisory_issued"

    def test_persist_advisory_outcome_best_effort(self, tmp_path):
        from unittest.mock import MagicMock, patch
        layer = self._layer()
        ctx = OperationalContext()
        adv = layer.advise("restart_server", "server_1", ctx, trust_level="admin")
        mock_mg = MagicMock()
        with patch("igris.core.memory_graph.MemoryGraph", return_value=mock_mg):
            layer.persist_advisory_outcome(adv, "accepted", str(tmp_path))
        mock_mg.add_node.assert_called_once()

    def test_persist_advisory_outcome_swallows_errors(self, tmp_path):
        from unittest.mock import patch
        layer = self._layer()
        ctx = OperationalContext()
        adv = layer.advise("restart_server", "server_1", ctx, trust_level="admin")
        with patch("igris.core.memory_graph.MemoryGraph", side_effect=RuntimeError("db error")):
            layer.persist_advisory_outcome(adv, "accepted", str(tmp_path))
