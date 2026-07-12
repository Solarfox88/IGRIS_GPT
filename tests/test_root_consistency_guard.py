"""Root consistency guard tests — #1301 PR-4A.

These tests do NOT change runtime behaviour. They encode the current expected
state of the root model as executable invariants, so regressions are caught
immediately rather than discovered through session/audit path mismatches.

Invariants guarded:
  1. write_auth._get_auth_root() is lazy (reads env at call time, not import time)
  2. AUTH layer reads IGRIS_PROJECT_ROOT, not CONFIG.project_root
  3. CONFIG.igris_dir == CONFIG.project_root / ".igris"
  4. run_preflight audit lands under project_root, not Path.home()
  5. chat_interlocutor_preflight.py has no Path.home() references
  6. routes_01.py preflight block uses IGRIS_PROJECT_ROOT, not CONFIG.project_root
  7. Fallback chain: when IGRIS_PROJECT_ROOT is unset both auth and preflight use "."
  8. WORKSPACE layer (CONFIG.project_root) and AUTH layer (IGRIS_PROJECT_ROOT)
     are independent and can differ without breaking either
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPO = Path(__file__).parent.parent
_WRITE_AUTH = _REPO / "igris" / "api" / "write_auth.py"
_AUTH_ROUTES = _REPO / "igris" / "api" / "routes" / "auth_routes.py"
_PREFLIGHT = _REPO / "igris" / "core" / "chat_interlocutor_preflight.py"
_ROUTES_01 = _REPO / "igris" / "web" / "routers" / "routes_01.py"
_CONFIG = _REPO / "igris" / "models" / "config.py"


# ── 1. write_auth lazy resolution ────────────────────────────────────────────

def test_write_auth_get_auth_root_reads_env_lazily(monkeypatch, tmp_path):
    """_get_auth_root() must return the CURRENT value of IGRIS_PROJECT_ROOT.

    Changing the env var after module import must take effect immediately —
    no module reload required. This is the core fix from PR-1.
    """
    from igris.api.write_auth import _get_auth_root

    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path / "first"))
    assert _get_auth_root() == str(tmp_path / "first")

    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path / "second"))
    assert _get_auth_root() == str(tmp_path / "second")


def test_write_auth_no_module_level_project_root_capture():
    """write_auth.py must NOT capture IGRIS_PROJECT_ROOT at module level.

    A module-level assignment (e.g. _PROJECT_ROOT = os.environ.get(...)) is
    captured once at import time and never updated. The file must use a
    function (_get_auth_root) instead.
    """
    src = _WRITE_AUTH.read_text(encoding="utf-8")
    # The only reference to IGRIS_PROJECT_ROOT must be inside _get_auth_root
    lines = src.splitlines()
    module_level_capture = [
        line for line in lines
        if "IGRIS_PROJECT_ROOT" in line
        and line.strip().startswith("_")   # module-level private var assignment
        and "=" in line
        and "def " not in line
    ]
    assert not module_level_capture, (
        f"write_auth.py captures IGRIS_PROJECT_ROOT at module level: {module_level_capture}"
    )


# ── 2. auth_routes delegates to _get_auth_root ───────────────────────────────

def test_auth_routes_uses_get_auth_root_not_direct_env():
    """auth_routes.py must delegate to _get_auth_root(), not read IGRIS_PROJECT_ROOT directly."""
    src = _AUTH_ROUTES.read_text(encoding="utf-8")
    assert "_get_auth_root" in src, (
        "auth_routes.py must import and use _get_auth_root() from write_auth"
    )
    assert "IGRIS_PROJECT_ROOT" not in src, (
        "auth_routes.py must not read IGRIS_PROJECT_ROOT directly — use _get_auth_root()"
    )


# ── 3. CONFIG.igris_dir invariant ────────────────────────────────────────────

def test_config_igris_dir_always_equals_project_root_dot_igris(tmp_path):
    """CONFIG.igris_dir must always equal project_root / '.igris'."""
    from igris.models.config import Config, LLMConfig

    llm = LLMConfig(provider="ollama", model="phi4-mini", base_url="http://127.0.0.1:11434")
    cfg = Config(
        local_llm=llm,
        fallback_llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash"),
        openai_chat_fallback=LLMConfig(provider="openai", model="gpt-4o-mini"),
        project_root=tmp_path,
    )
    assert cfg.igris_dir == tmp_path / ".igris"
    assert cfg.igris_dir == cfg.project_root / ".igris"


def test_config_igris_dir_not_in_model_dump(tmp_path):
    """igris_dir is a @property, not a stored field — must be absent from model_dump()."""
    from igris.models.config import Config, LLMConfig

    llm = LLMConfig(provider="ollama", model="phi4-mini", base_url="http://127.0.0.1:11434")
    cfg = Config(
        local_llm=llm,
        fallback_llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash"),
        openai_chat_fallback=LLMConfig(provider="openai", model="gpt-4o-mini"),
        project_root=tmp_path,
    )
    assert "igris_dir" not in cfg.model_dump()


# ── 4. run_preflight audit path ───────────────────────────────────────────────

def test_preflight_audit_lands_under_project_root_not_home(monkeypatch, tmp_path):
    """run_preflight must write audit under project_root/.igris/, never under HOME."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path / "project"))

    from igris.core.chat_interlocutor_preflight import run_preflight

    run_preflight(
        message="guard test",
        interlocutor_id="owner",
        project_root=str(tmp_path / "project"),
        is_local_request=True,
    )

    # Audit must be under project_root
    project_audit = tmp_path / "project" / ".igris" / "interlocutor_audit.jsonl"
    assert project_audit.exists(), (
        f"Audit file not found under project_root: {project_audit}"
    )

    # Audit must NOT be under HOME
    home_audit = fake_home / ".igris" / "interlocutor_audit.jsonl"
    assert not home_audit.exists(), (
        "Audit file found under HOME — Path.home() fallback still active in preflight"
    )


