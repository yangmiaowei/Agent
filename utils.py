"""
Utility functions for the package.
"""


def greet(name: str) -> str:
    """
    Return a greeting message.

    Args:
        name: The name to greet.

    Returns:
        A greeting string.
    """
    return f"Hello, {name}!"


def add(a: int | float, b: int | float) -> int | float:
    """
    Add two numbers.

    Args:
        a: First number.
        b: Second number.

    Returns:
        The sum of a and b.
    """
    return a + b


def multiply(a: int | float, b: int | float) -> int | float:
    """
    Multiply two numbers.

    Args:
        a: First number.
        b: Second number.

    Returns:
        The product of a and b.
    """
    return a * b
