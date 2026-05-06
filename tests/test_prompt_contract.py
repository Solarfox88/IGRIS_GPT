"""Tests for Prompt Contract — Epic #58.

Validates the system prompt template and few-shot examples.
"""

import json
import pytest

from igris.core.prompt_contract import (
    REASONING_LOOP_SYSTEM_PROMPT,
    ACTION_TYPE_DOCS,
    EXAMPLE_SCENARIOS,
    build_reasoning_prompt,
    get_example_scenarios,
)
from igris.core.agent_action_schema import (
    ACTION_TYPES,
    AGENT_ROLES,
    AGENT_REGISTRY,
    AgentAction,
    validate_action,
)


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

class TestPromptTemplate:
    """Test the reasoning loop prompt template."""

    def test_prompt_has_placeholders(self):
        assert "{role}" in REASONING_LOOP_SYSTEM_PROMPT
        assert "{role_description}" in REASONING_LOOP_SYSTEM_PROMPT
        assert "{action_types_doc}" in REASONING_LOOP_SYSTEM_PROMPT
        assert "{mission_context}" in REASONING_LOOP_SYSTEM_PROMPT
        assert "{state_context}" in REASONING_LOOP_SYSTEM_PROMPT
        assert "{recent_actions}" in REASONING_LOOP_SYSTEM_PROMPT
        assert "{file_context}" in REASONING_LOOP_SYSTEM_PROMPT

    def test_prompt_contains_safety_rules(self):
        assert "NEVER include secrets" in REASONING_LOOP_SYSTEM_PROMPT
        assert "NEVER propose actions that read .env" in REASONING_LOOP_SYSTEM_PROMPT
        assert "raw_shell_proposal" in REASONING_LOOP_SYSTEM_PROMPT

    def test_prompt_specifies_json_only(self):
        assert "valid JSON only" in REASONING_LOOP_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# build_reasoning_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    """Test prompt building function."""

    def test_build_for_coder(self):
        prompt = build_reasoning_prompt(role="coder")
        assert "coder" in prompt
        assert "write_file" in prompt
        assert "propose_patch" in prompt

    def test_build_for_researcher(self):
        prompt = build_reasoning_prompt(role="researcher")
        assert "researcher" in prompt
        assert "search_code" in prompt
        # researcher should not have write_file
        assert "write_file: NOT AVAILABLE" in prompt

    def test_build_for_security_guard(self):
        prompt = build_reasoning_prompt(role="security_guard")
        assert "security_guard" in prompt
        assert "raw_shell_proposal: NOT AVAILABLE" in prompt

    def test_build_with_context(self):
        prompt = build_reasoning_prompt(
            role="coder",
            mission_context="Add /api/ping endpoint",
            state_context="repo_clean: true",
            recent_actions="Step 1: read server.py → success",
            file_context="server.py: FastAPI app with routes...",
        )
        assert "Add /api/ping endpoint" in prompt
        assert "repo_clean: true" in prompt
        assert "read server.py" in prompt
        assert "FastAPI app" in prompt

    def test_all_roles_produce_valid_prompt(self):
        for role in AGENT_ROLES:
            prompt = build_reasoning_prompt(role=role)
            assert len(prompt) > 100
            assert role in prompt

    def test_unknown_role_still_works(self):
        prompt = build_reasoning_prompt(role="unknown_role")
        assert "General-purpose agent" in prompt


# ---------------------------------------------------------------------------
# Action type documentation
# ---------------------------------------------------------------------------

class TestActionTypeDocs:
    """Test action type documentation for the prompt."""

    def test_all_action_types_documented(self):
        for at in ACTION_TYPES:
            assert at in ACTION_TYPE_DOCS, f"No documentation for {at}"

    def test_docs_are_strings(self):
        for at, doc in ACTION_TYPE_DOCS.items():
            assert isinstance(doc, str)
            assert len(doc) > 10

    def test_docs_mention_params(self):
        assert "pattern" in ACTION_TYPE_DOCS["search_code"]
        assert "path" in ACTION_TYPE_DOCS["read_file_range"]
        assert "url" in ACTION_TYPE_DOCS["http_check"]
        assert "summary" in ACTION_TYPE_DOCS["finish"]


# ---------------------------------------------------------------------------
# Example scenarios
# ---------------------------------------------------------------------------

class TestExampleScenarios:
    """Test the few-shot example scenarios."""

    def test_at_least_10_examples(self):
        examples = get_example_scenarios()
        assert len(examples) >= 10

    def test_examples_have_required_fields(self):
        for ex in EXAMPLE_SCENARIOS:
            assert "scenario" in ex
            assert "goal" in ex
            assert "action" in ex
            action = ex["action"]
            assert "mode" in action
            assert "action_type" in action
            assert "reason" in action
            assert "parameters" in action

    def test_all_example_actions_validate(self):
        """Every example action must pass schema validation."""
        for ex in EXAMPLE_SCENARIOS:
            action = AgentAction.from_dict(ex["action"])
            result = validate_action(action)
            assert result.valid is True, (
                f"Example '{ex['scenario']}' failed validation: {result.errors}"
            )

    def test_examples_cover_diverse_action_types(self):
        types = {ex["action"]["action_type"] for ex in EXAMPLE_SCENARIOS}
        # Should cover at least navigation, modification, test, shell, terminal
        assert "read_file_range" in types
        assert "search_code" in types
        assert "write_file" in types
        assert "run_tests" in types
        assert "finish" in types
        assert "blocked" in types
        assert "ask_user" in types

    def test_examples_cover_diverse_roles(self):
        roles = {ex["action"]["mode"] for ex in EXAMPLE_SCENARIOS}
        assert len(roles) >= 5

    def test_example_json_serializable(self):
        """All examples must be JSON-serializable."""
        for ex in EXAMPLE_SCENARIOS:
            serialized = json.dumps(ex)
            assert isinstance(serialized, str)


# ---------------------------------------------------------------------------
# Integration: prompt + schema
# ---------------------------------------------------------------------------

class TestPromptSchemaIntegration:
    """Test that prompt and schema work together."""

    def test_prompt_mentions_all_action_types_for_coordinator(self):
        prompt = build_reasoning_prompt(role="coordinator")
        for at in ACTION_TYPES:
            assert at in prompt

    def test_prompt_limits_actions_for_restricted_roles(self):
        prompt = build_reasoning_prompt(role="planner")
        assert "write_file: NOT AVAILABLE" in prompt
        assert "raw_shell_proposal: NOT AVAILABLE" in prompt
