from __future__ import annotations

import ast
from typing import Dict, List, Tuple

from pycodehygiene.indexer import is_type_checking_test
from pycodehygiene.models import ReachabilitySummary, RepoIndex


TERMINAL_NODES = (ast.Return, ast.Raise, ast.Break, ast.Continue)


class ReachabilityAnalyzer:
    def __init__(self, index: RepoIndex):
        self.index = index

    def build(self) -> ReachabilitySummary:
        summary = ReachabilitySummary()

        for module_info in self.index.modules.values():
            unreachable: List[Tuple[int, int, str]] = []
            self._collect_unreachable(module_info.tree.body, unreachable)
            if unreachable:
                summary.unreachable[str(module_info.file_path)] = unreachable

        return summary

    def _collect_unreachable(self, statements: List[ast.stmt], out: List[Tuple[int, int, str]]):
        unreachable = False

        for statement in statements:
            if unreachable:
                out.append(
                    (
                        statement.lineno,
                        getattr(statement, "end_lineno", statement.lineno),
                        "code after terminal statement",
                    )
                )
                continue

            if isinstance(statement, TERMINAL_NODES):
                unreachable = True

            if isinstance(statement, ast.If):
                if is_type_checking_test(statement.test):
                    # Skip TYPE_CHECKING blocks to avoid noise.
                    self._collect_unreachable(statement.orelse, out)
                    continue

                constant = _constant_bool(statement.test)
                if constant is True:
                    self._collect_unreachable(statement.body, out)
                    if statement.orelse:
                        for stmt in statement.orelse:
                            out.append(
                                (
                                    stmt.lineno,
                                    getattr(stmt, "end_lineno", stmt.lineno),
                                    "constant-true branch unreachable",
                                )
                            )
                    continue
                if constant is False:
                    if statement.body:
                        for stmt in statement.body:
                            out.append(
                                (
                                    stmt.lineno,
                                    getattr(stmt, "end_lineno", stmt.lineno),
                                    "constant-false branch unreachable",
                                )
                            )
                    self._collect_unreachable(statement.orelse, out)
                    continue

                self._collect_unreachable(statement.body, out)
                self._collect_unreachable(statement.orelse, out)
                continue

            if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
                self._collect_unreachable(statement.body, out)
                self._collect_unreachable(statement.orelse, out)
                continue

            if isinstance(statement, ast.Try):
                self._collect_unreachable(statement.body, out)
                for handler in statement.handlers:
                    self._collect_unreachable(handler.body, out)
                self._collect_unreachable(statement.orelse, out)
                self._collect_unreachable(statement.finalbody, out)
                continue

            if isinstance(statement, (ast.With, ast.AsyncWith)):
                self._collect_unreachable(statement.body, out)
                continue


def _constant_bool(node: ast.AST) -> object:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    return None
