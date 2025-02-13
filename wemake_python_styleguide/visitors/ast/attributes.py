import ast

from typing_extensions import final

from wemake_python_styleguide.compat.aliases import FunctionNodes
from wemake_python_styleguide.constants import (
    ALL_MAGIC_METHODS,
    SPECIAL_ARGUMENT_NAMES_WHITELIST,
)
from wemake_python_styleguide.logic import nodes
from wemake_python_styleguide.logic.naming import access
from wemake_python_styleguide.violations.base import ASTViolation
from wemake_python_styleguide.violations.best_practices import (
    ProtectedAttributeViolation,
)
from wemake_python_styleguide.violations.oop import (
    DirectMagicAttributeAccessViolation,
)
from wemake_python_styleguide.visitors.base import BaseNodeVisitor


@final
class WrongAttributeVisitor(BaseNodeVisitor):
    """Ensures that attributes are used correctly."""

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Checks the `Attribute` node."""
        self._check_protected_attribute(node)
        self._check_magic_attribute(node)
        self.generic_visit(node)

    def _is_super_called(self, node: ast.Call) -> bool:
        return isinstance(node.func, ast.Name) and node.func.id == 'super'

    def _ensure_attribute_type(
        self,
        node: ast.Attribute,
        exception: type[ASTViolation],
    ) -> None:
        if (
            isinstance(node.value, ast.Name)
            and node.value.id in SPECIAL_ARGUMENT_NAMES_WHITELIST
        ):
            return

        if isinstance(node.value, ast.Call) and self._is_super_called(
            node.value,
        ):
            return

        self.add_violation(exception(node, text=node.attr))

    def _check_protected_attribute(self, node: ast.Attribute) -> None:
        if access.is_protected(node.attr):
            self._ensure_attribute_type(node, ProtectedAttributeViolation)

    def _check_magic_attribute(self, node: ast.Attribute) -> None:
        if access.is_magic(node.attr):
            # If "magic" method being called has the same name as
            # the enclosing function, then it is a "wrapper" and thus
            # a "false positive".

            ctx = nodes.get_context(node)
            if isinstance(ctx, FunctionNodes) and node.attr == ctx.name:
                return

            if node.attr in ALL_MAGIC_METHODS:
                self._ensure_attribute_type(
                    node,
                    DirectMagicAttributeAccessViolation,
                )
