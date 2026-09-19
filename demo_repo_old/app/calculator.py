"""A tiny module with a real bug for the agent to find and fix."""


def divide(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        raise ValueError("b must not be zero") from None


def add(a, b):
    return a + b


def subtract(a, b):
    return a - b
