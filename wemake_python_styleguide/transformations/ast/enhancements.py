import ast
import operator
from contextlib import suppress
from types import MappingProxyType
from typing import Final

from wemake_python_styleguide.compat.aliases import FunctionNodes
from wemake_python_styleguide.logic.nodes import evaluate_node, get_parent
from wemake_python_styleguide.types import ContextNodes

_CONTEXTS: tuple[type[ContextNodes], ...] = (
    ast.Module,
    ast.ClassDef,
    *FunctionNodes,
)

_AST_OPS_TO_OPERATORS: Final = MappingProxyType(
    {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.LShift: operator.lshift,
        ast.RShift: operator.rshift,
        ast.BitAnd: operator.and_,
        ast.BitOr: operator.or_,
        ast.BitXor: operator.xor,
    },
)


def set_node_context(tree: ast.AST) -> ast.AST:
    """
    Used to set proper context to all nodes.

    What we call "a context"?
    Context is where exactly this node belongs on a global level.

    Example:
    .. code:: python

        if some_value > 2:
            test = 'passed'

    Despite the fact ``test`` variable has ``Assign`` as it parent
    it will have ``Module`` as a context.

    What contexts do we respect?

    - :py:class:`ast.Module`
    - :py:class:`ast.ClassDef`
    - :py:class:`ast.FunctionDef` and :py:class:`ast.AsyncFunctionDef`

    .. versionchanged:: 0.8.1

    """
    for statement in ast.walk(tree):
        current_context = _find_context(statement, _CONTEXTS)
        setattr(statement, 'wps_context', current_context)  # noqa: B010
    return tree


def set_constant_evaluations(tree: ast.AST) -> ast.AST:
    """
    Used to evaluate operations between constants.

    We want this to be able to analyze parts of the code in which a math
    operation is making the linter unable to understand if the code is
    compliant or not.

    Example:
    .. code:: python

        value = array[1 + 0.5]

    This should not be allowed, because we would be using a float to index an
    array, but since there is an addition, the linter does not know that and
    does not raise an error.

    """
    for stmt in ast.walk(tree):
        parent = get_parent(stmt)
        if isinstance(stmt, ast.BinOp) and not isinstance(parent, ast.BinOp):
            evaluation = evaluate_operation(stmt)
            setattr(stmt, 'wps_op_eval', evaluation)  # noqa: B010
    return tree


def _find_context(
    node: ast.AST,
    contexts: tuple[type[ast.AST], ...],
) -> ast.AST | None:
    """
    We changed how we find and assign contexts in 0.8.1 version.

    It happened because of the bug #520
    See: https://github.com/wemake-services/wemake-python-styleguide/issues/520
    """
    parent = get_parent(node)
    if parent is None:
        return None
    if isinstance(parent, contexts):
        return parent
    return _find_context(parent, contexts)


def evaluate_operation(
    statement: ast.BinOp,
) -> int | float | str | bytes | None:
    """Tries to evaluate all math operations inside the statement."""
    if isinstance(statement.left, ast.BinOp):
        left = evaluate_operation(statement.left)
    else:
        left = evaluate_node(statement.left)

    if isinstance(statement.right, ast.BinOp):
        right = evaluate_operation(statement.right)
    else:
        right = evaluate_node(statement.right)

    op = _AST_OPS_TO_OPERATORS.get(type(statement.op))

    evaluation = None
    if op is not None:
        with suppress(Exception):
            evaluation = op(left, right)

    return evaluation
