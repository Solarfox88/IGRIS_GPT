"""Tests for Context Manager — Epic #60.

Validates token-budget-aware context building, file scoring,
history condensation, error summarization, and secret redaction.
"""

import pytest
from igris.core.context_manager import (
    ContextManager,
    ContextPacket,
    ScoredFile,
    TOKEN_BUDGETS,
    RESERVED_CHARS,
    MAX_RECENT_ACTIONS,
    MAX_RECENT_ERRORS,
    condense_actions,
    summarize_errors,
    score_file_relevance,
)


# ---------------------------------------------------------------------------
# ContextPacket
# ---------------------------------------------------------------------------

class TestContextPacket:
    """Test ContextPacket dataclass."""

    def test_empty_packet(self):
        p = ContextPacket()
        assert p.total_chars == 0
        assert p.role == "coder"

    def test_to_dict(self):
        p = ContextPacket(mission_context="test goal", role="tester")
        d = p.to_dict()
        assert d["mission_context"] == "test goal"
        assert d["role"] == "tester"
        assert isinstance(d["budget_chars"], int)

    def test_to_dict_redacts_secrets(self):
        fake_key = "sk-" + "a" * 30
        p = ContextPacket(mission_context=f"key is {fake_key}")
        d = p.to_dict()
        assert fake_key not in d["mission_context"]
        assert "REDACTED" in d["mission_context"]

    def test_total_chars_counts_all_sections(self):
        p = ContextPacket(
            mission_context="mission",
            state_context="state",
            file_context="files",
            recent_actions="actions",
            error_context="errors",
            memory_context="memory",
        )
        expected = len("mission") + len("state") + len("files") + len("actions") + len("errors") + len("memory")
        assert p.total_chars == expected


# ---------------------------------------------------------------------------
# ScoredFile
# ---------------------------------------------------------------------------

class TestScoredFile:
    """Test ScoredFile dataclass."""

    def test_to_dict(self):
        sf = ScoredFile(path="test.py", score=0.8, snippet="def hello():", reason="keyword")
        d = sf.to_dict()
        assert d["path"] == "test.py"
        assert d["score"] == 0.8

    def test_redacts_secrets_in_snippet(self):
        fake_key = "sk-" + "c" * 30
        sf = ScoredFile(path="test.py", score=0.5, snippet=f"KEY={fake_key}")
        d = sf.to_dict()
        assert fake_key not in d["snippet"]


# ---------------------------------------------------------------------------
# File relevance scoring
# ---------------------------------------------------------------------------

class TestFileRelevanceScoring:
    """Test file relevance scoring."""

    def test_keyword_match(self):
        score = score_file_relevance("igris/web/server.py", ["server"], [], [])
        assert score >= 0.3

    def test_recent_file_bonus(self):
        score = score_file_relevance("foo.py", [], ["foo.py"], [])
        assert score >= 0.2

    def test_error_file_bonus(self):
        score = score_file_relevance("broken.py", [], [], ["broken.py"])
        assert score >= 0.4

    def test_entry_point_bonus(self):
        score = score_file_relevance("igris/web/server.py", [], [], [])
        assert score >= 0.1

    def test_combined_scoring(self):
        score = score_file_relevance(
            "igris/web/server.py",
            ["server"],
            ["igris/web/server.py"],
            ["igris/web/server.py"],
        )
        assert score >= 0.9

    def test_score_capped_at_1(self):
        score = score_file_relevance(
            "server.py",
            ["server", "py", "ser"],
            ["server.py"],
            ["server.py"],
        )
        assert score <= 1.0

    def test_no_match(self):
        score = score_file_relevance("random.txt", [], [], [])
        assert score == 0.0

    def test_multiple_keywords(self):
        s1 = score_file_relevance("server.py", ["server"], [], [])
        s2 = score_file_relevance("server.py", ["server", "api"], [], [])
        assert s2 >= s1


