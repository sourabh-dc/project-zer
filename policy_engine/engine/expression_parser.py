"""
Safe Expression Parser for Policy Conditions
Evaluates policy condition expressions against a context dictionary.

Supports:
- Comparisons: ==, !=, <, <=, >, >=, in, not in
- Boolean operators: and, or, not
- Attribute access: subject.budget_remaining
- List literals: ['admin', 'manager']
- Numeric literals: 10000, 3.14
- String literals: 'active', "pending"
- Boolean literals: True, False, None

Examples:
- "subject.budget_remaining < resource.order_total"
- "subject.role in ['admin', 'manager']"
- "resource.amount > 10000 and subject.org_unit_type == 'department'"
- "not subject.is_blocked"
"""
import ast
import operator
from typing import Any, Dict


# Allowed comparison operators
COMPARISON_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}

# Allowed binary operators
BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}


class ExpressionError(Exception):
    """Raised when expression evaluation fails"""
    pass


class SafeExpressionEvaluator(ast.NodeVisitor):
    """
    Safely evaluates policy condition expressions.
    
    Only allows a restricted subset of Python expressions
    to prevent code injection attacks.
    """
    
    # Maximum recursion depth to prevent stack overflow
    MAX_DEPTH = 50
    
    def __init__(self, context: Dict[str, Any]):
        self.context = context
        self._depth = 0
    
    def evaluate(self, expression: str) -> Any:
        """
        Evaluate an expression and return the result.
        
        Args:
            expression: The expression string to evaluate
            
        Returns:
            The result of evaluating the expression
            
        Raises:
            ExpressionError: If the expression is invalid or unsafe
        """
        if not expression or not expression.strip():
            raise ExpressionError("Empty expression")
        
        try:
            tree = ast.parse(expression.strip(), mode='eval')
            return self.visit(tree.body)
        except SyntaxError as e:
            raise ExpressionError(f"Syntax error in expression: {e}")
        except Exception as e:
            raise ExpressionError(f"Expression evaluation failed: {e}")
    
    def visit(self, node):
        """Visit a node with depth tracking"""
        self._depth += 1
        if self._depth > self.MAX_DEPTH:
            raise ExpressionError("Expression too complex (max depth exceeded)")
        
        try:
            return super().visit(node)
        finally:
            self._depth -= 1
    
    def visit_Compare(self, node):
        """Handle comparison expressions: a < b, a == b, a in [1,2,3]"""
        left = self.visit(node.left)
        
        for op, comparator in zip(node.ops, node.comparators):
            right = self.visit(comparator)
            
            if isinstance(op, ast.In):
                if not hasattr(right, '__contains__'):
                    raise ExpressionError(f"Cannot use 'in' with {type(right)}")
                if left not in right:
                    return False
            elif isinstance(op, ast.NotIn):
                if not hasattr(right, '__contains__'):
                    raise ExpressionError(f"Cannot use 'not in' with {type(right)}")
                if left in right:
                    return False
            elif type(op) in COMPARISON_OPS:
                try:
                    if not COMPARISON_OPS[type(op)](left, right):
                        return False
                except TypeError:
                    # Handle comparison of incompatible types
                    return False
            else:
                raise ExpressionError(f"Unsupported comparison operator: {type(op).__name__}")
            
            left = right
        
        return True
    
    def visit_BoolOp(self, node):
        """Handle boolean operations: and, or"""
        if isinstance(node.op, ast.And):
            for value in node.values:
                if not self.visit(value):
                    return False
            return True
        elif isinstance(node.op, ast.Or):
            for value in node.values:
                if self.visit(value):
                    return True
            return False
        else:
            raise ExpressionError(f"Unsupported boolean operator: {type(node.op).__name__}")
    
    def visit_UnaryOp(self, node):
        """Handle unary operations: not, -"""
        operand = self.visit(node.operand)
        
        if isinstance(node.op, ast.Not):
            return not operand
        elif isinstance(node.op, ast.USub):
            return -operand
        elif isinstance(node.op, ast.UAdd):
            return +operand
        else:
            raise ExpressionError(f"Unsupported unary operator: {type(node.op).__name__}")
    
    def visit_BinOp(self, node):
        """Handle binary operations: +, -, *, /, %"""
        left = self.visit(node.left)
        right = self.visit(node.right)
        
        if type(node.op) in BINARY_OPS:
            try:
                return BINARY_OPS[type(node.op)](left, right)
            except Exception as e:
                raise ExpressionError(f"Binary operation failed: {e}")
        else:
            raise ExpressionError(f"Unsupported binary operator: {type(node.op).__name__}")
    
    def visit_IfExp(self, node):
        """Handle ternary expressions: a if condition else b"""
        if self.visit(node.test):
            return self.visit(node.body)
        else:
            return self.visit(node.orelse)
    
    def visit_Attribute(self, node):
        """Handle attribute access: subject.budget_remaining"""
        value = self.visit(node.value)
        attr = node.attr
        
        if value is None:
            return None
        
        # Try dictionary access first
        if isinstance(value, dict):
            return value.get(attr)
        
        # Then try attribute access
        if hasattr(value, attr):
            return getattr(value, attr)
        
        return None
    
    def visit_Subscript(self, node):
        """Handle subscript access: resource.products[0]"""
        value = self.visit(node.value)
        
        if value is None:
            return None
        
        # Handle slice
        if isinstance(node.slice, ast.Slice):
            raise ExpressionError("Slice notation not supported")
        
        index = self.visit(node.slice)
        
        try:
            return value[index]
        except (KeyError, IndexError, TypeError):
            return None
    
    def visit_Name(self, node):
        """Handle variable names: subject, resource, context"""
        name = node.id
        
        # Built-in constants
        if name == 'True':
            return True
        elif name == 'False':
            return False
        elif name == 'None':
            return None
        
        # Context variables
        if name in self.context:
            return self.context[name]
        
        raise ExpressionError(f"Unknown variable: {name}")
    
    def visit_Constant(self, node):
        """Handle literals: 10000, 'admin', True"""
        return node.value
    
    # Python 3.7 compatibility
    def visit_Num(self, node):
        """Handle numeric literals (Python 3.7)"""
        return node.n
    
    def visit_Str(self, node):
        """Handle string literals (Python 3.7)"""
        return node.s
    
    def visit_NameConstant(self, node):
        """Handle True/False/None (Python 3.7)"""
        return node.value
    
    def visit_List(self, node):
        """Handle list literals: [1, 2, 3]"""
        return [self.visit(el) for el in node.elts]
    
    def visit_Tuple(self, node):
        """Handle tuple literals: (1, 2, 3)"""
        return tuple(self.visit(el) for el in node.elts)
    
    def visit_Set(self, node):
        """Handle set literals: {1, 2, 3}"""
        return {self.visit(el) for el in node.elts}
    
    def visit_Dict(self, node):
        """Handle dict literals: {'a': 1, 'b': 2}"""
        return {
            self.visit(k): self.visit(v)
            for k, v in zip(node.keys, node.values)
        }
    
    def generic_visit(self, node):
        """Reject any unsupported node types"""
        raise ExpressionError(f"Unsupported expression type: {type(node).__name__}")


