"""A tiny module with a real bug for the agent to find and fix."""


def divide(a, b):
    if b == 0:
        raise ValueError("Division by zero is not allowed")
    return a / b


def add(a, b):
    return a + b


def subtract(a, b):
    return a - b
