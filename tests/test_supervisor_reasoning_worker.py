import json
from pathlib import Path
from unittest.mock import patch

from igris.core import supervisor_reasoning_worker as w
from igris.core.agent_reasoning_loop import LoopResult


def test_progress_file_deleted_on_clean_completion(tmp_path, monkeypatch, capsys):
    payload = {
        "project_root": str(tmp_path),
        "goal": "x",
        "max_steps": 1,
    }
    progress = tmp_path / ".igris" / "reasoning_progress.json"

    def fake_run(self, goal, initial_context, step_callback=None):
        if step_callback:
            step_callback(1, "read_file_range")
        return LoopResult(status="finished", total_steps=1)

    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(payload)))
    with patch("igris.core.agent_reasoning_loop.AgentReasoningLoop.run", fake_run):
        assert w.main() == 0
    assert not progress.exists()