# ---------------------------------------------------------------------------
# History condenser
# ---------------------------------------------------------------------------

class TestCondenseActions:
    """Test action history condensation."""

    def test_empty_actions(self):
        result = condense_actions([])
        assert result == "No recent actions."

    def test_few_actions_detailed(self):
        actions = [
            {"step": 1, "action_type": "search_code", "outcome": "success", "reason": "find server"},
            {"step": 2, "action_type": "read_file_range", "outcome": "success", "reason": "read routes"},
        ]
        result = condense_actions(actions)
        assert "search_code" in result
        assert "read_file_range" in result
        assert "find server" in result

    def test_many_actions_condensed(self):
        actions = [
            {"step": i, "action_type": "search_code", "outcome": "success"}
            for i in range(20)
        ]
        result = condense_actions(actions, max_items=5)
        assert "earlier actions summarized" in result
        assert "15" in result  # 20 - 5 = 15 earlier
        assert "search_code" in result

    def test_mixed_action_types(self):
        actions = [
            {"step": 1, "action_type": "search_code", "outcome": "success"},
            {"step": 2, "action_type": "read_file_range", "outcome": "success"},
            {"step": 3, "action_type": "write_file", "outcome": "success"},
        ]
        result = condense_actions(actions)
        assert "search_code" in result
        assert "read_file_range" in result
        assert "write_file" in result


# ---------------------------------------------------------------------------
# Error summarization
# ---------------------------------------------------------------------------

class TestSummarizeErrors:
    """Test error summarization."""

    def test_empty_errors(self):
        result = summarize_errors([])
        assert result == "No recent errors."

    def test_single_error(self):
        errors = [{"type": "test_failure", "message": "assert 1 == 2", "file": "test.py", "line": 10}]
        result = summarize_errors(errors)
        assert "test.py:10" in result
        assert "assert 1 == 2" in result

    def test_respects_max_items(self):
        errors = [{"type": "error", "message": f"err{i}"} for i in range(20)]
        result = summarize_errors(errors, max_items=3)
        lines = [l for l in result.split("\n") if l.strip()]
        assert len(lines) == 3

    def test_long_message_truncated(self):
        errors = [{"type": "error", "message": "x" * 500}]
        result = summarize_errors(errors)
        assert len(result) < 500

    def test_error_without_file(self):
        errors = [{"type": "runtime_error", "message": "something broke"}]
        result = summarize_errors(errors)
        assert "runtime_error" in result
        assert "something broke" in result


# ---------------------------------------------------------------------------
# ContextManager.build_context
# ---------------------------------------------------------------------------