# ── 5. No Path.home() in chat_interlocutor_preflight.py ─────────────────────

def test_preflight_source_has_no_path_home():
    """chat_interlocutor_preflight.py must contain no Path.home() references.

    All fallbacks must use '.' (CWD) consistent with the auth root layer.
    """
    src = _PREFLIGHT.read_text(encoding="utf-8")
    home_lines = [
        f"L{i+1}: {line.rstrip()}"
        for i, line in enumerate(src.splitlines())
        if "Path.home()" in line or ".home()" in line
    ]
    assert not home_lines, (
        "chat_interlocutor_preflight.py still contains Path.home() references:\n"
        + "\n".join(home_lines)
    )


# ── 6. routes_01.py preflight uses IGRIS_PROJECT_ROOT ────────────────────────

def test_routes_01_preflight_uses_igris_project_root_not_config():
    """routes_01.py must use IGRIS_PROJECT_ROOT for the preflight project_root.

    CONFIG.project_root reads PROJECT_ROOT (workspace). Auth sessions live under
    IGRIS_PROJECT_ROOT. Using CONFIG.project_root would cause a path mismatch when
    IGRIS_PROJECT_ROOT != PROJECT_ROOT, making valid sessions appear not found.
    """
    src = _ROUTES_01.read_text(encoding="utf-8")
    # The preflight root variable must be sourced from IGRIS_PROJECT_ROOT
    assert "IGRIS_PROJECT_ROOT" in src, "routes_01.py must reference IGRIS_PROJECT_ROOT"

    # Find the preflight root assignment and ensure it does NOT fall back to CONFIG.project_root
    pf_idx = src.find("_pf_project_root")
    assert pf_idx >= 0, "_pf_project_root variable not found in routes_01.py"
    region = src[pf_idx: pf_idx + 300]
    assert "CONFIG.project_root" not in region, (
        "routes_01.py preflight block falls back to CONFIG.project_root — "
        "use IGRIS_PROJECT_ROOT or '.' instead"
    )


# ── 7. Fallback chain: IGRIS_PROJECT_ROOT unset → "." ────────────────────────

def test_auth_root_fallback_to_dot_when_igris_project_root_unset(monkeypatch):
    """When IGRIS_PROJECT_ROOT is not set, _get_auth_root() must return '.'."""
    monkeypatch.delenv("IGRIS_PROJECT_ROOT", raising=False)
    from igris.api.write_auth import _get_auth_root
    assert _get_auth_root() == "."


def test_preflight_fallback_uses_dot_not_home(monkeypatch):
    """Preflight helpers must use '.' (not Path.home()) when project_root is None.

    This is verified by inspecting that 'or \".\"\' appears in preflight source
    and 'Path.home()' does not.
    """
    src = _PREFLIGHT.read_text(encoding="utf-8")
    assert 'or "."' in src, (
        "preflight does not contain 'or \".\"' fallback — expected for project_root-less calls"
    )
    assert "Path.home()" not in src, "Path.home() still present in preflight"


# ── 8. Workspace vs auth root independence ────────────────────────────────────

def test_igris_project_root_and_project_root_are_independent(monkeypatch, tmp_path):
    """IGRIS_PROJECT_ROOT (auth) and PROJECT_ROOT (workspace) can differ safely.

    Auth layer reads IGRIS_PROJECT_ROOT; workspace reads PROJECT_ROOT.
    The two must not be confused.
    """
    auth_root = tmp_path / "auth_root"
    workspace_root = tmp_path / "workspace_root"
    auth_root.mkdir()
    workspace_root.mkdir()

    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(auth_root))
    monkeypatch.setenv("PROJECT_ROOT", str(workspace_root))

    from igris.api.write_auth import _get_auth_root

    resolved_auth = _get_auth_root()
    assert resolved_auth == str(auth_root), (
        f"Auth root must be {auth_root}, got {resolved_auth}"
    )

    # CONFIG.project_root must be workspace_root, not auth_root
    import igris.models.config as cfg_mod
    cfg = cfg_mod.Config.load()
    assert cfg.project_root == workspace_root, (
        f"CONFIG.project_root must be {workspace_root}, got {cfg.project_root}"
    )
    assert cfg.project_root != Path(resolved_auth), (
        "CONFIG.project_root and auth root are the same — "
        "this test expects them to be different when env vars differ"
    )
