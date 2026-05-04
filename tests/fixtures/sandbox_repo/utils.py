"""Utility helpers — sandbox fixture for multi-file benchmark."""


def format_result(operation, a, b, result):
    """Format a calculation result as a string."""
    return f"{a} {operation} {b} = {result}"


def validate_number(value):
    """Validate that value is a number."""
    if not isinstance(value, (int, float)):
        raise TypeError(f"Expected number, got {type(value).__name__}")
    return value
