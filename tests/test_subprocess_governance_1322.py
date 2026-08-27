"""Tests for subprocess governance lint rule (#1322 Phase 3)."""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the check script by adding scripts/ to path
_SCRIPTS_DIR = str(Path(__file__).parent.parent / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import check_subprocess_governance as _mod

check_file = _mod.check_file
check_directory = _mod.check_directory
Violation = _mod.Violation
ALWAYS_ALLOWED = _mod.ALWAYS_ALLOWED
INFRASTRUCTURE_ALLOWED = _mod.INFRASTRUCTURE_ALLOWED
FORBIDDEN_MODULES = _mod.FORBIDDEN_MODULES
ALLOWED_MODULES = _mod.ALLOWED_MODULES


class TestGovernanceCheckOnRepo:
    """Tests that the current repo passes the governance check."""

    def test_repo_passes_governance_check(self) -> None:
        """The current igris/core directory should pass the governance check."""
        root = Path("igris/core")
        violations, stats = check_directory(root)
        assert len(violations) == 0, f"Expected no violations, got: {[v.to_dict() for v in violations]}"

    def test_migrated_modules_not_importing_subprocess(self) -> None:
        """The 4 migrated modules must not import subprocess."""
        for mod in FORBIDDEN_MODULES:
            text = Path(mod).read_text(encoding="utf-8", errors="replace")
            assert "import subprocess" not in text, f"{mod} must not import subprocess (migrated in Phase 2)"

    def test_migrated_modules_use_governed_run(self) -> None:
        """The 4 migrated modules must use governed_run."""
        for mod in FORBIDDEN_MODULES:
            text = Path(mod).read_text(encoding="utf-8", errors="replace")
            assert "governed_run" in text, f"{mod} must use governed_run()"

    def test_allowed_modules_have_rationale(self) -> None:
        """Every allowed module must have a rationale string."""
        for mod, rationale in ALLOWED_MODULES.items():
            assert rationale, f"{mod} has no rationale"
            assert len(rationale) > 10, f"{mod} rationale too short: {rationale}"


class TestViolationDetection:
    """Tests that the check detects unauthorized subprocess usage."""

    def test_unauthorized_import_detected(self) -> None:
        """An unauthorized file with 'import subprocess' should be detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            fake_file = tmpdir_path / "igris" / "core" / "fake_unauthorized.py"
            fake_file.parent.mkdir(parents=True)
            fake_file.write_text("import subprocess\n\nresult = subprocess.run(['echo', 'hi'])\n")

            violations = check_file(fake_file, tmpdir_path / "igris" / "core")
            assert len(violations) >= 1
            assert violations[0].file == str(fake_file)
            assert "import subprocess" in violations[0].symbol
            assert "UNAUTHORIZED" in violations[0].reason

    def test_unauthorized_from_import_detected(self) -> None:
        """An unauthorized file with 'from subprocess import run' should be detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            fake_file = tmpdir_path / "igris" / "core" / "fake_from_import.py"
            fake_file.parent.mkdir(parents=True)
            fake_file.write_text("from subprocess import run\n\nresult = run(['echo', 'hi'])\n")

            violations = check_file(fake_file, tmpdir_path / "igris" / "core")
            assert len(violations) >= 1
            assert "from subprocess import" in violations[0].symbol

    def test_forbidden_module_import_detected(self) -> None:
        """A forbidden (migrated) module importing subprocess should be detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            # Create a file with the same name as a forbidden module
            fake_file = tmpdir_path / "igris" / "core" / "mbop_runner.py"
            fake_file.parent.mkdir(parents=True)
            fake_file.write_text("import subprocess\nresult = subprocess.run(['echo'])\n")

            # Patch the forbidden set to use the actual path
            with patch.object(_mod, "FORBIDDEN_MODULES", {str(fake_file)}):
                violations = check_file(fake_file, tmpdir_path / "igris" / "core")
            assert len(violations) >= 1
            assert "FORBIDDEN" in violations[0].reason

    def test_allowed_module_no_violations(self) -> None:
        """An allowlisted module should produce no violations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            fake_file = tmpdir_path / "igris" / "core" / "tool_runtime.py"
            fake_file.parent.mkdir(parents=True)
            fake_file.write_text("import subprocess\nresult = subprocess.run(['echo'])\n")

            # Patch the allowed set to include the actual path
            with patch.object(_mod, "ALLOWED_MODULES", {str(fake_file): "test"}):
                violations = check_file(fake_file, tmpdir_path / "igris" / "core")
            assert len(violations) == 0

    def test_violation_reports_file_and_line(self) -> None:
        """Violations should include file path and line number."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            fake_file = tmpdir_path / "igris" / "core" / "fake_line_test.py"
            fake_file.parent.mkdir(parents=True)
            fake_file.write_text("# line 1\n# line 2\nimport subprocess\n")

            violations = check_file(fake_file, tmpdir_path / "igris" / "core")
            assert len(violations) == 1
            assert violations[0].line == 3
            assert "fake_line_test.py" in violations[0].file

    def test_no_subprocess_no_violation(self) -> None:
        """A file without subprocess should produce no violations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            fake_file = tmpdir_path / "igris" / "core" / "clean_module.py"
            fake_file.parent.mkdir(parents=True)
            fake_file.write_text("import os\nprint('hello')\n")

            violations = check_file(fake_file, tmpdir_path / "igris" / "core")
            assert len(violations) == 0


class TestPolicyConsistency:
    """Tests that the governance policy is internally consistent."""

    def test_no_overlap_allowed_forbidden(self) -> None:
        """No module should be in both ALLOWED and FORBIDDEN."""
        overlap = set(ALLOWED_MODULES.keys()) & FORBIDDEN_MODULES
        assert len(overlap) == 0, f"Modules in both allowed and forbidden: {overlap}"

    def test_forbidden_modules_are_migrated(self) -> None:
        """Forbidden modules should be the 4 migrated modules."""
        assert len(FORBIDDEN_MODULES) == 4
        assert "igris/core/mbop_runner.py" in FORBIDDEN_MODULES
        assert "igris/core/smw_actions.py" in FORBIDDEN_MODULES
        assert "igris/core/smw_diagnosis.py" in FORBIDDEN_MODULES
        assert "igris/core/smw_teach.py" in FORBIDDEN_MODULES

    def test_always_allowed_includes_authorized(self) -> None:
        """ALWAYS_ALLOWED should include the 3 authorized executors."""
        assert "igris/core/tool_runtime.py" in ALWAYS_ALLOWED
        assert "igris/core/devops_manager.py" in ALWAYS_ALLOWED
        assert "igris/core/supervisor_backend.py" in ALWAYS_ALLOWED
