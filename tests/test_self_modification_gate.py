"""Tests for igris/core/self_modification_gate.py (issue #523)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from igris.core.self_modification_gate import (
    SelfModificationGate,
    _diff_hash,
    _extract_changed_paths,
    _SELF_MOD_CONFIDENCE_THRESHOLD,
    append_audit_record,
    get_core_files,
    load_audit_records,
    rollback_last_commit,
    run_targeted_tests,
    run_smoke_check,
    touches_core_files,
)


_CORE_DIFF = """\
diff --git a/igris/core/self_repair_supervisor.py b/igris/core/self_repair_supervisor.py
index abc..def 100644
--- a/igris/core/self_repair_supervisor.py
+++ b/igris/core/self_repair_supervisor.py
@@ -1,3 +1,4 @@
+# patched
 x = 1
"""

_NON_CORE_DIFF = """\
diff --git a/igris/core/memory_graph.py b/igris/core/memory_graph.py
index abc..def 100644
--- a/igris/core/memory_graph.py
+++ b/igris/core/memory_graph.py
@@ -1 +1,2 @@
+# new line
 x = 1
"""


# ---------------------------------------------------------------------------
# Path extraction and touch detection
# ---------------------------------------------------------------------------

class TestExtractChangedPaths:
    def test_detects_diff_git_header(self):
        diff = "diff --git a/igris/core/foo.py b/igris/core/foo.py\n"
        paths = _extract_changed_paths(diff)
        assert "igris/core/foo.py" in paths

    def test_detects_unified_diff_header(self):
        diff = "--- a/igris/web/server.py\n+++ b/igris/web/server.py\n"
        paths = _extract_changed_paths(diff)
        assert "igris/web/server.py" in paths

    def test_deduplicates_paths(self):
        diff = (
            "diff --git a/igris/core/foo.py b/igris/core/foo.py\n"
            "--- a/igris/core/foo.py\n+++ b/igris/core/foo.py\n"
        )
        paths = _extract_changed_paths(diff)
        assert paths.count("igris/core/foo.py") == 1

    def test_empty_diff_returns_empty(self):
        assert _extract_changed_paths("") == []


class TestTouchesCoreFiles:
    def test_detects_core_file(self):
        touched = touches_core_files(_CORE_DIFF)
        assert "igris/core/self_repair_supervisor.py" in touched

    def test_non_core_diff_returns_empty(self):
        touched = touches_core_files(_NON_CORE_DIFF)
        assert touched == []

    def test_custom_core_files(self):
        custom = {"igris/core/memory_graph.py"}
        touched = touches_core_files(_NON_CORE_DIFF, custom)
        assert "igris/core/memory_graph.py" in touched

    def test_empty_diff_returns_empty(self):
        assert touches_core_files("") == []


class TestDiffHash:
    def test_same_diff_same_hash(self):
        assert _diff_hash("abc") == _diff_hash("abc")

    def test_different_diff_different_hash(self):
        assert _diff_hash("abc") != _diff_hash("def")

    def test_hash_is_16_chars(self):
        assert len(_diff_hash("some diff content")) == 16


# ---------------------------------------------------------------------------
# Gate logic
# ---------------------------------------------------------------------------

class TestSelfModificationGate:
    def _gate(self, tmp_path, threshold=0.85):
        return SelfModificationGate(
            str(tmp_path),
            confidence_threshold=threshold,
            smoke_timeout=1,
        )

    def test_non_core_diff_is_approved(self, tmp_path):
        gate = self._gate(tmp_path)
        result = gate.check(_NON_CORE_DIFF, run_id="r1", confidence=0.9)
        assert result.approved is True
        assert result.touched_core == []

    def test_core_diff_below_confidence_blocked(self, tmp_path):
        gate = self._gate(tmp_path, threshold=0.85)
        result = gate.check(_CORE_DIFF, run_id="r1", confidence=0.70, run_smoke=False)
        assert result.approved is False
        assert result.below_confidence_threshold is True

    def test_core_diff_above_confidence_tests_run(self, tmp_path):
        gate = self._gate(tmp_path, threshold=0.85)
        with patch("igris.core.self_modification_gate.run_targeted_tests", return_value=True):
            result = gate.check(_CORE_DIFF, run_id="r1", confidence=0.90, run_smoke=False)
        assert result.approved is True
        assert result.test_passed is True

    def test_failed_targeted_tests_blocks(self, tmp_path):
        gate = self._gate(tmp_path, threshold=0.85)
        with patch("igris.core.self_modification_gate.run_targeted_tests", return_value=False):
            result = gate.check(_CORE_DIFF, run_id="r1", confidence=0.90, run_smoke=False)
        assert result.approved is False
        assert result.test_passed is False

    def test_smoke_failure_blocks_and_sets_smoke_passed_false(self, tmp_path):
        gate = self._gate(tmp_path, threshold=0.85)
        with patch("igris.core.self_modification_gate.run_targeted_tests", return_value=True), \
             patch("igris.core.self_modification_gate.run_smoke_check", return_value=False):
            result = gate.check(_CORE_DIFF, run_id="r1", confidence=0.90, run_smoke=True)
        assert result.approved is False
        assert result.smoke_passed is False

    def test_is_self_modification_true_for_core_diff(self, tmp_path):
        gate = self._gate(tmp_path)
        assert gate.is_self_modification(_CORE_DIFF) is True

    def test_is_self_modification_false_for_non_core(self, tmp_path):
        gate = self._gate(tmp_path)
        assert gate.is_self_modification(_NON_CORE_DIFF) is False

    def test_rollback_called_on_smoke_failure(self, tmp_path):
        gate = self._gate(tmp_path, threshold=0.85)
        with patch("igris.core.self_modification_gate.run_targeted_tests", return_value=True), \
             patch("igris.core.self_modification_gate.run_smoke_check", return_value=False):
            result = gate.check(_CORE_DIFF, run_id="r1", confidence=0.90, run_smoke=True)
        with patch("igris.core.self_modification_gate.rollback_last_commit", return_value=True) as mock_rb:
            gate.rollback_if_needed(result)
            mock_rb.assert_called_once()

    def test_rollback_not_called_on_approved(self, tmp_path):
        gate = self._gate(tmp_path)
        with patch("igris.core.self_modification_gate.run_targeted_tests", return_value=True), \
             patch("igris.core.self_modification_gate.run_smoke_check", return_value=True):
            result = gate.check(_CORE_DIFF, run_id="r1", confidence=0.90, run_smoke=True)
        with patch("igris.core.self_modification_gate.rollback_last_commit") as mock_rb:
            gate.rollback_if_needed(result)
            mock_rb.assert_not_called()


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

class TestAuditTrail:
    def test_append_and_load(self, tmp_path):
        record = {"run_id": "r1", "touched_core": ["igris/core/foo.py"], "outcome": "approved"}
        append_audit_record(str(tmp_path), record)
        records = load_audit_records(str(tmp_path))
        assert len(records) == 1
        assert records[0]["outcome"] == "approved"

    def test_multiple_records_accumulate(self, tmp_path):
        append_audit_record(str(tmp_path), {"n": 1})
        append_audit_record(str(tmp_path), {"n": 2})
        records = load_audit_records(str(tmp_path))
        assert len(records) == 2

    def test_load_missing_returns_empty(self, tmp_path):
        assert load_audit_records(str(tmp_path)) == []

    def test_load_corrupt_returns_empty(self, tmp_path):
        (tmp_path / ".igris").mkdir()
        (tmp_path / ".igris" / "self_modifications.json").write_text("NOT JSON")
        assert load_audit_records(str(tmp_path)) == []

    def test_gate_writes_audit_on_confidence_block(self, tmp_path):
        gate = SelfModificationGate(str(tmp_path), confidence_threshold=0.85, smoke_timeout=1)
        gate.check(_CORE_DIFF, run_id="audit_test", confidence=0.5, run_smoke=False)
        records = load_audit_records(str(tmp_path))
        assert any(r.get("outcome") == "below_confidence_threshold" for r in records)


# ---------------------------------------------------------------------------
# get_core_files
# ---------------------------------------------------------------------------

class TestGetCoreFiles:
    def test_returns_default_files(self):
        files = get_core_files()
        assert "igris/core/self_repair_supervisor.py" in files
        assert "igris/core/meta_watchdog.py" in files

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("IGRIS_CORE_FILES", "igris/core/foo.py,igris/core/bar.py")
        files = get_core_files()
        assert files == {"igris/core/foo.py", "igris/core/bar.py"}

    def test_empty_env_uses_defaults(self, monkeypatch):
        monkeypatch.setenv("IGRIS_CORE_FILES", "")
        files = get_core_files()
        assert len(files) >= 5  # defaults
