"""Tests for IGRIS-aware chat personality and capability grounding.

Sprint 31 — v0.6: Chat must reflect IGRIS identity, not generic ChatGPT.
"""

import pytest

from igris.core.chat_personality import (
    IGRIS_SYSTEM_PROMPT,
    CAPABILITIES,
    detect_intent,
    get_grounded_response,
    get_capability_summary,
    enrich_chat_response,
)


# ---------------------------------------------------------------------------
# Identity / System Prompt
# ---------------------------------------------------------------------------

class TestIGRISSystemPrompt:
    """IGRIS system prompt is well-formed and identity-aware."""

    def test_prompt_mentions_igris(self):
        assert "IGRIS_GPT" in IGRIS_SYSTEM_PROMPT

    def test_prompt_no_free_shell(self):
        assert "shell libera" in IGRIS_SYSTEM_PROMPT or "no free shell" in IGRIS_SYSTEM_PROMPT.lower()

    def test_prompt_mentions_safety(self):
        assert "sicur" in IGRIS_SYSTEM_PROMPT.lower() or "safety" in IGRIS_SYSTEM_PROMPT.lower()

    def test_prompt_mentions_approval_gates(self):
        assert "approval" in IGRIS_SYSTEM_PROMPT.lower() or "approv" in IGRIS_SYSTEM_PROMPT.lower()

    def test_prompt_no_secrets(self):
        # Must not contain actual tokens/secrets
        assert "ghp_" not in IGRIS_SYSTEM_PROMPT
        assert "sk-" not in IGRIS_SYSTEM_PROMPT
        assert "password" not in IGRIS_SYSTEM_PROMPT.lower() or "non esporre" in IGRIS_SYSTEM_PROMPT.lower()

    def test_prompt_bounded_length(self):
        # System prompt should be concise (< 3000 chars)
        assert len(IGRIS_SYSTEM_PROMPT) < 3000


# ---------------------------------------------------------------------------
# Intent Detection
# ---------------------------------------------------------------------------

class TestIntentDetection:
    """Intent detection correctly identifies operational intents."""

    def test_machine_info_italian(self):
        assert detect_intent("dammi info sulla macchina") == "machine_info"

    def test_machine_info_english(self):
        assert detect_intent("show me machine info") == "machine_info"

    def test_machine_info_cpu(self):
        assert detect_intent("quanta RAM ha il server?") == "machine_info"

    def test_network_info(self):
        assert detect_intent("dammi info sulla rete del tuo host") == "network_info"

    def test_network_info_port(self):
        assert detect_intent("su che porta è in ascolto?") == "network_info"

    def test_github_access(self):
        assert detect_intent("riesci a vedere il mio GitHub?") == "github_access"

    def test_github_push(self):
        assert detect_intent("puoi fare push?") == "github_access"

    def test_github_pr(self):
        assert detect_intent("crea una pull request") == "github_access"

    def test_capabilities_italian(self):
        assert detect_intent("cosa puoi fare?") == "capabilities"

    def test_capabilities_english(self):
        assert detect_intent("what can you do?") == "capabilities"

    def test_capabilities_help(self):
        assert detect_intent("help me understand your capabilities") == "capabilities"

    def test_testing_intent(self):
        assert detect_intent("esegui i test") == "testing"

    def test_git_local_intent(self):
        assert detect_intent("mostrami git status") == "git_local"

    def test_patching_intent(self):
        assert detect_intent("crea una patch per questo bug") == "patching"

    def test_missions_intent(self):
        assert detect_intent("crea una missione per refactoring") == "missions"

    def test_memory_intent(self):
        assert detect_intent("mostrami i fallimenti recenti") == "memory"

    def test_shell_request_intent(self):
        assert detect_intent("esegui un comando bash") == "shell_request"

    def test_unknown_intent(self):
        assert detect_intent("ciao come stai?") is None

    def test_generic_question(self):
        assert detect_intent("qual è la capitale della Francia?") is None


# ---------------------------------------------------------------------------
# Grounded Responses
# ---------------------------------------------------------------------------

