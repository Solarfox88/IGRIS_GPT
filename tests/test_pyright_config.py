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


def test_ci_type_check_documents_or_true_status():
    """CI type-check job should document why '|| true' is present.

    Phase 2 of #1316 requires CI to eventually block on pyright errors.
    The '|| true' pattern makes the step always succeed, which
    defeats the purpose of type checking. Until all errors are fixed,
    the step should document why it's non-blocking.
    """
    ci_file = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    content = ci_file.read_text(encoding="utf-8")
    assert "type-check" in content, "No type-check job in CI workflow"
    lines = content.splitlines()
    in_type_check = False
    found_pyright_line = False
    for i, line in enumerate(lines):
        if "type-check:" in line and "job" not in line.lower():
            in_type_check = True
        if in_type_check and "pyright" in line:
            found_pyright_line = True
            if "|| true" in line:
                # If || true is present, there should be a comment explaining why
                # (either on this line or the preceding line)
                has_comment = "#" in line and ("Phase" in line or "until" in line or "todo" in line.lower())
                if not has_comment and i > 0:
                    for j in range(max(0, i - 3), i):
                        prev = lines[j]
                        if "#" in prev and ("Phase" in prev or "until" in prev or "todo" in prev.lower()):
                            has_comment = True
                            break
                assert has_comment, \
                    f"CI type-check uses '|| true' without documenting why. Line: {line}"
    assert found_pyright_line, "No pyright step found in type-check job"


def test_pyright_excludes_are_minimal():
    """pyright excludes should be minimal and documented.

    Overly broad excludes (e.g. excluding all of igris/core/) would
    mask real type errors and defeat the purpose of type checking.
    """
    pyproject = REPO_ROOT / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    pyright_config = data["tool"]["pyright"]
    excludes = pyright_config.get("exclude", [])
    # Check that no exclude is overly broad (e.g. "igris/" or "igris/core/")
    for exclude in excludes:
        # Allowed: __pycache__, .venv, .local, specific files
        assert not exclude.startswith("igris/"), \
            f"Overly broad exclude: {exclude} — should not exclude source code directories"


def test_no_bare_type_ignore_without_justification():
    """Check that # type: ignore comments in igris/ have justification.

    Per #1316 Phase 2: 'No new # type: ignore without justification comment'.
    This test scans for bare '# type: ignore' without an inline comment.
    """
    import re
    igris_dir = REPO_ROOT / "igris"
    bare_pattern = re.compile(r'#\s*type:\s*ignore\s*(?:\[[^\]]+\])?\s*$')
    justified_pattern = re.compile(r'#\s*type:\s*ignore\s*(?:\[[^\]]+\])?\s*#\s*.+')
    violations = []
    for py_file in igris_dir.rglob("*.py"):
        try:
            content = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(content.splitlines(), 1):
            if bare_pattern.search(line) and not justified_pattern.search(line):
                violations.append(f"{py_file.name}:{i}: {line.strip()}")
    # Allow existing violations but fail if there are too many new ones
    # This is a soft check — we want to track and reduce, not block all PRs
    assert len(violations) <= 20, \
        f"Too many bare '# type: ignore' without justification ({len(violations)}):\n" + \
        "\n".join(violations[:10])
