"""Tests for #1316 — pyright type checking configuration.

Verifies that:
- pyproject.toml has [tool.pyright] section
- CI workflow includes a type-check job
- pyright is in dev dependencies
- pyright configuration uses basic mode
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent


def test_pyproject_has_pyright_config():
    """pyproject.toml has [tool.pyright] section."""
    pyproject = REPO_ROOT / "pyproject.toml"
    assert pyproject.exists(), "pyproject.toml not found"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    assert "tool" in data, "No [tool] section in pyproject.toml"
    assert "pyright" in data["tool"], "No [tool.pyright] section in pyproject.toml"


def test_pyright_basic_mode():
    """pyright is configured in basic mode."""
    pyproject = REPO_ROOT / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    pyright_config = data["tool"]["pyright"]
    assert pyright_config.get("typeCheckingMode") == "basic", \
        f"Expected typeCheckingMode='basic', got '{pyright_config.get('typeCheckingMode')}'"


def test_pyright_python_version():
    """pyright targets Python 3.12."""
    pyproject = REPO_ROOT / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    pyright_config = data["tool"]["pyright"]
    assert pyright_config.get("pythonVersion") == "3.12"


def test_pyright_in_dev_dependencies():
    """pyright is listed in dev dependencies."""
    pyproject = REPO_ROOT / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    dev_deps = data["project"]["optional-dependencies"]["dev"]
    assert any("pyright" in dep for dep in dev_deps), \
        f"pyright not found in dev dependencies: {dev_deps}"


def test_ci_has_type_check_job():
    """CI workflow includes a type-check job."""
    ci_file = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    assert ci_file.exists(), "CI workflow file not found"
    content = ci_file.read_text(encoding="utf-8")
    assert "type-check" in content, "No type-check job in CI workflow"
    assert "pyright" in content, "No pyright step in CI workflow"


def test_pyright_includes_igris():
    """pyright is configured to check igris/ directory."""
    pyproject = REPO_ROOT / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    pyright_config = data["tool"]["pyright"]
    includes = pyright_config.get("include", [])
    assert "igris/" in includes, f"igris/ not in pyright include: {includes}"


def test_pyright_excludes_local():
    """pyright excludes .local/ directory."""
    pyproject = REPO_ROOT / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    pyright_config = data["tool"]["pyright"]
    excludes = pyright_config.get("exclude", [])
    assert any(".local" in e for e in excludes), \
        f".local/ not in pyright exclude: {excludes}"
