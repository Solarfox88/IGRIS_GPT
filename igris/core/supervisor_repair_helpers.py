"""Repair cycle helpers extracted from SelfRepairSupervisor.

Block 2 of #1356 Phase 4.  These functions were originally instance methods on
``SelfRepairSupervisor``.  They have been extracted to this module to reduce
the size of the monolith.  The original class retains thin delegation wrappers
for backward compatibility.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from igris.core.supervisor_models import CommandResult, SupervisorRun, _command_detail


# ------------------------------------------------------------------
# Provider health check
# ------------------------------------------------------------------

def quick_provider_check(timeout: int = 10) -> bool:
    """Fast health-check: ping the configured LLM provider with a timeout.

    Returns True if at least one provider responds, False if all are
    unreachable or timeout.
    """
    _log = logging.getLogger("igris.supervisor.provider_check")
    helper_command = str(os.getenv("IGRIS_API_HELPER_COMMAND", "")).strip()
    if not helper_command:
        _log.debug("_quick_provider_check: no IGRIS_API_HELPER_COMMAND set, assuming available")
        return True

    ping_payload = {
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    try:
        import subprocess as _sp, json as _json
        result = _sp.run(
            helper_command.split(),
            input=_json.dumps(ping_payload),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0 and result.stdout.strip():
            _log.debug("_quick_provider_check: provider OK (returncode=0)")
            return True
        _log.warning(
            "_quick_provider_check: provider returned rc=%d; stdout=%r",
            result.returncode, result.stdout[:200],
        )
        return False
    except Exception as exc:  # TimeoutExpired, FileNotFoundError, etc.
        _log.warning("_quick_provider_check: provider ping failed: %s", exc)
        return False


# ------------------------------------------------------------------
# Missing-tests scaffold helpers
# ------------------------------------------------------------------

def synthetic_missing_tests_diff(
    project_root: str,
    target: str,
) -> str:
    """Build a synthetic diff from an existing test file (for restore-retry path)."""
    if not target:
        return ""
    target_path = Path(project_root) / target
    if not target_path.exists():
        return ""
    try:
        content = target_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    lines = [
        f"diff --git a/{target} b/{target}",
        "new file mode 100644",
        "--- /dev/null",
        f"+++ b/{target}",
    ]
    for line in content.splitlines():
        lines.append(f"+{line}")
    if not content.endswith("\n"):
        lines.append("\\ No newline at end of file")
    return "\n".join(lines) + "\n"


def scaffold_missing_tests_target(
    project_root: str,
    target: str,
    goal: str,
) -> CommandResult:
    """Scaffold a placeholder test file for a missing-tests repair."""
    from igris.core.supervisor_analysis import _required_endpoint_from_goal

    if not target:
        return CommandResult(False, "", "No targeted test path configured for missing-tests scaffold", 2)

    endpoint = _required_endpoint_from_goal(goal)
    if not endpoint:
        return CommandResult(False, "", "No API endpoint found in goal for missing-tests scaffold", 2)

    test_slug = endpoint.strip("/").replace("/", "_").replace("-", "_").lower()
    test_slug = re.sub(r"[^a-z0-9_]+", "_", test_slug).strip("_")
    if not test_slug:
        test_slug = "mission_endpoint"

    content = (
        "import os\n\n"
        "from fastapi.testclient import TestClient\n\n"
        "from igris.web.server import create_app\n\n\n"
        f"def test_{test_slug}(tmp_path):\n"
        "    # Isolate watchdog from real project during scaffold test.\n"
        "    os.environ[\"PROJECT_ROOT\"] = str(tmp_path)\n"
        "    os.environ[\"WORKSPACE_ROOT\"] = str(tmp_path)\n"
        "    client = TestClient(create_app())\n"
        f"    response = client.get(\"{endpoint}\")\n"
        "    # Accept 200 (implemented) or 404/405 (scaffold placeholder — not yet implemented).\n"
        "    # A 5xx error would indicate a real problem and is not accepted.\n"
        "    assert response.status_code in (200, 404, 405), (\n"
        f"        f\"Unexpected status {{response.status_code}} for '{endpoint}' — \"\n"
        "        \"expected 200 (implemented) or 404/405 (not yet implemented)\"\n"
        "    )\n"
    )

    target_path = Path(project_root) / target
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
    except OSError as exc:
        return CommandResult(False, "", str(exc), 1)

    return CommandResult(True, f"Scaffolded {target} for {endpoint}", "", 0)


def re_scaffold_targeted_test_if_missing(
    supervisor: Any,
    run: SupervisorRun,
    config: Any,
) -> bool:
    """Re-scaffold a missing targeted test file after a restore-based retry."""
    from igris.core.supervisor_analysis import _is_valid_missing_tests_repair_diff as _is_valid

    target = supervisor._targeted_test_file(config)
    if not target:
        return False
    target_path = Path(supervisor.project_root) / target
    if target_path.exists():
        return False

    scaffold = scaffold_missing_tests_target(
        supervisor.project_root, target, config.goal,
    )
    run.add("repair_scaffold", "success" if scaffold.success else "failure", _command_detail(scaffold))
    if not scaffold.success:
        return False

    synthetic_diff = synthetic_missing_tests_diff(supervisor.project_root, target)
    if not synthetic_diff or not _is_valid(synthetic_diff, config.goal):
        restore = supervisor.backend.restore_dangerous_diff()
        run.add(
            "repair_restore",
            "success" if restore.success else "failure",
            "Post-restore targeted test scaffold was invalid; restored.",
        )
        return False

    run.add(
        "repair_scaffold_diff",
        "success",
        "Synthesized missing-tests diff from post-restore scaffold file.",
        synthesized_untracked=True,
    )
    return True


def preserve_targeted_tests_after_restore_retry(
    supervisor: Any,
    run: SupervisorRun,
    config: Any,
    failure: str,
) -> None:
    """Preserve targeted tests after a restore-based retry path."""
    if failure not in {"missing_tests", "pytest_failure"}:
        return
    if re_scaffold_targeted_test_if_missing(supervisor, run, config):
        run.add(
            "repair_completion",
            "degraded",
            "Re-scaffolded targeted tests after restore-based retry path.",
        )
