def add(left, right):
    return left + right

def subtract(left, right):
    return left - right

def multiply(left,right):
    return left * right

def divide(left, right):
    if right == 0:
        raise ValueError("Cannot divide by zero")
    return left / right