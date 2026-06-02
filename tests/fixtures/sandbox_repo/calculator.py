"""Simple calculator module — sandbox fixture for external repo benchmarks."""

_HISTORY = []


def _record(operation, a, b, result):
    _HISTORY.append((operation, a, b, result))
    return result


def clear_history():
    _HISTORY.clear()


def get_history():
    return list(_HISTORY)


def add(a, b):
    return _record("add", a, b, a + b)


def subtract(a, b):
    return _record("subtract", a, b, a - b)


def multiply(a, b):
    return _record("multiply", a, b, a * b)


def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return _record("divide", a, b, a / b)


def percentage(value, total):
    """Calculate percentage of value relative to total."""
    if total == 0:
        raise ValueError("Cannot calculate percentage with total=0")
    return _record("percentage", value, total, (value / total) * 100)
