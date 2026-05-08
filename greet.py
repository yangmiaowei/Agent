def greet(name: str) -> str:
    """Return a greeting message for the given name.

    Args:
        name: The name of the person to greet.

    Returns:
        A greeting string in the form ``"Hello, {name}!"``.
    """
    return f"Hello, {name}!"


if __name__ == "__main__":
    print(greet("World"))
