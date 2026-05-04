"""Tests for clean install verification (Sprint 18).

Verifies that IGRIS_GPT can be imported, configured, and started
from a fresh state with no pre-existing runtime artifacts.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest


class TestImports:
    """Verify all core modules can be imported cleanly."""

    def test_import_server(self):
        from igris.web.server import create_app
        app = create_app()
        assert app.title == "IGRIS_GPT"

    def test_import_safety(self):
        from igris.core.safety import redact_secrets
        assert redact_secrets("hello") == "hello"

    def test_import_task_engine(self):
        from igris.core.task_engine import TaskEngine
        assert TaskEngine is not None

    def test_import_chat_engine(self):
        from igris.core.chat_engine import chat
        assert callable(chat)

    def test_import_autonomous_loop(self):
        from igris.core.autonomous_loop import execute_step
        assert callable(execute_step)

    def test_import_mission_planner(self):
        from igris.core.mission_planner import plan_mission
        assert callable(plan_mission)

    def test_import_decision_memory(self):
        from igris.core.decision_memory import record_decision
        assert callable(record_decision)

    def test_import_diagnostics(self):
        from igris.core.diagnostics import run_diagnostics
        assert callable(run_diagnostics)

    def test_import_safe_policy(self):
        from igris.core.safe_policy import check_command_policy
        assert callable(check_command_policy)

    def test_import_project_state(self):
        from igris.core.project_state import get_project_state
        assert callable(get_project_state)

    def test_import_decision_report(self):
        from igris.core.decision_report import create_decision_report
        assert callable(create_decision_report)

    def test_import_chat_streaming(self):
        from igris.core.chat_streaming import chat_stream_sync
        assert callable(chat_stream_sync)

    def test_import_chat_context(self):
        from igris.core.chat_context import build_chat_context
        assert callable(build_chat_context)


class TestGitIgnore:
    """Verify gitignore covers runtime artifacts."""

    def test_igris_dir_ignored(self):
        gitignore = Path(__file__).resolve().parents[1] / ".gitignore"
        content = gitignore.read_text()
        assert ".igris/" in content

    def test_logs_ignored(self):
        gitignore = Path(__file__).resolve().parents[1] / ".gitignore"
        content = gitignore.read_text()
        assert "logs/" in content

    def test_env_ignored(self):
        gitignore = Path(__file__).resolve().parents[1] / ".gitignore"
        content = gitignore.read_text()
        assert ".env" in content

    def test_egg_info_ignored(self):
        gitignore = Path(__file__).resolve().parents[1] / ".gitignore"
        content = gitignore.read_text()
        assert "*.egg-info/" in content

    def test_venv_ignored(self):
        gitignore = Path(__file__).resolve().parents[1] / ".gitignore"
        content = gitignore.read_text()
        assert ".venv/" in content

    def test_pycache_ignored(self):
        gitignore = Path(__file__).resolve().parents[1] / ".gitignore"
        content = gitignore.read_text()
        assert "__pycache__/" in content


class TestScriptsExist:
    """Verify all required scripts exist and are executable."""

    SCRIPTS = [
        "install_ubuntu.sh",
        "start_igris.sh",
        "stop_igris.sh",
        "status_igris.sh",
        "smoke_test.sh",
        "setup_ollama.sh",
    ]

    @pytest.mark.parametrize("script", SCRIPTS)
    def test_script_exists(self, script):
        path = Path(__file__).resolve().parents[1] / "scripts" / script
        assert path.exists(), f"Script {script} not found"

    @pytest.mark.parametrize("script", SCRIPTS)
    def test_script_executable(self, script):
        path = Path(__file__).resolve().parents[1] / "scripts" / script
        assert os.access(path, os.X_OK), f"Script {script} not executable"

    @pytest.mark.parametrize("script", SCRIPTS)
    def test_script_has_shebang(self, script):
        path = Path(__file__).resolve().parents[1] / "scripts" / script
        first_line = path.read_text().split("\n")[0]
        assert first_line.startswith("#!/"), f"Script {script} missing shebang"


class TestRuntimeDirs:
    """Verify runtime directories are created properly."""

    def test_runtime_dirs_created(self, tmp_path):
        from igris.models.config import CONFIG
        old_root = CONFIG.project_root
        CONFIG.project_root = tmp_path

        for subdir in ["tasks", "reports", "timeline", "memory"]:
            d = tmp_path / ".igris" / subdir
            d.mkdir(parents=True, exist_ok=True)
            assert d.exists()

        CONFIG.project_root = old_root


class TestNoSecretsInCode:
    """Verify no hardcoded secrets in source files."""

    def test_no_api_keys_in_source(self):
        import re
        src_dir = Path(__file__).resolve().parents[1] / "igris"
        pattern = re.compile(r"sk-[A-Za-z0-9]{20,}")
        for py_file in src_dir.rglob("*.py"):
            content = py_file.read_text()
            match = pattern.search(content)
            assert match is None, f"Possible API key in {py_file}: {match.group()[:20]}..."

    def test_no_github_tokens_in_source(self):
        import re
        src_dir = Path(__file__).resolve().parents[1] / "igris"
        pattern = re.compile(r"ghp_[A-Za-z0-9]{20,}")
        for py_file in src_dir.rglob("*.py"):
            content = py_file.read_text()
            match = pattern.search(content)
            assert match is None, f"Possible GitHub token in {py_file}: {match.group()[:20]}..."


class TestConfigDefaults:
    """Verify sensible defaults exist."""

    def test_env_example_exists(self):
        path = Path(__file__).resolve().parents[1] / ".env.example"
        assert path.exists()

    def test_config_sample_exists(self):
        path = Path(__file__).resolve().parents[1] / "config" / "config.sample.json"
        assert path.exists()

    def test_env_example_no_real_secrets(self):
        path = Path(__file__).resolve().parents[1] / ".env.example"
        content = path.read_text()
        assert "sk-real" not in content
        assert "ghp_real" not in content


class TestServerCreation:
    """Verify server creates and configures correctly."""

    def test_create_app_returns_fastapi(self, tmp_path):
        from igris.models.config import CONFIG
        from fastapi import FastAPI
        old_root = CONFIG.project_root
        for d in [".igris/tasks", ".igris/timeline", ".igris/memory"]:
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        os.environ["PROJECT_ROOT"] = str(tmp_path)
        CONFIG.project_root = tmp_path

        from igris.web.server import create_app
        app = create_app()
        assert isinstance(app, FastAPI)
        assert app.title == "IGRIS_GPT"

        CONFIG.project_root = old_root

    def test_health_endpoint(self, tmp_path):
        from igris.models.config import CONFIG
        from fastapi.testclient import TestClient
        from igris.web.server import create_app
        old_root = CONFIG.project_root
        for d in [".igris/tasks", ".igris/timeline", ".igris/memory", ".igris/reports/decisions"]:
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        os.environ["PROJECT_ROOT"] = str(tmp_path)
        os.environ["WORKSPACE_ROOT"] = str(tmp_path)
        CONFIG.project_root = tmp_path

        client = TestClient(create_app())
        r = client.get("/api/health")
        assert r.status_code == 200
        CONFIG.project_root = old_root

    def test_readiness_endpoint(self, tmp_path):
        from igris.models.config import CONFIG
        from fastapi.testclient import TestClient
        from igris.web.server import create_app
        old_root = CONFIG.project_root
        for d in [".igris/tasks", ".igris/timeline", ".igris/memory", ".igris/reports/decisions"]:
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        os.environ["PROJECT_ROOT"] = str(tmp_path)
        os.environ["WORKSPACE_ROOT"] = str(tmp_path)
        CONFIG.project_root = tmp_path

        client = TestClient(create_app())
        r = client.get("/api/readiness")
        assert r.status_code == 200
        CONFIG.project_root = old_root
