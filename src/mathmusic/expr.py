"""Safe parsing and evaluation of mathematical expressions in x.

Only arithmetic, numeric literals, x, a few constants and a whitelist of
numpy functions are accepted. Anything else (attributes, subscripts,
lambdas, imports, other names) is rejected before evaluation.
"""

from __future__ import annotations

import ast
from functools import lru_cache

import numpy as np

FUNCTIONS = {
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "asin": np.arcsin,
    "acos": np.arccos,
    "atan": np.arctan,
    "sinh": np.sinh,
    "cosh": np.cosh,
    "tanh": np.tanh,
    "exp": np.exp,
    "log": np.log,
    "log2": np.log2,
    "log10": np.log10,
    "sqrt": np.sqrt,
    "abs": np.abs,
    "floor": np.floor,
    "ceil": np.ceil,
    "sign": np.sign,
    "sinc": np.sinc,
    "mod": np.mod,
    "min": np.minimum,
    "max": np.maximum,
    "clip": np.clip,
}
CONSTANTS = {"pi": np.pi, "tau": 2 * np.pi, "e": np.e}
# Argument counts, checked before evaluation so a bad call is rejected up front.
ARITY = {name: 1 for name in FUNCTIONS}
ARITY.update({"mod": 2, "min": 2, "max": 2, "clip": 3})

_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
)


class ExpressionError(ValueError):
    """Raised when an expression cannot be parsed, is not allowed, or fails to evaluate."""


class _Floats(ast.NodeTransformer):
    """Wrap every numeric literal in float64 so arithmetic follows numpy rules.

    Python's own `1/0` raises ZeroDivisionError; numpy gives inf or nan, which
    the engine treats as an undefined point, like `1/x` at x = 0.
    """

    def visit_Constant(self, node: ast.Constant) -> ast.Call:
        return ast.Call(func=ast.Name(id="_float", ctx=ast.Load()), args=[node], keywords=[])


class Expression:
    """A validated expression y = f(x) that can be evaluated over an array."""

    def __init__(self, source: str) -> None:
        self.source = source
        normalized = source.replace("^", "**")
        try:
            tree = ast.parse(normalized, mode="eval")
        except SyntaxError as exc:
            raise ExpressionError(f"cannot parse {source!r}: {exc.msg}") from exc

        call_names = set()
        for node in ast.walk(tree):
            if not isinstance(node, _ALLOWED_NODES):
                raise ExpressionError(
                    f"{type(node).__name__} is not allowed in {source!r}"
                )
            if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
                raise ExpressionError(f"only numbers are allowed in {source!r}")
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                    name = ast.unparse(node.func)
                    raise ExpressionError(f"unknown function {name!r} in {source!r}")
                if node.keywords or len(node.args) != ARITY[node.func.id]:
                    raise ExpressionError(
                        f"{node.func.id} takes {ARITY[node.func.id]} argument(s) in {source!r}"
                    )
                call_names.add(id(node.func))

        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and id(node) not in call_names:
                if node.id != "x" and node.id not in CONSTANTS:
                    raise ExpressionError(f"unknown name {node.id!r} in {source!r}")

        tree = ast.fix_missing_locations(_Floats().visit(tree))
        self._code = compile(tree, "<expression>", "eval")

    def evaluate(self, x: np.ndarray | float) -> np.ndarray:
        """Evaluate over x. Returns an array shaped like x (NaN/inf where undefined).

        A formula that parses but cannot run (a whitelisted function called with
        the wrong arguments, a literal division by zero) raises ExpressionError,
        so callers can report it against its clip, sound or effect instead of
        letting a TypeError escape and take down the whole render.
        """
        x = np.asarray(x, dtype=float)
        env = {"x": x, "_float": np.float64, **CONSTANTS, **FUNCTIONS}
        try:
            with np.errstate(all="ignore"):
                result = eval(self._code, {"__builtins__": {}}, env)
            return np.broadcast_to(np.asarray(result, dtype=float), x.shape).copy()
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise ExpressionError(f"cannot evaluate {self.source!r}: {exc}") from None

    def __repr__(self) -> str:
        return f"Expression({self.source!r})"


@lru_cache(maxsize=512)
def compile_expression(source: str) -> Expression:
    """A cached Expression for rendering loops, which evaluate the same formulas many times.

    Failures are not cached: a bad formula raises ExpressionError on every call.
    """
    return Expression(source)