def evaluate_expression(expression: str, context: Dict[str, Any]) -> Any:
    """
    Safely evaluate a policy condition expression.
    
    Args:
        expression: The condition expression to evaluate
        context: Dictionary with 'subject', 'resource', 'context', etc.
        
    Returns:
        The result of evaluating the expression (usually bool)
        
    Raises:
        ExpressionError: If the expression is invalid or evaluation fails
        
    Examples:
        >>> evaluate_expression(
        ...     "subject.budget_remaining < resource.order_total",
        ...     {"subject": {"budget_remaining": 5000}, "resource": {"order_total": 10000}}
        ... )
        True
        
        >>> evaluate_expression(
        ...     "subject.role in ['admin', 'manager'] and resource.amount <= 50000",
        ...     {"subject": {"role": "manager"}, "resource": {"amount": 30000}}
        ... )
        True
    """
    evaluator = SafeExpressionEvaluator(context)
    return evaluator.evaluate(expression)


def validate_expression(expression: str) -> tuple[bool, str]:
    """
    Validate an expression without evaluating it.
    
    Args:
        expression: The expression to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not expression or not expression.strip():
        return False, "Expression cannot be empty"
    
    try:
        tree = ast.parse(expression.strip(), mode='eval')
        # Walk the tree to check for disallowed constructs
        for node in ast.walk(tree):
            if isinstance(node, (ast.Call, ast.Lambda, ast.ListComp, 
                                ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                return False, f"Disallowed construct: {type(node).__name__}"
        return True, ""
    except SyntaxError as e:
        return False, f"Syntax error: {e}"
    except Exception as e:
        return False, f"Validation error: {e}"
