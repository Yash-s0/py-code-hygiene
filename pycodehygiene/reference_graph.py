from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from pycodehygiene.config import Config
from pycodehygiene.indexer import attribute_chain, is_type_checking_test
from pycodehygiene.models import RepoIndex, UsageSummary


DYNAMIC_CALL_NAMES = {
    "getattr",
    "setattr",
    "hasattr",
    "globals",
    "locals",
    "vars",
    "__import__",
    "eval",
    "exec",
}

DYNAMIC_IMPORT_MODULES = {"importlib", "pkg_resources"}
DYNAMIC_IMPORT_FUNCS = {"import_module", "reload", "load_entry_point"}


@dataclass
class ScopeState:
    kind: str
    assigned: Dict[str, Tuple[int, bool]]
    used: Set[str]
    inferred_types: Dict[str, Set[str]]
    global_names: Set[str]
    nonlocal_names: Set[str]

    def __init__(self, kind: str):
        self.kind = kind
        self.assigned = {}
        self.used = set()
        self.inferred_types = {}
        self.global_names = set()
        self.nonlocal_names = set()


class ReferenceGraphBuilder:
    def __init__(self, index: RepoIndex, config: Config):
        self.index = index
        self.config = config

    def build(self) -> UsageSummary:
        summary = UsageSummary()

        for module_info in self.index.modules.values():
            collector = ModuleReferenceCollector(self.index, module_info, self.config)
            collector.visit(module_info.tree)

            summary.used_symbols.update(collector.used_symbols)
            summary.used_imports.update(collector.used_imports)
            _merge_contexts(summary.symbol_contexts, collector.symbol_contexts)
            _merge_contexts(summary.import_contexts, collector.import_contexts)
            _merge_contexts(summary.potential_symbol_reasons, collector.potential_symbol_reasons)

            if collector.unused_locals:
                summary.unused_locals[str(module_info.file_path)] = collector.unused_locals

            if collector.module_flags:
                module_info.flags.update(collector.module_flags)

        return summary


