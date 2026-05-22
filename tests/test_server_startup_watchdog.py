from types import SimpleNamespace
from unittest.mock import patch

import pytest

from igris.web import server


def test_run_app_opens_issue_after_port_failure():
    ss_result = SimpleNamespace(stdout='LISTEN 0 128 *:7778 *:* users:("python",pid=111,fd=3)')
    issue_result = SimpleNamespace(stdout="", stderr="", returncode=0)

    with patch.object(server._sp, "run", side_effect=[ss_result, ss_result, ss_result, issue_result]) as mock_run, \
         patch.object(server.os, "kill"), \
         patch.object(server.uvicorn, "run"), \
         patch.object(server._time, "sleep"), \
         pytest.raises(SystemExit) as exc:
        server.run_app(server.create_app(), port=7778)

    assert exc.value.code == 1
    cmd = mock_run.call_args_list[-1].args[0]
    assert cmd[:3] == ["gh", "issue", "create"]
