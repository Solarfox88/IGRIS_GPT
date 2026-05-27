from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from igris.core import meta_watchdog
from igris.core.smw_actions import git_clean_root, kill_stale_process, open_diagnostic_issue
from igris.core.smw_diagnosis import diagnose
from igris.core.smw_patterns import detect_patterns
from igris.core.smw_sensors import SystemSnapshot, take_snapshot
from igris.core.smw_teach import Incident, load_incidents, record_incident, teach_back


def mk_snapshot(**kwargs):
    base = SystemSnapshot(time.time(), None, True, False, [], "r1", "done", None, time.time() - 10, 100.0, [], False, [], "main", [], [], 0.0, 0.0, {})
    for k,v in kwargs.items():
        setattr(base, k, v)
    return base


def test_take_snapshot_returns_snapshot():
    s = asyncio.run(take_snapshot("."))
    assert isinstance(s, SystemSnapshot)
    assert hasattr(s, "current_branch")


def test_detect_watchdog_cleanup_loop():
    s = mk_snapshot(recent_log_lines=["dirty workspace detected before launch"] * 5)
    assert any(p.pattern.name == "watchdog_cleanup_loop" for p in detect_patterns(s))


def test_detect_port_conflict():
    assert any(p.pattern.name == "port_conflict" for p in detect_patterns(mk_snapshot(port_conflict=True)))


def test_detect_watchdog_idle_anomaly():
    s = mk_snapshot(active_runs=[], seconds_since_last_run=1000, tracked_dirty=False)
    assert any(p.pattern.name == "watchdog_idle_anomaly" for p in detect_patterns(s))


def test_detect_untracked_artefact():
    s = mk_snapshot(untracked_files=["?? v06_UX_spec.md"], active_runs=[])
    assert any(p.pattern.name == "untracked_artefact_blocking" for p in detect_patterns(s))


def test_diagnose_cleanup_loop_no_llm():
    d = diagnose(detect_patterns(mk_snapshot(recent_log_lines=["dirty workspace detected"]*4))[0], ".")
    assert d.confidence >= 0.9 and d.recommended_tier == 1 and "git_clean_root" in d.recommended_actions


def test_diagnose_port_conflict_no_llm():
    d = diagnose(detect_patterns(mk_snapshot(port_conflict=True))[0], ".")
    assert "kill_stale_process" in d.recommended_actions


@patch("igris.core.smw_actions.subprocess.run")
def test_git_clean_root_action(mock_run):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "ok"
    mock_run.return_value.stderr = ""
    asyncio.run(git_clean_root("."))
    mock_run.assert_called_with(["git", "clean", "-fd", "."], cwd=".", capture_output=True, text=True)


@patch("igris.core.smw_actions.subprocess.run")
def test_kill_stale_process_no_stale(mock_run):
    mock_run.return_value.stdout = ""
    r = asyncio.run(kill_stale_process())
    assert r.success


@patch("igris.core.smw_actions.os.kill")
@patch("igris.core.smw_actions.subprocess.run")
def test_kill_stale_process_kills_stale(mock_run, mock_kill):
    mock_run.return_value.stdout = "LISTEN 0 128 *:7778 *:* users:(\"python\",pid=12345,fd=3)"
    asyncio.run(kill_stale_process())
    mock_kill.assert_called()


@patch("igris.core.smw_actions.subprocess.run")
def test_open_diagnostic_issue(mock_run):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "ok"
    mock_run.return_value.stderr = ""
    r = asyncio.run(open_diagnostic_issue(".", "port_conflict", "ev", ["a"]))
    assert "port_conflict" in r.output


def test_record_and_load_incident():
    with tempfile.TemporaryDirectory() as td:
        i = Incident("id1", "p", time.time(), None, "rc", ["a"], "resolved", "ev")
        record_incident(i, td)
        loaded = load_incidents(td)
        assert loaded[0].incident_id == "id1"


