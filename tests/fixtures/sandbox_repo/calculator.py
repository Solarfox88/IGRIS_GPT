"""Simple calculator module — sandbox fixture for external repo benchmarks."""


def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    return a * b


def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


def percentage(value, total):
    """Calculate percentage of value relative to total."""
    return (value / total) * 100
