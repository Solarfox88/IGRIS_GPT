"""
Semantic deduplication utilities.

This module provides simple heuristics for detecting when two task
descriptions are semantically equivalent.  It operates on plain
strings and does not require any external dependencies or heavy
machine‑learning models.  The goal is to avoid repeating essentially
the same task multiple times by normalising and comparing
signatures.

The implementation here is intentionally conservative; it is meant
to serve as an MVP that can later be replaced with more advanced
similarity measures (e.g. embeddings).  In particular, it uses
lowercase normalisation, a small set of stopwords in English/Italian,
and keyword canonicalisation for common agentic activities.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Set, Tuple


# Basic stopwords in English and Italian.  This list is intentionally
# small to reduce false positives and avoid removing useful tokens.
_STOPWORDS: Set[str] = {
    "the", "a", "an", "and", "or", "di", "il", "la", "le", "lo", "gli", "dei",
    "delle", "del", "della", "un", "una", "uno", "che", "to", "da", "per",
}

# Keyword canonicalisation map.  Maps various synonyms to a canonical
# term so that e.g. "test", "testing" and "pytest" are considered
# equivalent at the signature level.  Similarly for other families.
_CANONICAL_KEYWORDS: List[Tuple[Set[str], str]] = [
    ({"test", "testing", "pytest", "unittest"}, "test"),
    ({"fix", "edit", "modify", "refactor"}, "edit"),
    ({"search", "find", "grep", "ricerca"}, "search"),
    ({"write", "create", "generate", "scrivi", "scrivere"}, "write"),
    ({"plan", "design", "project"}, "plan"),
]


def normalize_text(text: str) -> str:
    """Normalise a string for comparison.

    Converts to lowercase and removes punctuation.  Does not remove
    accents.  Returns a single whitespace separated string.
    """
    # Lowercase
    lowered = text.lower()
    # Replace non‑word characters with spaces
    cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", lowered)
    # Collapse multiple spaces
    collapsed = re.sub(r"\s+", " ", cleaned).strip()
    return collapsed


def _canonicalise_token(token: str) -> str:
    """Canonicalise a single token using the predefined keyword map.

    Returns the canonical form if a match is found, otherwise the
    original token.
    """
    for synonyms, canon in _CANONICAL_KEYWORDS:
        if token in synonyms:
            return canon
    return token


def extract_task_signature(text: str) -> Set[str]:
    """Extract a set of canonical tokens from a task description.

    Normalises the text, splits it into tokens, removes stopwords and
    canonicalises known keywords.  Returns a set of unique tokens.
    """
    normalized = normalize_text(text)
    tokens = normalized.split()
    signature: Set[str] = set()
    for token in tokens:
        if token in _STOPWORDS:
            continue
        signature.add(_canonicalise_token(token))
    return signature


def semantic_fingerprint(text: str, family: str = "") -> str:
    """Generate a simple semantic fingerprint for a task.

    The fingerprint is a sorted, hyphen‑joined string of the task's
    canonical signature tokens, optionally prefixed by the family name.
    """
    sig = extract_task_signature(text)
    parts = sorted(sig)
    if family:
        return f"{family}:" + "-".join(parts)
    return "-".join(parts)


def is_semantic_duplicate(task: str, recent_tasks: Iterable[str], threshold: float = 0.7) -> bool:
    """Determine if a task is semantically a duplicate of a recent one.

    Compares the signature of the given task to the signatures of
    recent tasks.  Returns True if there exists a recent task whose
    signature has Jaccard similarity >= threshold.  Uses a simple
    Jaccard index (intersection/union) between the two token sets.

    :param task: The task description to check.
    :param recent_tasks: An iterable of recent task descriptions.
    :param threshold: The Jaccard similarity threshold to treat as a duplicate.
    :returns: True if a duplicate is found, otherwise False.
    """
    sig_a = extract_task_signature(task)
    if not sig_a:
        return False
    for other in recent_tasks:
        sig_b = extract_task_signature(other)
        if not sig_b:
            continue
        intersection = sig_a.intersection(sig_b)
        union = sig_a.union(sig_b)
        # Avoid division by zero
        if not union:
            continue
        similarity = len(intersection) / len(union)
        if similarity >= threshold:
            return True
    return False


def explain_duplicate(task: str, recent_tasks: Iterable[str]) -> Tuple[bool, str]:
    """Explain which recent task this one duplicates and why.

    Returns a tuple (is_duplicate, explanation).  If no duplicate is
    found the explanation is an empty string.
    """
    sig_a = extract_task_signature(task)
    best_similarity = 0.0
    best_match: str = ""
    for other in recent_tasks:
        sig_b = extract_task_signature(other)
        if not sig_b:
            continue
        intersection = sig_a.intersection(sig_b)
        union = sig_a.union(sig_b)
        if not union:
            continue
        similarity = len(intersection) / len(union)
        if similarity > best_similarity:
            best_similarity = similarity
            best_match = other
    if best_similarity >= 0.7 and best_match:
        return True, f"Task '{task}' is similar to previous task '{best_match}' (similarity {best_similarity:.2f})."
    return False, ""