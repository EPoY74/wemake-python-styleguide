import ast
from collections import defaultdict
from collections.abc import Callable
from typing import TypeAlias, cast

from typing_extensions import final

from wemake_python_styleguide.compat.aliases import ForNodes, WithNodes
from wemake_python_styleguide.compat.types import NamedMatch
from wemake_python_styleguide.logic.naming.name_nodes import flat_variable_names
from wemake_python_styleguide.logic.nodes import get_context, get_parent
from wemake_python_styleguide.logic.scopes import defs, predicates
from wemake_python_styleguide.logic.walk import is_contained_by
from wemake_python_styleguide.types import (
    AnyAssignWithWalrus,
    AnyFor,
    AnyFunctionDef,
    AnyImport,
    AnyWith,
)
from wemake_python_styleguide.violations.best_practices import (
    BlockAndLocalOverlapViolation,
    ControlVarUsedAfterBlockViolation,
    OuterScopeShadowingViolation,
)
from wemake_python_styleguide.visitors import base, decorators

#: That's how we represent contexts for control variables.
_BlockVariables: TypeAlias = defaultdict[
    ast.AST,
    defaultdict[str, list[ast.AST]],
]

#: That's how we filter some overlaps that do happen in Python:
_ScopePredicate: TypeAlias = Callable[[ast.AST, set[str]], bool]
_NamePredicate: TypeAlias = Callable[[ast.AST], bool]

#: Named nodes.
_NamedNode: TypeAlias = (
    AnyFunctionDef | ast.ClassDef | ast.ExceptHandler | NamedMatch
)


@final
@decorators.alias(
    'visit_named_nodes',
    (
        'visit_FunctionDef',
        'visit_AsyncFunctionDef',
        'visit_ClassDef',
        'visit_ExceptHandler',
        'visit_MatchAs',
        'visit_MatchStar',
    ),
)
@decorators.alias(
    'visit_any_for',
    (
        'visit_For',
        'visit_AsyncFor',
    ),
)
@decorators.alias(
    'visit_locals',
    (
        'visit_Assign',
        'visit_AnnAssign',
        'visit_NamedExpr',
        'visit_arg',
    ),
)
class BlockVariableVisitor(base.BaseNodeVisitor):
    """
    This visitor is used to detect variables that are reused for blocks.

    Check out this example:

    .. code::

      exc = 7
      try:
          ...
      except Exception as exc:  # reusing existing variable
          ...

    Please, do not modify. This is fragile and complex.

    """

    _naming_predicates: tuple[_NamePredicate, ...] = (
        predicates.is_property_setter,
        predicates.is_function_overload,
        predicates.is_no_value_annotation,
    )

    _scope_predicates: tuple[_ScopePredicate, ...] = (
        lambda node, names: predicates.is_property_setter(node),
        predicates.is_same_value_reuse,
        predicates.is_same_try_except_cases,
    )

    # Blocks:

    def visit_named_nodes(self, node: _NamedNode) -> None:
        """Visits block nodes that have ``.name`` property."""
        names = {node.name} if node.name else set()
        self._scope(node, names, is_local=False)
        self._outer_scope(node, names)
        self.generic_visit(node)

    def visit_any_for(self, node: AnyFor) -> None:
        """Collects block nodes from loop definitions."""
        names = defs.extract_names(node.target)
        self._scope(node, names, is_local=False)
        self._outer_scope(node, names)
        self.generic_visit(node)

    def visit_alias(self, node: ast.alias) -> None:
        """Aliases from ``import`` and ``from ... import`` block nodes."""
        parent = cast(AnyImport, get_parent(node))
        import_name = {node.asname} if node.asname else {node.name}
        self._scope(parent, import_name, is_local=False)
        self._outer_scope(parent, import_name)
        self.generic_visit(node)

    def visit_withitem(self, node: ast.withitem) -> None:
        """Visits ``with`` and ``async with`` declarations."""
        if node.optional_vars:
            parent = cast(AnyWith, get_parent(node))
            names = defs.extract_names(node.optional_vars)
            self._scope(parent, names, is_local=False)
            self._outer_scope(parent, names)
        self.generic_visit(node)

    # Locals:

    def visit_locals(self, node: AnyAssignWithWalrus | ast.arg) -> None:
        """Visits local variable definitions and function arguments."""
        if isinstance(node, ast.arg):
            names = {node.arg}
        else:
            names = set(flat_variable_names([node]))

        self._scope(node, names, is_local=True)
        self._outer_scope(node, names)
        self.generic_visit(node)

    # Utils:

    def _scope(
        self,
        node: ast.AST,
        names: set[str],
        *,
        is_local: bool,
    ) -> None:
        scope = defs.BlockScope(node)
        shadow = scope.shadowing(names, is_local=is_local)

        ignored_scope = any(
            predicate(node, names) for predicate in self._scope_predicates
        )
        ignored_name = any(
            predicate(node) for predicate in self._naming_predicates
        )

        if shadow and not ignored_scope:
            self.add_violation(
                BlockAndLocalOverlapViolation(node, text=', '.join(shadow)),
            )

        if not ignored_name:
            scope.add_to_scope(names, is_local=is_local)

    def _outer_scope(self, node: ast.AST, names: set[str]) -> None:
        scope = defs.OuterScope(node)
        shadow = scope.shadowing(names)

        if shadow:
            self.add_violation(
                OuterScopeShadowingViolation(node, text=', '.join(shadow)),
            )

        scope.add_to_scope(names)


@final
@decorators.alias(
    'visit_any_for',
    (
        'visit_For',
        'visit_AsyncFor',
    ),
)
class AfterBlockVariablesVisitor(base.BaseNodeVisitor):
    """Visitor that ensures that block variables are not used after block."""

    def __init__(self, *args, **kwargs) -> None:
        """We need to store complex data about variable usages."""
        super().__init__(*args, **kwargs)
        self._block_variables: _BlockVariables = defaultdict(
            lambda: defaultdict(list),
        )

    # Blocks:

    def visit_any_for(self, node: AnyFor) -> None:
        """Visit loops."""
        self._add_to_scope(node, defs.extract_names(node.target))
        self.generic_visit(node)

    def visit_withitem(self, node: ast.withitem) -> None:
        """Visits ``with`` and ``async with`` declarations."""
        if node.optional_vars:
            self._add_to_scope(
                cast(AnyWith, get_parent(node)),
                defs.extract_names(node.optional_vars),
            )
        self.generic_visit(node)

    # Variable usages:

    def visit_Name(self, node: ast.Name) -> None:
        """Check variable usages."""
        if isinstance(node.ctx, ast.Load):
            self._check_variable_usage(node)
        self.generic_visit(node)

    # Utils:

    def _add_to_scope(self, node: ast.AST, names: set[str]) -> None:
        context = cast(ast.AST, get_context(node))
        for var_name in names:
            self._block_variables[context][var_name].append(node)

    def _check_variable_usage(self, node: ast.Name) -> None:
        context = cast(ast.AST, get_context(node))
        blocks = self._block_variables[context][node.id]
        is_contained_block_var = any(
            is_contained_by(node, block) for block in blocks
        )
        # Restrict the use of block variables with the same name to
        # the same type of block - either `for` or `with`.
        is_same_type_block = all(
            isinstance(block, ForNodes) for block in blocks
        ) or all(isinstance(block, WithNodes) for block in blocks)
        # Return if not a block variable or a contained block variable.
        if not blocks or (is_contained_block_var and is_same_type_block):
            return

        self.add_violation(
            ControlVarUsedAfterBlockViolation(node, text=node.id),
        )
