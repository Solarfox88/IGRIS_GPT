"""
Anti‑loop heuristics for preventing repetitive or runaway behaviour.

The anti‑loop module classifies tasks into broad families and keeps counts of
recent occurrences.  When a family is saturated (i.e. repeated too many
times) the agent should switch strategies or seek human intervention.
"""

from __future__ import annotations

from collections import Counter, deque
from typing import Deque, Iterable, List, Optional


def classify_task_family(text: str) -> str:
    """Classify a task into a simple family based on keywords.

    This is a very naive implementation; future versions might use an LLM
    classifier or a more sophisticated parser.  Families are coarse grained
    categories such as "test", "edit", "search", "plan".
    """
    lowered = text.lower()
    if any(keyword in lowered for keyword in ["test", "pytest", "unittest"]):
        return "testing"
    if any(keyword in lowered for keyword in ["fix", "edit", "modify", "refactor"]):
        return "editing"
    if any(keyword in lowered for keyword in ["search", "find", "grep"]):
        return "search"
    if any(keyword in lowered for keyword in ["write", "create", "generate"]):
        return "writing"
    return "other"


def compute_family_counts(tasks: Iterable[str], maxlen: int = 20) -> Counter:
    """Compute a counter of task families for the most recent tasks.

    :param tasks: An iterable of task descriptions (strings).
    :param maxlen: Only the last `maxlen` tasks are considered.
    :return: A Counter mapping family names to counts.
    """
    recent: Deque[str] = deque(tasks, maxlen=maxlen)
    counts: Counter = Counter(classify_task_family(t) for t in recent)
    return counts


def saturated_families(counts: Counter, threshold: int = 3) -> List[str]:
    """Return the list of families whose counts meet or exceed the threshold."""
    return [family for family, n in counts.items() if n >= threshold]


def should_force_strategy_shift(tasks: Iterable[str], threshold: int = 3) -> bool:
    """Determine whether the agent should shift strategies.

    Returns True if any task family is saturated beyond the given threshold.
    """
    counts = compute_family_counts(tasks)
    return bool(saturated_families(counts, threshold=threshold))


def is_observation_like(task: str) -> bool:
    """Return True if the task description appears to be observational.

    Observational tasks typically involve reading, inspecting or reporting
    on the current state (e.g. checking tests, reading logs, listing
    files).  This heuristic is intentionally broad and simply looks for
    keywords; future versions might use a classifier.
    """
    lowered = task.lower()
    return any(
        kw in lowered
        for kw in ["check", "inspect", "view", "read", "list", "show", "report"]
    )


def explain_saturation(tasks: Iterable[str], threshold: int = 3) -> str:
    """Produce a human‑readable explanation of which families are saturated.

    Returns a sentence listing saturated families and their counts.  If no
    family is saturated, returns an empty string.
    """
    counts = compute_family_counts(tasks)
    saturated = [f for f, n in counts.items() if n >= threshold]
    if not saturated:
        return ""
    parts = [f"{fam} ({counts[fam]})" for fam in saturated]
    return "Saturated families: " + ", ".join(parts)


def can_select_family(
    family: str,
    history: Iterable[str],
    differentiator: Optional[str] = None,
    threshold: int = 3,
) -> bool:
    """Check if a task family can be selected given recent history.

    :param family: The candidate family to select.
    :param history: Recent task descriptions.
    :param differentiator: Optional explanation of how this iteration is different.
    :param threshold: Saturation threshold.
    :returns: True if the family is not saturated or a differentiator is provided.
    """
    counts = compute_family_counts(history)
    saturated = saturated_families(counts, threshold=threshold)
    if family not in saturated:
        return True
    # If saturated but a differentiator is provided, allow selection
    return bool(differentiator)


def required_strategy_shift_family(
    current_family: str, history: Iterable[str], threshold: int = 3
) -> Optional[str]:
    """Determine which family should be used next when the current family is saturated.

    This is a naive heuristic: if the current family is saturated, recommend
    switching to a different family among the recent tasks (choose the
    least frequent one).  If all families are saturated or no tasks exist,
    return None.
    """
    counts = compute_family_counts(history)
    saturated = saturated_families(counts, threshold=threshold)
    if current_family not in saturated:
        return None
    # Choose the least frequent family among existing counts, excluding current
    alternatives = {fam: cnt for fam, cnt in counts.items() if fam != current_family}
    if not alternatives:
        return None
    # Sort by count ascending
    sorted_alts = sorted(alternatives.items(), key=lambda x: x[1])
    return sorted_alts[0][0]