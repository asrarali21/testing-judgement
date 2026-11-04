def add(left, right):
    return left + right

def subtract(left, right):
    return left - right

def multiply(left,right):
    return left * right

def power(base, exponent):
    return base ** exponent

def average(values):
    """Calculate the arithmetic mean of numeric values.
    Args:
        values: A non-empty sequence of numbers.
    Returns:
        The arithmetic mean as a float.
    Raises:
        ValueError: If values is empty.
    """
    items = list(values)
    if not items:
        raise ValueError("values must not be empty")
    return sum(items) / len(items)

def modulo(left, right):
    if right == 0:
        raise ValueError("Cannot divide by zero")
    return left % right

def percentage(part, whole):
    if whole == 0:
        raise ValueError("whole must not be zero")
    return (part / whole) * 100