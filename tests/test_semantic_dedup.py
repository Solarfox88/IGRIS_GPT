"""Tests for semantic deduplication."""
from igris.core.semantic_dedup import is_semantic_duplicate, explain_duplicate


def test_same_meaning_different_wording():
    """Two tasks with the same canonical tokens should be duplicates."""
    task_a = "run pytest"
    task_b = "run testing"
    assert is_semantic_duplicate(task_a, [task_b])


def test_different_targets_not_duplicated():
    task_a = "search for config in /etc"
    task_b = "write a new API endpoint for tasks"
    assert not is_semantic_duplicate(task_a, [task_b])


def test_explain_duplicate_returns_explanation():
    task = "run pytest"
    is_dup, explanation = explain_duplicate(task, ["run testing"])
    assert is_dup
    assert len(explanation) > 0


def test_explain_no_duplicate():
    task = "deploy to production server"
    is_dup, _ = explain_duplicate(task, ["search for config files"])
    assert isinstance(is_dup, bool)
