import ast

from wemake_python_styleguide.types import ContextNodes


def is_literal(node: ast.AST) -> bool:
    """
    Checks for nodes that contains only constants.

    If the node contains only literals it will be evaluated.
    When node relies on some other names, it won't be evaluated.
    """
    try:
        ast.literal_eval(node)
    except ValueError:
        return False
    return True


def get_parent(node: ast.AST) -> ast.AST | None:
    """Returns the parent node or ``None`` if node has no parent."""
    return getattr(node, 'wps_parent', None)


def get_context(node: ast.AST) -> ContextNodes | None:
    """Returns the context or ``None`` if node has no context."""
    return getattr(node, 'wps_context', None)


def evaluate_node(node: ast.AST) -> int | float | str | bytes | None:
    """Returns the value of a node or its evaluation."""
    if isinstance(node, ast.Str | ast.Bytes):
        return node.s
    try:
        return ast.literal_eval(node)  # type: ignore[no-any-return]
    except Exception:
        return None
