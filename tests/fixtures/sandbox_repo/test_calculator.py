"""Tests for calculator module — sandbox fixture."""

from calculator import add, subtract, multiply, divide, percentage


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
