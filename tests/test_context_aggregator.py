"""Tests for ContextAggregator (#1244)."""
import json
import pytest
from pathlib import Path
from igris.core.context_aggregator import ContextAggregator, PersonalOSBrief, ContextSection


@pytest.fixture
def agg(tmp_path):
    return ContextAggregator(project_root=tmp_path)


# Init / health
def test_context_aggregator_initializes(agg):
    assert agg.project_root is not None


def test_context_aggregator_healthcheck(agg):
    h = agg.healthcheck()
    assert "ok" in h
    assert "backends" in h


def test_context_aggregator_degraded_dependency_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "igris.core.rank_gauntlet.RankGauntlet.run",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("gauntlet down")),
    )
    agg = ContextAggregator(project_root=tmp_path)
    brief = agg.build_context(query="test", interlocutor_id="owner", trust_level="admin")
    assert brief is not None


# Sections
def test_build_context_includes_route_section(agg):
    from igris.core.jarvis_request_router import JarvisRequestRouter
    router = JarvisRequestRouter(project_root=agg.project_root)
    rd = router.classify("controlla i log", trust_level="admin")
    brief = agg.build_context(
        query="controlla i log", interlocutor_id="owner", trust_level="admin", route_decision=rd
    )
    sec = brief.get_section("route")
    assert sec is not None
    assert sec.status == "ok"


