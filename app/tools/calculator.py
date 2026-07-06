"""A safe arithmetic calculator tool.

Evaluates a math expression by walking a parsed AST and permitting only numeric
literals and arithmetic operators — never ``eval`` on raw input. Demonstrates the
tool contract end-to-end and gives the planner something concrete to route to.
"""

from __future__ import annotations

import ast
import operator
from typing import Any

from app.core.exceptions import ToolError
from app.tools.base import Tool, ToolResult

_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_ALLOWED_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        return _ALLOWED_UNARY[type(node.op)](_eval(node.operand))
    raise ToolError("expression contains a disallowed operation")


class CalculatorTool(Tool):
    """Evaluate a safe arithmetic expression, e.g. ``(2 + 3) * 4``."""

    name = "calculator"
    description = "Вычисляет арифметическое выражение (+, -, *, /, //, %, **)."
    parameters = {
        "type": "object",
        "properties": {"expression": {"type": "string", "description": "Арифметическое выражение"}},
        "required": ["expression"],
    }

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        expression = str(arguments["expression"])
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise ToolError(f"invalid expression: {exc.msg}") from exc
        value = _eval(tree)
        rendered = f"{value:g}"
        return ToolResult(
            tool=self.name, ok=True, output=f"{expression} = {rendered}", data={"value": value}
        )