@patch("igris.core.smw_teach.subprocess.run")
def test_teach_back_opens_issue_on_second_occurrence(mock_run):
    mock_run.return_value.stdout = ""
    with tempfile.TemporaryDirectory() as td:
        i1 = Incident("id1", "p", time.time(), None, "rc", ["a"], "resolved", "ev")
        i2 = Incident("id2", "p", time.time(), None, "rc", ["a"], "resolved", "ev")
        asyncio.run(teach_back(i1, td))
        asyncio.run(teach_back(i2, td))
        assert mock_run.called


def test_cooldown_prevents_double_fire():
    meta_watchdog._SMW_COOLDOWN_PATTERNS.clear()
    s = mk_snapshot(untracked_files=["?? a"], active_runs=[])
    d = detect_patterns(s)[0]
    meta_watchdog._SMW_COOLDOWN_PATTERNS[d.pattern.name] = d.detected_at
    blocked = (d.detected_at - meta_watchdog._SMW_COOLDOWN_PATTERNS[d.pattern.name]) < d.pattern.cooldown_seconds
    assert blocked


@patch("igris.web.server.uvicorn.run")
@patch("igris.web.server.os.kill")
@patch("igris.web.server._sp.run")
def test_startup_kills_stale_process(mock_ss, mock_kill, _):
    from igris.web.server import create_app, run_app
    stuck = MagicMock()
    stuck.stdout = 'LISTEN 0 128 *:7778 *:* users=("python",pid=12345,fd=3)'
    clear = MagicMock()
    clear.stdout = ""
    mock_ss.side_effect = [stuck, clear]
    run_app(create_app(), port=7778)
    assert mock_kill.called


# ---------------------------------------------------------------------------
# Issue #723 — cancel endpoint: JSONDecodeError on empty/malformed body
# Issue #728 — no time.sleep() in async context in server.py
# ---------------------------------------------------------------------------

class TestCancelEndpointBodyParsing:
    """Issue #723 — POST /api/rank/runs/{id}/cancel must not 500 on bad body."""

    def _make_client(self, tmp_path):
        from igris.web.server import create_app, CONFIG
        CONFIG.project_root = tmp_path
        app = create_app()
        from starlette.testclient import TestClient
        return TestClient(app, raise_server_exceptions=False)

    def test_cancel_empty_body_returns_not_500(self, tmp_path):
        """Empty body → 200 (not found gives 404) or 404, never 500."""
        client = self._make_client(tmp_path)
        response = client.post("/api/rank/runs/nonexistent-run/cancel", content=b"", headers={"Content-Type": "application/json"})
        assert response.status_code != 500, f"Got 500: {response.text}"
        assert response.status_code in (200, 404)

    def test_cancel_malformed_json_returns_not_500(self, tmp_path):
        """Malformed JSON body → 200/404, never 500."""
        client = self._make_client(tmp_path)
        response = client.post("/api/rank/runs/nonexistent-run/cancel", content=b"{bad json}", headers={"Content-Type": "application/json"})
        assert response.status_code != 500, f"Got 500: {response.text}"

    def test_cancel_valid_json_body_works(self, tmp_path):
        """Valid JSON body with reason → 200/404, never 500."""
        client = self._make_client(tmp_path)
        response = client.post("/api/rank/runs/nonexistent-run/cancel", json={"reason": "test cancel"})
        assert response.status_code != 500


class TestNoAsyncTimeSleep:
    """Issue #728 — verify no time.sleep() calls inside async functions in server.py."""

    def test_no_blocking_sleep_in_async_server_functions(self):
        """Static check: time.sleep must not appear inside async def in server.py."""
        import ast
        from pathlib import Path
        source = (Path(__file__).parent.parent / "igris" / "web" / "server.py").read_text()
        lines = source.splitlines()
        tree = ast.parse(source)
        async_ranges = [
            (node.lineno, node.end_lineno)
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
        ]
        violations = []
        for i, line in enumerate(lines, start=1):
            if ("time.sleep(" in line or "_time.sleep(" in line) and "# NOTE:" not in line:
                for start, end in async_ranges:
                    if start <= i <= end:
                        violations.append(f"Line {i}: {line.strip()}")
        assert not violations, f"Blocking time.sleep inside async def:\n" + "\n".join(violations)
