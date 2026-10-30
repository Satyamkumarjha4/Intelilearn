"""Computes the answer of a numerical question from the expression a model wrote (`sqrt(3) / 2 * 10`).

The expression is text from a model that read text a learner supplied, so it is parsed with `ast` and walked by this
class only: numbers, `+ - * / **`, unary minus and plus, parentheses, a short list of functions and two constants.
Nothing is ever passed to `eval`, `exec` or a symbolic library's parser. Length, nesting, exponents and results are
bounded, so a hostile or silly expression ends in an error, not in a stuck worker.
"""

import ast
import math
from typing import Any, ClassVar


class ExpressionError(ValueError):
    """The expression is not allowed or cannot be computed. The message says why, in words a generator can act on."""


class ExpressionEvaluator:
    MAX_CHARS = 200
    MAX_DEPTH = 20  # of the syntax tree, and of nested parentheses
    MAX_EXPONENT = 1000

    #: radians for the trigonometric functions; `log` is base 10, `ln` is natural
    FUNCTIONS: ClassVar[dict[str, Any]] = {
        "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos,
        "atan": math.atan, "log": math.log10, "ln": math.log, "exp": math.exp, "abs": abs,
    }  # fmt: skip
    CONSTANTS: ClassVar[dict[str, float]] = {"pi": math.pi, "e": math.e}

    def evaluate(self, expression: Any) -> float:
        """The value as a finite float, or `ExpressionError`."""
        if not isinstance(expression, str):
            raise ExpressionError("The expression must be text.")
        if len(expression) > self.MAX_CHARS:
            raise ExpressionError(f"The expression is longer than {self.MAX_CHARS} characters.")
        if not expression.strip():
            raise ExpressionError("The expression is empty.")
        if self._paren_depth(expression) > self.MAX_DEPTH:
            raise ExpressionError("The expression is nested too deeply.")
        try:
            tree = ast.parse(expression.strip(), mode="eval")
        except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
            raise ExpressionError(f"The expression is not valid maths ({type(exc).__name__}).") from None
        return self._finite(self._walk(tree.body, 1))

    @staticmethod
    def _paren_depth(text: str) -> int:
        depth = deepest = 0
        for char in text:
            if char == "(":
                depth += 1
                deepest = max(deepest, depth)
            elif char == ")":
                depth -= 1
        return deepest

    def _walk(self, node: ast.AST, depth: int) -> float:
        if depth > self.MAX_DEPTH:
            raise ExpressionError("The expression is nested too deeply.")
        if isinstance(node, ast.Constant):
            return self._number(node)
        if isinstance(node, ast.Name):
            if node.id in self.CONSTANTS:
                return self.CONSTANTS[node.id]
            raise ExpressionError(f"The name {node.id!r} is not allowed (only pi and e).")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = self._walk(node.operand, depth + 1)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp) and type(node.op) in self._BINARY:
            left, right = self._walk(node.left, depth + 1), self._walk(node.right, depth + 1)
            return self._finite(self._BINARY[type(node.op)](self, left, right))
        if isinstance(node, ast.Call):
            return self._call(node, depth)
        raise ExpressionError(f"{self._describe(node)} is not allowed.")

    def _call(self, node: ast.Call, depth: int) -> float:
        name = node.func.id if isinstance(node.func, ast.Name) else None
        if name is None:
            raise ExpressionError("Calling anything but the listed functions is not allowed.")
        if name not in self.FUNCTIONS:
            raise ExpressionError(f"The function {name!r} is not allowed.")
        if node.keywords or any(isinstance(arg, ast.Starred) for arg in node.args) or len(node.args) != 1:
            raise ExpressionError(f"{name} takes exactly one plain argument.")
        argument = self._walk(node.args[0], depth + 1)
        try:
            return self._finite(float(self.FUNCTIONS[name](argument)))
        except (ValueError, OverflowError):
            raise ExpressionError(f"{name}({argument:g}) is not defined or is too large.") from None

    @staticmethod
    def _number(node: ast.Constant) -> float:
        if type(node.value) not in (int, float):
            raise ExpressionError("Only plain numbers are allowed.")
        try:
            return float(node.value)
        except OverflowError:
            raise ExpressionError("A number is too large.") from None

    def _power(self, base: float, exponent: float) -> float:
        if abs(exponent) > self.MAX_EXPONENT:
            raise ExpressionError(f"An exponent larger than {self.MAX_EXPONENT} is not allowed.")
        try:
            result = base**exponent
        except ZeroDivisionError:
            raise ExpressionError("Division by zero.") from None
        except OverflowError:
            raise ExpressionError("The result is too large.") from None
        if isinstance(result, complex):
            raise ExpressionError("The result is not a real number.")
        return result

    def _divide(self, left: float, right: float) -> float:
        if right == 0:
            raise ExpressionError("Division by zero.")
        return left / right

    _BINARY: ClassVar[dict[type, Any]] = {
        ast.Add: lambda self, a, b: a + b,
        ast.Sub: lambda self, a, b: a - b,
        ast.Mult: lambda self, a, b: a * b,
        ast.Div: _divide,
        ast.Pow: _power,
    }

    @staticmethod
    def _finite(value: float) -> float:
        if not math.isfinite(value):
            raise ExpressionError("The result is not a finite number.")
        return value

    @staticmethod
    def _describe(node: ast.AST) -> str:
        return {
            ast.Attribute: "Attribute access",
            ast.Subscript: "Indexing",
            ast.Lambda: "A lambda",
            ast.Compare: "A comparison",
            ast.BoolOp: "A boolean operator",
            ast.IfExp: "A conditional",
            ast.JoinedStr: "A formatted string",
        }.get(type(node), f"{type(node).__name__} (or this operator)")