class TestGroundedResponses:
    """Grounded responses are IGRIS-aware and safe."""

    def test_machine_info_no_shell(self):
        resp = get_grounded_response("machine_info")
        assert resp is not None
        assert "shell" not in resp or "Non uso shell libera" in resp
        assert "/api/status" in resp

    def test_machine_info_mentions_safe_endpoints(self):
        resp = get_grounded_response("machine_info")
        assert "/api/readiness" in resp
        assert "command_id" in resp

    def test_network_info_conservative(self):
        resp = get_grounded_response("network_info")
        assert resp is not None
        assert "IP privati" in resp or "sicurezza" in resp.lower()
        assert "/api/status" in resp

    def test_github_mentions_approval(self):
        resp = get_grounded_response("github_access")
        assert resp is not None
        assert "I_APPROVE_GITHUB_WRITE" in resp
        assert "push/merge automatici" in resp or "Non posso" in resp

    def test_github_mentions_gated_workflow(self):
        resp = get_grounded_response("github_access")
        assert "gated" in resp.lower() or "approval" in resp.lower()

    def test_capabilities_structured(self):
        resp = get_grounded_response("capabilities")
        assert resp is not None
        assert "IGRIS_GPT" in resp
        assert "Missioni" in resp
        assert "Task" in resp
        assert "Patch" in resp
        assert "Git" in resp

    def test_capabilities_no_unrestricted_claim(self):
        resp = get_grounded_response("capabilities")
        assert "unlimited" not in resp.lower()
        assert "unrestricted" not in resp.lower()
        assert "qualsiasi" not in resp.lower()

    def test_shell_request_denied_safely(self):
        resp = get_grounded_response("shell_request")
        assert resp is not None
        assert "sicurezza" in resp.lower() or "sicur" in resp.lower()
        assert "command_id" in resp
        # Should offer alternatives, not just refuse
        assert "Alternative" in resp or "alternative" in resp.lower()

    def test_testing_response_mentions_command_id(self):
        resp = get_grounded_response("testing")
        assert resp is not None
        assert "run_tests" in resp

    def test_all_responses_bounded(self):
        """All grounded responses must be < 1500 chars."""
        for intent in ["machine_info", "network_info", "github_access",
                       "capabilities", "testing", "git_local", "patching",
                       "missions", "memory", "shell_request"]:
            resp = get_grounded_response(intent)
            assert resp is not None, f"No response for intent: {intent}"
            assert len(resp) < 1500, f"Response for {intent} is too long: {len(resp)}"

    def test_no_secrets_in_responses(self):
        """No responses should contain secret patterns."""
        for intent in ["machine_info", "network_info", "github_access",
                       "capabilities", "testing", "git_local", "patching",
                       "missions", "memory", "shell_request"]:
            resp = get_grounded_response(intent)
            assert "ghp_" not in resp
            assert "sk-" not in resp
            assert "password" not in resp.lower() or "non esporre" in resp.lower()

    def test_none_for_unknown_intent(self):
        assert get_grounded_response("nonexistent_intent") is None


# ---------------------------------------------------------------------------
# Capability Summary
# ---------------------------------------------------------------------------

class TestCapabilitySummary:
    """Capability summary is structured and complete."""

    def test_summary_has_identity(self):
        summary = get_capability_summary()
        assert "identity" in summary
        assert "IGRIS" in summary["identity"]

    def test_summary_has_capabilities(self):
        summary = get_capability_summary()
        assert "capabilities" in summary
        assert len(summary["capabilities"]) > 5

    def test_summary_has_safety(self):
        summary = get_capability_summary()
        assert "safety" in summary
        assert summary["safety"]["no_free_shell"] is True
        assert summary["safety"]["no_auto_merge"] is True

    def test_capabilities_have_labels(self):
        for key, cap in CAPABILITIES.items():
            assert "label" in cap, f"Capability {key} missing label"
            assert "description" in cap, f"Capability {key} missing description"
            assert "safe" in cap, f"Capability {key} missing safe flag"

    def test_gated_capabilities_have_approval(self):
        for key, cap in CAPABILITIES.items():
            if "gated" in key.lower() or "gated" in cap.get("label", "").lower():
                assert "approval_required" in cap, \
                    f"Gated capability {key} missing approval_required"


# ---------------------------------------------------------------------------
# Enrich Response
# ---------------------------------------------------------------------------

class TestEnrichResponse:
    """Enrich chat response integrates personality correctly."""

    def test_enriches_known_intent(self):
        result = enrich_chat_response("dammi info sulla macchina", "generic answer")
        assert "/api/status" in result
        assert "generic answer" not in result

    def test_passes_through_unknown(self):
        result = enrich_chat_response("ciao come stai?", "I'm fine, thanks!")
        assert result == "I'm fine, thanks!"

    def test_github_enrichment(self):
        result = enrich_chat_response("riesci a vedere il mio GitHub?", "no")
        assert "I_APPROVE_GITHUB_WRITE" in result