class TestBuildContext:
    """Test context building."""

    def test_basic_build(self):
        ctx = ContextManager("/tmp")
        packet = ctx.build_context(goal="test goal", role="coder")
        assert isinstance(packet, ContextPacket)
        assert packet.role == "coder"
        assert "test goal" in packet.mission_context

    def test_with_mission_info(self):
        ctx = ContextManager("/tmp")
        packet = ctx.build_context(
            goal="Add /api/ping",
            mission_id="m-001",
            mission_status="executing",
        )
        assert "m-001" in packet.mission_context
        assert "executing" in packet.mission_context

    def test_with_errors(self):
        ctx = ContextManager("/tmp")
        packet = ctx.build_context(
            goal="fix test",
            recent_errors=[{"type": "test_failure", "message": "assert False"}],
        )
        assert "assert False" in packet.error_context

    def test_with_actions(self):
        ctx = ContextManager("/tmp")
        packet = ctx.build_context(
            goal="navigate",
            recent_actions=[
                {"step": 1, "action_type": "search_code", "outcome": "success"},
            ],
        )
        assert "search_code" in packet.recent_actions

    def test_with_memory(self):
        ctx = ContextManager("/tmp")
        packet = ctx.build_context(
            goal="fix bug",
            memory_items=[{"event_type": "lesson", "content": "always check imports"}],
        )
        assert "always check imports" in packet.memory_context

    def test_with_world_state(self):
        ctx = ContextManager("/tmp")
        packet = ctx.build_context(
            goal="check status",
            world_state={"repo_clean": True, "tests_pass": True},
        )
        assert "repo_clean" in packet.state_context

    def test_with_file_snippets(self):
        ctx = ContextManager("/tmp")
        packet = ctx.build_context(
            goal="edit server",
            file_snippets={"server.py": "def create_app():\n    pass"},
            keywords=["server"],
        )
        assert "server.py" in packet.file_context
        assert "create_app" in packet.file_context

    def test_empty_context_degrades(self):
        ctx = ContextManager("/tmp")
        packet = ctx.build_context()
        assert isinstance(packet, ContextPacket)
        assert packet.mission_context == "No active mission."
        assert packet.error_context == "No recent errors."

    def test_budget_respected(self):
        ctx = ContextManager("/tmp")
        packet = ctx.build_context(
            goal="test",
            profile="local_light",
        )
        assert packet.used_chars <= TOKEN_BUDGETS["local_light"]

    def test_large_content_truncated(self):
        ctx = ContextManager("/tmp")
        huge_snippets = {"big.py": "x" * 100000}
        packet = ctx.build_context(
            goal="test",
            profile="local_light",
            file_snippets=huge_snippets,
            keywords=["big"],
        )
        assert packet.used_chars <= TOKEN_BUDGETS["local_light"]
        assert len(packet.truncated_sections) > 0

    def test_build_time_tracked(self):
        ctx = ContextManager("/tmp")
        packet = ctx.build_context(goal="test")
        assert packet.build_time_ms >= 0

    def test_secret_redacted_in_output(self):
        fake_key = "sk-" + "d" * 30
        ctx = ContextManager("/tmp")
        packet = ctx.build_context(
            goal=f"use key {fake_key}",
        )
        d = packet.to_dict()
        assert fake_key not in d["mission_context"]


# ---------------------------------------------------------------------------
# Convenience methods
# ---------------------------------------------------------------------------

class TestConvenienceMethods:
    """Test convenience builder methods."""

    def test_build_for_navigation(self):
        ctx = ContextManager("/tmp")
        packet = ctx.build_context_for_navigation("find server routes")
        assert packet.role == "researcher"
        assert "find server routes" in packet.mission_context

    def test_build_for_coding(self):
        ctx = ContextManager("/tmp")
        packet = ctx.build_context_for_coding(
            "add endpoint",
            file_snippets={"server.py": "app = FastAPI()"},
        )
        assert packet.role == "coder"
        assert "add endpoint" in packet.mission_context

    def test_build_for_testing(self):
        ctx = ContextManager("/tmp")
        packet = ctx.build_context_for_testing(
            "run tests",
            test_output="FAILED test_main.py::test_1 - assert False",
        )
        assert packet.role == "tester"
        assert "FAILED" in packet.error_context


# ---------------------------------------------------------------------------
# Budget info
# ---------------------------------------------------------------------------

class TestBudgetInfo:
    """Test budget information."""

    def test_known_profile(self):
        ctx = ContextManager("/tmp")
        info = ctx.get_budget_info("local_light")
        assert info["profile"] == "local_light"
        assert info["total_budget_chars"] == TOKEN_BUDGETS["local_light"]
        assert info["approximate_tokens"] == TOKEN_BUDGETS["local_light"] // 4

    def test_default_profile(self):
        ctx = ContextManager("/tmp")
        info = ctx.get_budget_info("nonexistent_profile")
        assert info["total_budget_chars"] == TOKEN_BUDGETS["default"]

    def test_all_profiles_have_budgets(self):
        for profile in TOKEN_BUDGETS:
            ctx = ContextManager("/tmp")
            info = ctx.get_budget_info(profile)
            assert info["available_chars"] == info["total_budget_chars"] - RESERVED_CHARS
