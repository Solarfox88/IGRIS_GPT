"""
Provider routing logic.

The router determines which language model provider to use based on availability
and cost.  It uses the configuration to decide between the local provider
(Ollama), a fallback provider (OpenAI) or (in the future) Vast.ai.  The
`explain_routing` function returns a human‑readable explanation for the last
decision.
"""

from __future__ import annotations

from typing import List, Optional, Tuple, Dict, Any

from igris.models.config import CONFIG


class Provider(str):
    LOCAL = "local"
    FALLBACK = "fallback"
    VASTAI = "vastai"


_last_provider: Optional[Tuple[str, str]] = None
# Maintain a history of provider decisions for cost/routing summary.
# Each entry is a dict with provider, model and reason fields.
_provider_history: List[Dict[str, Any]] = []


def choose_provider(for_task: str = "chat") -> Tuple[str, str]:
    """Return the name and model of the chosen provider and record the choice.

    Currently the logic is simplistic: always use the local provider.  If the
    fallback API key is missing the fallback provider will not be chosen.
    This function records the last choice for reporting in both `_last_provider` and
    `_provider_history`.  In future versions this logic can consider factors
    such as task complexity, model capabilities, latency and cost budgets.
    """
    global _last_provider, _provider_history
    # Determine provider; default to local
    provider = Provider.LOCAL
    model = CONFIG.local_llm.model
    reason = "Using local provider because it is low cost and sufficient for the task."
    # TODO: add logic for fallback or vastai here based on CONFIG and availability
    _last_provider = (provider, model)
    # Record history entry
    _provider_history.append({
        "provider": provider,
        "model": model,
        "reason": reason,
    })
    return _last_provider


def explain_routing() -> str:
    """Explain why the last provider was chosen."""
    if _last_provider is None:
        return "No provider has been chosen yet.  Messages have not been sent."
    provider, model = _last_provider
    if provider == Provider.LOCAL:
        return (
            f"Using local provider {CONFIG.local_llm.provider} with model {model} because it is low cost and sufficient for the task."
        )
    elif provider == Provider.FALLBACK:
        return (
            f"Using fallback provider {CONFIG.fallback_llm.provider} with model {model} because the local model was unable to answer."
        )
    elif provider == Provider.VASTAI:
        return (
            f"Using Vast.ai instance with model {model} due to high compute requirements."
        )
    return "Unknown provider choice."


def get_history() -> List[Dict[str, Any]]:
    """Return a copy of the provider history.

    Each entry in the history is a dict with keys: provider, model and reason.
    """
    return list(_provider_history)


def cost_summary() -> Dict[str, Any]:
    """Return a simple summary of provider usage.

    The summary includes the count of calls per provider, the last provider used,
    and a total call count.  It does not include actual costs because these
    depend on external pricing which is not available to the agent.
    """
    summary = {
        "total_calls": len(_provider_history),
        "providers": {},
        "last_provider": _last_provider[0] if _last_provider else None,
    }
    for entry in _provider_history:
        provider = entry["provider"]
        summary["providers"].setdefault(provider, 0)
        summary["providers"][provider] += 1
    return summary