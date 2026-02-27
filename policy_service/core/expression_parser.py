"""
Safe expression evaluator for policy rules.

Uses Python's `ast` module to parse condition strings and evaluate them
against a context dict.  **Does NOT use eval()**.

Supported syntax:
  - Comparisons: <, >, <=, >=, ==, !=
  - Boolean logic: and, or, not
  - Membership: in, not in
  - Dot-access: subject.budget_remaining  (resolves to context["subject"]["budget_remaining"])
  - Literals: numbers, strings, booleans, None
  - Lists: [1, 2, 3]

Forbidden:
  - Function calls, imports, assignments, subscript with non-constant keys, etc.
"""

import ast
import operator
from typing import Any, Dict

_COMPARE_OPS = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}


class PolicyEvaluationError(Exception):
    """Raised when a condition expression cannot be safely evaluated."""


def _resolve_dot(obj: Any, parts: list[str]) -> Any:
    """Walk a nested dict/object by dot-path parts."""
    current = obj
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        elif hasattr(current, part):
            current = getattr(current, part)
        else:
            return None
    return current


class _SafeEvaluator(ast.NodeVisitor):
    """Walk the AST of a condition expression and evaluate it against a context."""

    def __init__(self, context: Dict[str, Any]):
        self.context = context

    # ------------------------------------------------------------------
    # Top-level entry
    # ------------------------------------------------------------------
    def evaluate(self, node: ast.AST) -> Any:
        return self.visit(node)

    # ------------------------------------------------------------------
    # Allowed node types
    # ------------------------------------------------------------------

    def visit_Module(self, node: ast.Module) -> Any:
        if len(node.body) != 1 or not isinstance(node.body[0], ast.Expr):
            raise PolicyEvaluationError("Expression must be a single expression")
        return self.visit(node.body[0])

    def visit_Expr(self, node: ast.Expr) -> Any:
        return self.visit(node.value)

    def visit_Constant(self, node: ast.Constant) -> Any:
        return node.value

    def visit_List(self, node: ast.List) -> Any:
        return [self.visit(elt) for elt in node.elts]

    def visit_Tuple(self, node: ast.Tuple) -> Any:
        return tuple(self.visit(elt) for elt in node.elts)

    def visit_Name(self, node: ast.Name) -> Any:
        name = node.id
        # built-in constants
        if name == "true" or name == "True":
            return True
        if name == "false" or name == "False":
            return False
        if name == "None" or name == "none":
            return None
        # lookup in context (top-level key)
        if name in self.context:
            return self.context[name]
        return None

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        """Resolve dot-access: e.g. subject.budget_remaining"""
        parts: list[str] = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        else:
            raise PolicyEvaluationError(f"Unsupported attribute base: {ast.dump(current)}")
        parts.reverse()
        return _resolve_dot(self.context, parts)

    def visit_Compare(self, node: ast.Compare) -> Any:
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            right = self.visit(comparator)
            op_type = type(op)
            if op_type not in _COMPARE_OPS:
                raise PolicyEvaluationError(f"Unsupported comparison operator: {ast.dump(op)}")
            try:
                if not _COMPARE_OPS[op_type](left, right):
                    return False
            except TypeError:
                # incompatible types (e.g. None < 5) → treat as False
                return False
            left = right
        return True

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        if isinstance(node.op, ast.And):
            return all(self.visit(v) for v in node.values)
        elif isinstance(node.op, ast.Or):
            return any(self.visit(v) for v in node.values)
        raise PolicyEvaluationError(f"Unsupported boolean op: {ast.dump(node.op)}")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        if isinstance(node.op, ast.Not):
            return not self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -self.visit(node.operand)
        raise PolicyEvaluationError(f"Unsupported unary op: {ast.dump(node.op)}")

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        """Ternary: x if cond else y"""
        if self.visit(node.test):
            return self.visit(node.body)
        return self.visit(node.orelse)

    # ------------------------------------------------------------------
    # Fallback — reject anything else
    # ------------------------------------------------------------------
    def generic_visit(self, node: ast.AST) -> Any:
        raise PolicyEvaluationError(
            f"Disallowed expression node: {type(node).__name__}. "
            f"Only comparisons, boolean logic, literals, and dot-access are allowed."
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_condition(expression: str, context: Dict[str, Any]) -> bool:
    """Evaluate a condition expression string against a context dict.

    Args:
        expression: e.g. "subject.budget_remaining < resource.order_total"
        context: e.g. {"subject": {"budget_remaining": 500}, "resource": {"order_total": 1000}}

    Returns:
        True if the condition is met, False otherwise.

    Raises:
        PolicyEvaluationError on disallowed syntax or parse errors.
    """
    try:
        tree = ast.parse(expression, mode="eval" if not expression.strip().startswith("#") else "exec")
        # ast.parse in "eval" mode wraps in ast.Expression; normalise
        if isinstance(tree, ast.Expression):
            tree = ast.Module(body=[ast.Expr(value=tree.body)], type_ignores=[])
    except SyntaxError as exc:
        raise PolicyEvaluationError(f"Syntax error in expression: {exc}") from exc

    evaluator = _SafeEvaluator(context)
    result = evaluator.evaluate(tree)

    # coerce to bool
    return bool(result)

