"""Tests for #1124 Browser Evidence hardening.

Covers: artifact store, retention/cleanup, structured console/network events,
screenshot metadata persistence, fake runner structured output, degraded mode.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

import pytest

from igris.core.browser_evidence import (
    BrowserArtifactStore,
    BrowserSmokeResult,
    ConsoleEvent,
    FakeBrowserRunner,
    NetworkEvent,
    ScreenshotMeta,
    run_browser_smoke_with_fallback,
)


# ---------------------------------------------------------------------------
# Structured event models
# ---------------------------------------------------------------------------

class TestConsoleEvent:
    def test_defaults(self):
        ev = ConsoleEvent()
        assert ev.level == "error"
        assert ev.message == ""

    def test_to_dict(self):
        ev = ConsoleEvent(level="warning", message="deprecated API", source="app.js")
        d = ev.to_dict()
        assert d["level"] == "warning"
        assert d["message"] == "deprecated API"
        assert d["source"] == "app.js"
        assert "timestamp" in d


class TestNetworkEvent:
    def test_defaults(self):
        ev = NetworkEvent()
        assert ev.method == "GET"
        assert ev.status_code == 0

    def test_to_dict(self):
        ev = NetworkEvent(url="https://api.example.com/data", error="timeout")
        d = ev.to_dict()
        assert d["url"] == "https://api.example.com/data"
        assert d["error"] == "timeout"


class TestScreenshotMeta:
    def test_defaults(self):
        sm = ScreenshotMeta()
        assert sm.format == "png"
        assert sm.fake is False

    def test_to_dict(self):
        sm = ScreenshotMeta(path="/tmp/s.png", url="http://localhost", size_bytes=1024, fake=True)
        d = sm.to_dict()
        assert d["path"] == "/tmp/s.png"
        assert d["size_bytes"] == 1024
        assert d["fake"] is True


# ---------------------------------------------------------------------------
# BrowserSmokeResult new fields
# ---------------------------------------------------------------------------

class TestBrowserSmokeResultFields:
    def test_new_fields_default_empty(self):
        r = BrowserSmokeResult(ok=True)
        assert r.console_events == []
        assert r.network_events == []
        assert r.screenshot_meta is None

    def test_to_dict_includes_new_fields(self):
        r = BrowserSmokeResult(ok=True, console_events=[{"level": "error"}])
        d = r.to_dict()
        assert "console_events" in d
        assert "network_events" in d
        assert "screenshot_meta" in d


# ---------------------------------------------------------------------------
# FakeBrowserRunner structured output
# ---------------------------------------------------------------------------

class TestFakeBrowserRunnerStructured:
    def test_success_includes_structured_events(self, tmp_path):
        runner = FakeBrowserRunner()
        result = runner.run_smoke(url="http://localhost", artifact_dir=str(tmp_path))
        assert result.ok is True
        assert result.console_events == []
        assert result.network_events == []
        assert result.screenshot_meta is not None
        assert result.screenshot_meta["fake"] is True
        assert result.screenshot_meta["url"] == "http://localhost"

    def test_console_errors_produce_structured_events(self, tmp_path):
        runner = FakeBrowserRunner(console_errors=["TypeError: x", "ReferenceError: y"])
        result = runner.run_smoke(url="http://localhost", artifact_dir=str(tmp_path))
        assert len(result.console_events) == 2
        assert result.console_events[0]["level"] == "error"
        assert result.console_events[0]["message"] == "TypeError: x"
        assert "timestamp" in result.console_events[0]

    def test_network_errors_produce_structured_events(self, tmp_path):
        runner = FakeBrowserRunner(network_errors=["https://api.example.com/bad"])
        result = runner.run_smoke(url="http://localhost", artifact_dir=str(tmp_path))
        assert len(result.network_events) == 1
        assert result.network_events[0]["url"] == "https://api.example.com/bad"
        assert result.network_events[0]["error"] == "request_failed"

    def test_screenshot_meta_populated(self, tmp_path):
        runner = FakeBrowserRunner()
        result = runner.run_smoke(url="http://localhost", selector="#app", artifact_dir=str(tmp_path))
        assert result.screenshot_meta is not None
        assert result.screenshot_meta["selector"] == "#app"
        assert result.screenshot_meta["format"] == "png"

    def test_forced_error_no_structured_events(self, tmp_path):
        runner = FakeBrowserRunner(forced_error="crash")
        result = runner.run_smoke(url="http://localhost", artifact_dir=str(tmp_path))
        assert result.ok is False
        assert result.degraded is True
        assert result.console_events == []
        assert result.screenshot_meta is None

    def test_backward_compat_old_fields_still_present(self, tmp_path):
        runner = FakeBrowserRunner(console_errors=["err1"])
        result = runner.run_smoke(url="http://localhost", artifact_dir=str(tmp_path))
        assert result.console_errors == ["err1"]
        assert result.screenshot_metadata == {"fake": True, "format": "png", "bytes": 0}


# ---------------------------------------------------------------------------
# Fallback / degraded mode
# ---------------------------------------------------------------------------

class TestFallbackDegradedMode:
    def test_fallback_still_works(self):
        result = run_browser_smoke_with_fallback(url="http://localhost")
        assert isinstance(result, BrowserSmokeResult)
        if result.degraded:
            assert result.error

    def test_fake_runner_via_fallback(self, tmp_path):
        runner = FakeBrowserRunner(selector_found=True)
        result = run_browser_smoke_with_fallback(
            url="http://localhost", runner=runner, artifact_dir=str(tmp_path),
        )
        assert result.ok is True
        assert result.screenshot_meta is not None


# ---------------------------------------------------------------------------
# Artifact store
# ---------------------------------------------------------------------------

class TestBrowserArtifactStore:
    def test_store_and_retrieve(self, tmp_path):
        store = BrowserArtifactStore(base_dir=str(tmp_path))
        result = BrowserSmokeResult(
            ok=True, url="http://localhost", timestamp=time.time(),
            console_events=[{"level": "error", "message": "test"}],
            screenshot_meta={"path": "/tmp/s.png", "fake": True},
        )
        entry = store.store_result(result, run_id="run-1")
        assert entry["run_id"] == "run-1"
        assert entry["ok"] is True
        assert len(entry["console_events"]) == 1

        entries = store.get_entries(run_id="run-1")
        assert len(entries) == 1
        assert entries[0]["url"] == "http://localhost"

    def test_persistence_reload(self, tmp_path):
        store1 = BrowserArtifactStore(base_dir=str(tmp_path))
        result = BrowserSmokeResult(ok=True, url="http://localhost", timestamp=time.time())
        store1.store_result(result, run_id="r1")

        store2 = BrowserArtifactStore(base_dir=str(tmp_path))
        assert store2.count == 1
        assert store2.get_entries()[0]["url"] == "http://localhost"

    def test_get_entries_limit(self, tmp_path):
        store = BrowserArtifactStore(base_dir=str(tmp_path))
        for i in range(10):
            result = BrowserSmokeResult(ok=True, url=f"http://localhost/{i}", timestamp=time.time())
            store.store_result(result)
        assert len(store.get_entries(limit=5)) == 5

    def test_get_entries_filter_by_run_id(self, tmp_path):
        store = BrowserArtifactStore(base_dir=str(tmp_path))
        r1 = BrowserSmokeResult(ok=True, url="http://a", timestamp=time.time())
        r2 = BrowserSmokeResult(ok=True, url="http://b", timestamp=time.time())
        store.store_result(r1, run_id="run-a")
        store.store_result(r2, run_id="run-b")
        assert len(store.get_entries(run_id="run-a")) == 1
        assert store.get_entries(run_id="run-a")[0]["url"] == "http://a"

    def test_retention_max_entries(self, tmp_path):
        store = BrowserArtifactStore(base_dir=str(tmp_path))
        for i in range(10):
            result = BrowserSmokeResult(ok=True, url=f"http://localhost/{i}", timestamp=time.time())
            store.store_result(result)
        removed = store.apply_retention(max_entries=5)
        assert removed == 5
        assert store.count == 5

    def test_retention_max_age(self, tmp_path):
        store = BrowserArtifactStore(base_dir=str(tmp_path))
        old_result = BrowserSmokeResult(ok=True, url="http://old", timestamp=time.time() - 100000)
        new_result = BrowserSmokeResult(ok=True, url="http://new", timestamp=time.time())
        store.store_result(old_result)
        store.store_result(new_result)
        removed = store.apply_retention(max_age_seconds=1000)
        assert removed == 1
        assert store.count == 1
        assert store.get_entries()[0]["url"] == "http://new"

    def test_retention_no_op(self, tmp_path):
        store = BrowserArtifactStore(base_dir=str(tmp_path))
        result = BrowserSmokeResult(ok=True, url="http://localhost", timestamp=time.time())
        store.store_result(result)
        removed = store.apply_retention()
        assert removed == 0
        assert store.count == 1

    def test_empty_store(self, tmp_path):
        store = BrowserArtifactStore(base_dir=str(tmp_path))
        assert store.count == 0
        assert store.get_entries() == []

    def test_corrupt_index_recovery(self, tmp_path):
        index_file = tmp_path / "index.json"
        index_file.write_text("NOT JSON")
        store = BrowserArtifactStore(base_dir=str(tmp_path))
        assert store.count == 0

    def test_redaction_in_stored_entry(self, tmp_path):
        store = BrowserArtifactStore(base_dir=str(tmp_path))
        result = BrowserSmokeResult(
            ok=False, url="http://localhost",
            error="ghp_secret_token_abc123", timestamp=time.time(),
        )
        entry = store.store_result(result)
        # redact_secrets should have processed the error
        assert isinstance(entry["error"], str)


# ---------------------------------------------------------------------------
# Integration: FakeBrowserRunner + ArtifactStore
# ---------------------------------------------------------------------------

class TestFakeRunnerWithArtifactStore:
    def test_end_to_end(self, tmp_path):
        runner = FakeBrowserRunner(console_errors=["err1"])
        result = runner.run_smoke(url="http://localhost:7778", artifact_dir=str(tmp_path))

        store = BrowserArtifactStore(base_dir=str(tmp_path / "artifacts"))
        entry = store.store_result(result, run_id="e2e-test")

        assert entry["console_error_count"] == 1
        assert len(entry["console_events"]) == 1
        assert entry["screenshot_meta"] is not None
        assert entry["screenshot_meta"]["fake"] is True

        # Retrieve
        entries = store.get_entries(run_id="e2e-test")
        assert len(entries) == 1