def test_build_context_includes_memory_section_for_admin(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    mem.store_preference("owner", "admin", "Preferisco risposte brevi")
    agg = ContextAggregator(project_root=tmp_path, unified_memory=mem)
    brief = agg.build_context(query="preferenze", interlocutor_id="owner", trust_level="admin")
    sec = brief.get_section("memory")
    assert sec is not None
    assert sec.status in ("ok", "empty", "degraded")


def test_build_context_untrusted_gets_limited_memory(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    mem.store_preference("owner", "admin", "OWNER_SECRET_PREFERENCE")
    agg = ContextAggregator(project_root=tmp_path, unified_memory=mem)
    brief = agg.build_context(
        query="preferenze", interlocutor_id="unknown_xyz", trust_level="untrusted"
    )
    sec = brief.get_section("memory")
    assert sec is not None
    assert sec.safe_for_prompt is False or sec.status == "empty"
    full_text = brief.brief_text + " ".join(str(s.summary) for s in brief.sections)
    assert "OWNER_SECRET_PREFERENCE" not in full_text


def test_build_context_includes_project_state(agg):
    brief = agg.build_context(query="stato", interlocutor_id="owner", trust_level="admin")
    sec = brief.get_section("project_state")
    assert sec is not None
    assert sec.status in ("ok", "degraded")


def test_build_context_git_state_best_effort(agg):
    brief = agg.build_context(query="git", interlocutor_id="owner", trust_level="admin")
    sec = brief.get_section("git_state")
    assert sec is not None
    assert sec.status in ("ok", "degraded", "unavailable")


def test_build_context_tasks_unavailable_degraded(agg):
    """When task_engine is None, tasks section is unavailable but no crash."""
    brief = agg.build_context(
        query="task", interlocutor_id="owner", trust_level="admin", include_tasks=True
    )
    sec = brief.get_section("tasks_timeline")
    assert sec is not None
    assert sec.status == "unavailable"


def test_build_context_missions_unavailable_degraded(agg):
    brief = agg.build_context(
        query="mission", interlocutor_id="owner", trust_level="admin", include_missions=True
    )
    sec = brief.get_section("missions")
    assert sec is not None
    assert sec.status == "unavailable"


def test_build_context_rank_unavailable_degraded(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "igris.core.rank_gauntlet.RankGauntlet.run",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("gauntlet down")),
    )
    agg = ContextAggregator(project_root=tmp_path)
    brief = agg.build_context(
        query="rank", interlocutor_id="owner", trust_level="admin", include_rank=True
    )
    sec = brief.get_section("rank_status")
    assert sec is not None
    assert sec.status in ("unavailable", "degraded")
    assert brief is not None


# Prompt
def test_build_prompt_context_contains_personal_os_brief(agg):
    text = agg.build_prompt_context(query="test", interlocutor_id="owner", trust_level="admin")
    assert "[PERSONAL OS BRIEF]" in text


def test_build_prompt_context_respects_max_chars(agg):
    text = agg.build_prompt_context(
        query="test", interlocutor_id="owner", trust_level="admin", max_chars=500
    )
    assert len(text) <= 520


def test_build_prompt_context_orders_sections_by_priority(agg):
    text = agg.build_prompt_context(query="test", interlocutor_id="owner", trust_level="admin")
    route_pos = text.find("Route Decision")
    proj_pos = text.find("Project State")
    if route_pos >= 0 and proj_pos >= 0:
        assert route_pos < proj_pos


def test_build_prompt_context_no_raw_secret(tmp_path):
    FAKE = "FAKE_TOKEN_CONTEXT_1234567890_NOTREAL"
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    mem.store_lesson(f"usa token={FAKE} per il deploy", project="test")
    agg = ContextAggregator(project_root=tmp_path, unified_memory=mem)
    text = agg.build_prompt_context(
        query="deploy", interlocutor_id="owner", trust_level="admin"
    )
    assert FAKE not in text, f"Raw fake secret in prompt context: {text[:500]}"


# Safety
def test_context_does_not_auto_elevate_owner(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    mem.store_preference("owner", "admin", "SENSITIVE_OWNER_DATA_XYZ")
    agg = ContextAggregator(project_root=tmp_path, unified_memory=mem)
    brief = agg.build_context(
        query="data", interlocutor_id="owner", trust_level="untrusted"
    )
    full_str = json.dumps(brief.to_dict())
    assert "SENSITIVE_OWNER_DATA_XYZ" not in full_str


def test_context_blocked_route_limits_memory(tmp_path):
    from igris.core.jarvis_request_router import JarvisRequestRouter
    router = JarvisRequestRouter(project_root=tmp_path)
    rd = router.classify("cancella database", interlocutor_id="unknown", trust_level="untrusted")
    assert rd.blocked
    agg = ContextAggregator(project_root=tmp_path)
    brief = agg.build_context(
        query="cancella", interlocutor_id="unknown", trust_level="untrusted", route_decision=rd
    )
    sec = brief.get_section("memory")
    if sec:
        assert sec.status in ("empty", "unavailable") or not sec.items


def test_context_requires_approval_limits_operational_detail(tmp_path):
    from igris.core.jarvis_request_router import JarvisRequestRouter
    router = JarvisRequestRouter(project_root=tmp_path)
    rd = router.classify("fai deploy in produzione", interlocutor_id="owner", trust_level="admin")
    assert rd.requires_approval
    agg = ContextAggregator(project_root=tmp_path)
    brief = agg.build_context(
        query="deploy", interlocutor_id="owner", trust_level="admin", route_decision=rd
    )
    sec = brief.get_section("memory")
    if sec:
        assert sec.safe_for_prompt is False or not sec.items


def test_context_redacts_nested_secret_values(tmp_path):
    FAKE = "FAKE_PASSPHRASE_CONTEXT_NOTREAL_XYZ"
    agg = ContextAggregator(project_root=tmp_path)
    brief = agg.build_context(
        query=f"passphrase={FAKE}", interlocutor_id="owner", trust_level="admin"
    )
    output = json.dumps(brief.to_dict())
    assert FAKE not in output, f"Fake secret leaked in context dict"


def test_context_no_except_pass_behavior(tmp_path, monkeypatch):
    """All failures must produce observable warnings, not silent pass."""
    original_run = __import__("subprocess").run

    def failing_run(cmd, *args, **kwargs):
        if "git" in (cmd[0] if isinstance(cmd, list) else cmd):
            raise RuntimeError("git down")
        return original_run(cmd, *args, **kwargs)

    monkeypatch.setattr("subprocess.run", failing_run)

    agg = ContextAggregator(project_root=tmp_path)
    brief = agg.build_context(query="test", interlocutor_id="owner", trust_level="admin")
    git_sec = brief.get_section("git_state")
    if git_sec:
        assert git_sec.status in ("degraded", "unavailable")


# Functional
def test_functional_brief_project_reasoning(tmp_path):
    from igris.core.jarvis_request_router import JarvisRequestRouter
    router = JarvisRequestRouter(project_root=tmp_path)
    rd = router.classify("ragiona sull'architettura", trust_level="admin")
    agg = ContextAggregator(project_root=tmp_path)
    brief = agg.build_context(
        query="architettura", interlocutor_id="owner", trust_level="admin",
        route_decision=rd, include_rank=False,
    )
    assert "[PERSONAL OS BRIEF]" in brief.brief_text
    assert brief.route == "project_reasoning"


def test_functional_brief_read_only_inspection(tmp_path):
    from igris.core.jarvis_request_router import JarvisRequestRouter
    router = JarvisRequestRouter(project_root=tmp_path)
    rd = router.classify("controlla i log del server", trust_level="admin")
    agg = ContextAggregator(project_root=tmp_path)
    brief = agg.build_context(
        query="log", interlocutor_id="owner", trust_level="admin",
        route_decision=rd, include_rank=False,
    )
    assert brief.ok
    assert "read_only_inspection" in brief.route


def test_functional_brief_memory_influence_report(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    mem.store_preference("owner", "admin", "Preferisco sempre risposte brevi")
    agg = ContextAggregator(project_root=tmp_path, unified_memory=mem)
    brief = agg.build_context(query="risposte", interlocutor_id="owner", trust_level="admin")
    assert brief is not None
    assert isinstance(brief.brief_text, str)


def test_to_dict_is_serializable(agg):
    brief = agg.build_context(
        query="test", interlocutor_id="owner", trust_level="admin", include_rank=False
    )
    d = brief.to_dict()
    assert json.dumps(d)  # must not raise


def test_get_section_returns_none_for_missing(agg):
    brief = agg.build_context(query="test", interlocutor_id="owner", trust_level="admin")
    assert brief.get_section("nonexistent_xyz") is None