class ModuleReferenceCollector(ast.NodeVisitor):
    def __init__(self, index: RepoIndex, module_info, config: Config):
        self.index = index
        self.module_info = module_info
        self.config = config
        self.used_symbols: Set[str] = set()
        self.used_imports: Set[str] = set()
        self.symbol_contexts: Dict[str, Set[str]] = {}
        self.import_contexts: Dict[str, Set[str]] = {}
        self.potential_symbol_reasons: Dict[str, Set[str]] = {}
        self.unused_locals: List[Tuple[int, str, bool]] = []
        self.module_flags: Set[str] = set()

        self.scope_stack: List[ScopeState] = [ScopeState("module")]
        self.qualname_stack: List[str] = []
        self.class_symbol_stack: List[str] = []
        self.container_stack: List[str] = []
        self.type_checking_stack: List[bool] = [False]
        self.annotation_stack: List[bool] = [False]

        self.unresolved_attribute_calls: Set[str] = set()

    def visit_Module(self, node: ast.Module):
        for stmt in node.body:
            self.visit(stmt)

        self._finalize_scope(self.scope_stack.pop())
        self._apply_unresolved_attribute_matches()

    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Load):
            self._mark_name_used(node.id)

    def visit_Global(self, node: ast.Global):
        self.scope_stack[-1].global_names.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal):
        self.scope_stack[-1].nonlocal_names.update(node.names)

    def visit_ClassDef(self, node: ast.ClassDef):
        class_id = self._lookup_class_symbol(node)
        if class_id:
            self.class_symbol_stack.append(class_id)

        self.qualname_stack.append(node.name)
        self.container_stack.append("class")

        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            if keyword.value:
                self.visit(keyword.value)
        for stmt in node.body:
            self.visit(stmt)

        self.container_stack.pop()
        self.qualname_stack.pop()
        if class_id:
            self.class_symbol_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._visit_function(node)

    def _visit_function(self, node: ast.AST):
        self.qualname_stack.append(node.name)
        self.container_stack.append("function")
        self.scope_stack.append(ScopeState("function"))

        for decorator in node.decorator_list:
            self.visit(decorator)

        self._register_function_arguments(node)

        if getattr(node, "returns", None):
            self._visit_annotation(node.returns)

        for stmt in node.body:
            self.visit(stmt)

        self._finalize_scope(self.scope_stack.pop())
        self.container_stack.pop()
        self.qualname_stack.pop()

    def _register_function_arguments(self, node: ast.AST):
        scope = self.scope_stack[-1]
        all_args = []
        all_args.extend(getattr(node.args, "posonlyargs", []))
        all_args.extend(node.args.args)
        all_args.extend(node.args.kwonlyargs)

        if node.args.vararg:
            all_args.append(node.args.vararg)
        if node.args.kwarg:
            all_args.append(node.args.kwarg)

        for arg in all_args:
            if arg.annotation:
                self._visit_annotation(arg.annotation)
            line = getattr(arg, "lineno", node.lineno)
            scope.assigned[arg.arg] = (line, False)

        for default in node.args.defaults:
            self.visit(default)
        for default in node.args.kw_defaults:
            if default:
                self.visit(default)

        if self.class_symbol_stack and node.args.args:
            first_arg = node.args.args[0].arg
            scope.inferred_types[first_arg] = {self.class_symbol_stack[-1]}

    def visit_Call(self, node: ast.Call):
        if self._is_dynamic_call(node):
            self.module_flags.add("dynamic_usage")
        self._handle_call_target(node.func)

        for arg in node.args:
            self.visit(arg)
        for keyword in node.keywords:
            if keyword.value:
                self.visit(keyword.value)

    def visit_Attribute(self, node: ast.Attribute):
        if isinstance(node.ctx, ast.Load):
            chain = attribute_chain(node)
            if chain:
                self._mark_import_binding_used(chain[0])
                if not self._mark_attribute_chain_to_symbols(chain):
                    self.unresolved_attribute_calls.add(node.attr)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        inferred_class_ids = self._infer_class_ids_from_value(node.value)
        safe = is_side_effect_free_expr(node.value)
        for target in node.targets:
            self._assign_target(target, node.lineno, inferred_class_ids, safe)
            if isinstance(target, ast.Attribute):
                self.module_flags.add("dynamic_usage")
            self._visit_assignment_target_reads(target)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        if node.annotation:
            self._visit_annotation(node.annotation)
        inferred_class_ids = self._infer_class_ids_from_value(node.value) if node.value else None
        safe = is_side_effect_free_expr(node.value) if node.value else True
        self._assign_target(node.target, node.lineno, inferred_class_ids, safe)
        self._visit_assignment_target_reads(node.target)
        if node.value:
            self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign):
        if isinstance(node.target, ast.Name):
            self._mark_name_used(node.target.id)
            self._assign_name(node.target.id, node.lineno, safe=False)
        else:
            self.visit(node.target)
        self.visit(node.value)

    def visit_For(self, node: ast.For):
        self.visit(node.iter)
        self._assign_target(node.target, node.lineno, safe=False)
        for stmt in node.body:
            self.visit(stmt)
        for stmt in node.orelse:
            self.visit(stmt)

    def visit_AsyncFor(self, node: ast.AsyncFor):
        self.visit_For(node)

    def visit_With(self, node: ast.With):
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars:
                self._assign_target(item.optional_vars, node.lineno, safe=False)
        for stmt in node.body:
            self.visit(stmt)

    def visit_AsyncWith(self, node: ast.AsyncWith):
        self.visit_With(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        if node.type:
            self.visit(node.type)
        if node.name:
            self._assign_name(node.name, node.lineno, safe=False)
        for stmt in node.body:
            self.visit(stmt)

    def visit_If(self, node: ast.If):
        if is_type_checking_test(node.test):
            self.type_checking_stack.append(True)
            for stmt in node.body:
                self.visit(stmt)
            self.type_checking_stack.pop()
            for stmt in node.orelse:
                self.visit(stmt)
        else:
            self.visit(node.test)
            for stmt in node.body:
                self.visit(stmt)
            for stmt in node.orelse:
                self.visit(stmt)

    def visit_Try(self, node: ast.Try):
        for stmt in node.body:
            self.visit(stmt)
        for handler in node.handlers:
            self.visit(handler)
        for stmt in node.orelse:
            self.visit(stmt)
        for stmt in node.finalbody:
            self.visit(stmt)

    def _handle_call_target(self, func: ast.AST):
        if isinstance(func, ast.Name):
            self._mark_name_used(func.id)
            self._mark_named_symbols_used(func.id)
            self._mark_import_binding_used(func.id)
            return

        if isinstance(func, ast.Attribute):
            self.visit(func.value)
            if not self._mark_attribute_callable(func):
                self.unresolved_attribute_calls.add(func.attr)
            return

        self.visit(func)

    def _mark_attribute_callable(self, node: ast.Attribute) -> bool:
        resolved = False
        if isinstance(node.value, ast.Name):
            variable_name = node.value.id

            class_ids = self._infer_variable_class_ids(variable_name)
            if class_ids and self._mark_methods_used(class_ids, node.attr):
                resolved = True

            class_name_ids = self._resolve_name_to_class_ids(variable_name)
            if class_name_ids:
                self.used_symbols.update(class_name_ids)
                if self._mark_methods_used(class_name_ids, node.attr):
                    resolved = True

        chain = attribute_chain(node)
        if chain and self._mark_attribute_chain_to_symbols(chain):
            resolved = True

        return resolved

    def _assign_target(
        self,
        target: ast.AST,
        line: int,
        inferred_class_ids: Optional[Set[str]] = None,
        safe: bool = True,
    ):
        for name in extract_target_names(target):
            self._assign_name(name, line, inferred_class_ids, safe)

    def _visit_assignment_target_reads(self, target: ast.AST) -> None:
        if isinstance(target, ast.Subscript):
            self.visit(target.value)
            self.visit(target.slice)
        elif isinstance(target, ast.Attribute):
            self.visit(target.value)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._visit_assignment_target_reads(element)
        elif isinstance(target, ast.Starred):
            self._visit_assignment_target_reads(target.value)

    def _assign_name(
        self,
        name: str,
        line: int,
        inferred_class_ids: Optional[Set[str]] = None,
        safe: bool = True,
    ):
        if name == "__all__":
            return

        scope = self._resolve_assignment_scope(name)
        scope.assigned[name] = (line, safe)

        if inferred_class_ids:
            scope.inferred_types[name] = set(inferred_class_ids)
        elif name in scope.inferred_types:
            del scope.inferred_types[name]

    def _mark_name_used(self, name: str):
        scope = self._resolve_usage_scope(name)
        if scope:
            scope.used.add(name)

        self._mark_import_binding_used(name)
        self._mark_named_symbols_used(name)

    def _resolve_assignment_scope(self, name: str) -> ScopeState:
        current = self.scope_stack[-1]
        if name in current.global_names:
            return self.scope_stack[0]

        if name in current.nonlocal_names:
            for scope in reversed(self.scope_stack[:-1]):
                if scope.kind == "function":
                    return scope
        return current

    def _resolve_usage_scope(self, name: str) -> Optional[ScopeState]:
        current = self.scope_stack[-1]
        if name in current.global_names:
            module_scope = self.scope_stack[0]
            if name in module_scope.assigned:
                return module_scope

        for scope in reversed(self.scope_stack):
            if name in scope.assigned:
                return scope
        return None

    def _mark_import_binding_used(self, name: str):
        for import_id in self.module_info.import_bindings_by_name.get(name, []):
            self._track_import_context(import_id)

    def _mark_named_symbols_used(self, name: str):
        for symbol_id in self.index.symbol_ids_by_module_and_name.get(self.module_info.module, {}).get(
            name, set()
        ):
            self.used_symbols.add(symbol_id)
            self._track_symbol_context(symbol_id)

    def _track_import_context(self, import_id: str):
        context = self._current_context()
        self.import_contexts.setdefault(import_id, set()).add(context)
        if context == "runtime":
            self.used_imports.add(import_id)
            binding = self.index.imports.get(import_id)
            if binding and binding.target_symbol_ids:
                for symbol_id in binding.target_symbol_ids:
                    self.used_symbols.add(symbol_id)
                    self._track_symbol_context(symbol_id)

    def _track_symbol_context(self, symbol_id: str):
        context = self._current_context()
        self.symbol_contexts.setdefault(symbol_id, set()).add(context)

    def _current_context(self) -> str:
        if self.annotation_stack and self.annotation_stack[-1]:
            return "annotation"
        if self.type_checking_stack and self.type_checking_stack[-1]:
            return "type_checking"
        return "runtime"

    def _infer_class_ids_from_value(self, value: Optional[ast.AST]) -> Optional[Set[str]]:
        if value is None:
            return None
        if isinstance(value, ast.Call):
            return self._infer_class_ids_from_call(value)
        if isinstance(value, ast.Name):
            return self._infer_variable_class_ids(value.id)
        return None

    def _infer_class_ids_from_call(self, node: ast.Call) -> Optional[Set[str]]:
        if isinstance(node.func, ast.Name):
            class_ids = self._resolve_name_to_class_ids(node.func.id)
            return set(class_ids) if class_ids else None

        if isinstance(node.func, ast.Attribute):
            chain = attribute_chain(node.func)
            if chain:
                symbol_ids = self._resolve_symbols_from_chain(chain)
                class_ids = {sid for sid in symbol_ids if sid in self.index.class_lookup.values()}
                return class_ids if class_ids else None

        return None

    def _infer_variable_class_ids(self, name: str) -> Optional[Set[str]]:
        for scope in reversed(self.scope_stack):
            if name in scope.inferred_types:
                return set(scope.inferred_types[name])
        return None

    def _resolve_name_to_class_ids(self, name: str) -> Set[str]:
        class_ids: Set[str] = set()

        for symbol_id in self.index.symbol_ids_by_module_and_name.get(self.module_info.module, {}).get(
            name, set()
        ):
            if symbol_id in self.index.class_lookup.values():
                class_ids.add(symbol_id)

        for import_id in self.module_info.import_bindings_by_name.get(name, []):
            binding = self.index.imports[import_id]
            class_ids.update(
                symbol_id
                for symbol_id in binding.target_symbol_ids
                if symbol_id in self.index.class_lookup.values()
            )

        return class_ids

    def _mark_methods_used(self, class_ids: Set[str], method_name: str) -> bool:
        resolved = False
        for class_id in class_ids:
            for method_id in self.index.class_methods.get(class_id, {}).get(method_name, set()):
                self.used_symbols.add(method_id)
                self._track_symbol_context(method_id)
                resolved = True
        return resolved

    def _mark_attribute_chain_to_symbols(self, chain: List[str]) -> bool:
        symbol_ids = self._resolve_symbols_from_chain(chain)
        if not symbol_ids:
            return False
        for symbol_id in symbol_ids:
            self.used_symbols.add(symbol_id)
            self._track_symbol_context(symbol_id)
        return True

    def _resolve_symbols_from_chain(self, chain: List[str]) -> Set[str]:
        candidates = self._expanded_chains(chain)
        resolved: Set[str] = set()

        for full_chain in candidates:
            if len(full_chain) < 2:
                continue
            for split_index in range(len(full_chain) - 1, 0, -1):
                module_name = ".".join(full_chain[:split_index])
                symbol_name = full_chain[split_index]
                # TODO: Incorporate import graph + type inference for deeper resolution.
                symbol_ids = self.index.top_level_defs_by_module.get(module_name, {}).get(
                    symbol_name, set()
                )
                if symbol_ids:
                    resolved.update(symbol_ids)
        return resolved

    def _expanded_chains(self, chain: List[str]) -> List[List[str]]:
        expanded = [chain]
        first = chain[0]

        for imported_module in self.module_info.module_aliases.get(first, set()):
            imported_parts = imported_module.split(".")
            if chain[: len(imported_parts)] == imported_parts:
                expanded.append(chain)
            else:
                expanded.append(imported_parts + chain[1:])

        unique: List[List[str]] = []
        seen: Set[Tuple[str, ...]] = set()
        for item in expanded:
            key = tuple(item)
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    def _lookup_class_symbol(self, node: ast.ClassDef) -> Optional[str]:
        qualname = ".".join(self.qualname_stack + [node.name]) if self.qualname_stack else node.name
        return self.index.class_lookup.get((self.module_info.module, qualname, node.lineno))

    def _finalize_scope(self, scope: ScopeState):
        if scope.kind != "function":
            return

        unused_names = sorted(set(scope.assigned) - set(scope.used))
        for name in unused_names:
            if is_ignored_variable_name(name):
                continue
            line, safe = scope.assigned[name]
            self.unused_locals.append((line, name, safe))

    def _apply_unresolved_attribute_matches(self):
        for attr_name in sorted(self.unresolved_attribute_calls):
            for class_id, methods in self.index.class_methods.items():
                for method_id in methods.get(attr_name, set()):
                    if method_id not in self.used_symbols:
                        self.potential_symbol_reasons.setdefault(method_id, set()).add(
                            "unresolved_attribute_call"
                        )

    def _visit_annotation(self, node: ast.AST) -> None:
        self.annotation_stack.append(True)
        self.visit(node)
        self.annotation_stack.pop()

    def _is_dynamic_call(self, node: ast.Call) -> bool:
        if isinstance(node.func, ast.Name):
            return node.func.id in DYNAMIC_CALL_NAMES
        if isinstance(node.func, ast.Attribute):
            chain = attribute_chain(node.func)
            if not chain:
                return False
            if chain[-1] in DYNAMIC_IMPORT_FUNCS and chain[0] in DYNAMIC_IMPORT_MODULES:
                return True
        return False


def is_ignored_variable_name(name: str) -> bool:
    return name in {"self", "cls"} or name.startswith("_")


def extract_target_names(target: ast.AST) -> List[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: List[str] = []
        for element in target.elts:
            names.extend(extract_target_names(element))
        return names
    if isinstance(target, ast.Starred):
        return extract_target_names(target.value)
    return []


def is_side_effect_free_expr(node: Optional[ast.AST]) -> bool:
    if node is None:
        return True
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return is_side_effect_free_expr(node.value)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(is_side_effect_free_expr(el) for el in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            is_side_effect_free_expr(k) and is_side_effect_free_expr(v)
            for k, v in zip(node.keys, node.values)
        )
    if isinstance(node, ast.UnaryOp):
        return is_side_effect_free_expr(node.operand)
    if isinstance(node, ast.BinOp):
        return is_side_effect_free_expr(node.left) and is_side_effect_free_expr(node.right)
    return False


def _merge_contexts(target: Dict[str, Set[str]], source: Dict[str, Set[str]]) -> None:
    for key, values in source.items():
        target.setdefault(key, set()).update(values)
