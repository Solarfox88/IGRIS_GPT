"""Tests for calculator module — sandbox fixture."""

from calculator import (
    add,
    subtract,
    multiply,
    divide,
    percentage,
    clear_history,
    get_history,
)


def test_add():
    assert add(2, 3) == 5


def test_subtract():
    assert subtract(5, 3) == 2


def test_multiply():
    assert multiply(3, 4) == 12


def test_divide():
    assert divide(10, 2) == 5.0


def test_divide_by_zero():
    """This test will fail — the bug to fix."""
    try:
        divide(10, 0)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_percentage():
    assert percentage(25, 100) == 25.0


def test_percentage_by_zero():
    """Percentage over zero total should raise a clear ValueError."""
    try:
        percentage(25, 0)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_history_records_operations():
    clear_history()

    assert add(1, 2) == 3
    assert subtract(5, 1) == 4
    assert multiply(2, 3) == 6
    assert divide(8, 2) == 4.0
    assert percentage(10, 20) == 50.0

    assert get_history() == [
        ("add", 1, 2, 3),
        ("subtract", 5, 1, 4),
        ("multiply", 2, 3, 6),
        ("divide", 8, 2, 4.0),
        ("percentage", 10, 20, 50.0),
    ]
