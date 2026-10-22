"""Always-available tools: they touch nothing outside the program."""
import ast
import operator
from datetime import datetime

from ..tools import tool

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _eval(node):
    # Walk the parsed expression ourselves instead of eval(): eval would run any Python code.
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("Exponent too large.")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("Only numbers and + - * / // % ** ( ) are allowed.")


@tool(safety="Only numbers and + - * / // % ** ( ). It can't run code.", example='223.2')
def calculator(expression: str):
    """Evaluate a math expression and return the exact result.

    Args:
        expression: The math expression, e.g. "(1200 * 0.18) + 45"
    """
    return _eval(ast.parse(expression, mode="eval").body)


@tool(safety='Reads the clock only.', example='Thursday, 22 October 2026, 15:51')
def current_datetime():
    """Get the current local date and time."""
    return datetime.now().strftime("%A, %d %B %Y, %H:%M")
