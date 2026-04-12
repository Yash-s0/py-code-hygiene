from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, List, Optional, Set

from pycodehygiene.config import Config
from pycodehygiene.discovery import DiscoveryResult, _is_test_file
from pycodehygiene.models import CodeBlock, FileStat, ImportBinding, ModuleInfo, RepoIndex, Symbol
from pycodehygiene.utils import count_lines, read_file


ENTRYPOINT_NAMES = {"main", "cli", "run"}
SIDE_EFFECT_MODULE_HINTS = {"registry", "registries", "signal", "signals", "plugin", "plugins", "hook", "hooks"}


DECISION_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.ExceptHandler,
    ast.BoolOp,
    ast.IfExp,
)


def build_index(discovery: DiscoveryResult, config: Config) -> RepoIndex:
    index = RepoIndex(root=discovery.root)

    for file_path in discovery.python_files:
        source = read_file(file_path)
        line_stats = count_lines(source)

        module_name = module_name_from_path(file_path, discovery.root)
        package_name = package_name_from_module(module_name, file_path)

        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as exc:
            index.parse_errors[str(file_path)] = str(exc)
            index.file_stats[str(file_path)] = FileStat(
                file=str(file_path),
                total_lines=line_stats["total"],
                code_lines=line_stats["code"],
                comment_lines=line_stats["comment"],
                blank_lines=line_stats["blank"],
                function_count=0,
                class_count=0,
            )
            continue

        module_info = ModuleInfo(
            file_path=file_path,
            module=module_name,
            package=package_name,
            tree=tree,
            source=source,
        )
        module_info.is_test_file = _is_test_file(file_path)
        index.modules[module_name] = module_info

        collector = IndexCollector(index, module_info, config)
        collector.visit(tree)

        index.file_stats[str(file_path)] = FileStat(
            file=str(file_path),
            total_lines=line_stats["total"],
            code_lines=line_stats["code"],
            comment_lines=line_stats["comment"],
            blank_lines=line_stats["blank"],
            function_count=collector.function_count,
            class_count=collector.class_count,
        )

    _apply_exports(index)
    _resolve_import_targets(index)
    _mark_import_bindings_reused_by_other_modules(index)
    _mark_reexports_in_init(index)
    _mark_public_api(index, config)
    return index


def module_name_from_path(file_path: Path, root: Path) -> str:
    rel = file_path.relative_to(root)
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else "__root__"


def package_name_from_module(module_name: str, file_path: Path) -> str:
    if file_path.name == "__init__.py":
        return module_name
    if "." not in module_name:
        return ""
    return module_name.rsplit(".", 1)[0]


class IndexCollector(ast.NodeVisitor):
    def __init__(self, index: RepoIndex, module_info: ModuleInfo, config: Config):
        self.index = index
        self.module_info = module_info
        self.config = config
        self.qualname_stack: List[str] = []
        self.class_symbol_stack: List[str] = []
        self.container_stack: List[str] = []
        self.type_checking_stack: List[bool] = [False]
        self.source_lines = module_info.source.splitlines()
        self.function_count = 0
        self.class_count = 0

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            bound_name = alias.asname if alias.asname else alias.name.split(".")[0]
            report_name = alias.asname if alias.asname else alias.name
            symbol_id = build_symbol_id(
                self.module_info.module,
                "import",
                f"{report_name}:{node.lineno}",
                node.lineno,
            )

            binding = ImportBinding(
                symbol_id=symbol_id,
                module=self.module_info.module,
                file=str(self.module_info.file_path),
                line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                bound_name=bound_name,
                report_name=report_name,
                imported_module=alias.name,
                imported_name=None,
                has_alias=bool(alias.asname),
                is_star=False,
                is_top_level=not self.container_stack,
                in_type_checking=self._in_type_checking(),
            )
            self._register_import(binding)

            if binding.imported_name is None:
                self.module_info.module_aliases.setdefault(bound_name, set()).add(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        resolved_module = resolve_import_from_module(
            self.module_info.package,
            node.level,
            node.module,
        )

        for alias in node.names:
            is_star = alias.name == "*"
            bound_name = alias.asname if alias.asname else alias.name
            report_name = alias.asname if alias.asname else alias.name
            symbol_id = build_symbol_id(
                self.module_info.module,
                "import",
                f"{report_name}:{node.lineno}",
                node.lineno,
            )

            binding = ImportBinding(
                symbol_id=symbol_id,
                module=self.module_info.module,
                file=str(self.module_info.file_path),
                line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                bound_name=bound_name,
                report_name=report_name,
                imported_module=resolved_module,
                imported_name=None if is_star else alias.name,
                has_alias=bool(alias.asname),
                is_star=is_star,
                is_top_level=not self.container_stack,
                in_type_checking=self._in_type_checking(),
            )
            if node.module == "__future__":
                binding.reasons.add("future_import")
            self._register_import(binding)

        if node.module == "__future__":
            for alias in node.names:
                if alias.name == "annotations":
                    self.module_info.future_annotations = True

    def visit_Assign(self, node: ast.Assign):
        if not self.container_stack:
            self._collect_module_exports(node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        if not self.container_stack:
            self._collect_module_exports([node.target], node.value)
        if node.annotation:
            self._note_annotation(node.annotation)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign):
        if not self.container_stack and isinstance(node.target, ast.Name) and node.target.id == "__all__":
            values = extract_string_constants(node.value)
            if values:
                self.module_info.exports.update(values)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._visit_function(node)

    def _visit_function(self, node: ast.AST):
        name = node.name
        qualname = ".".join(self.qualname_stack + [name]) if self.qualname_stack else name
        is_method = bool(self.container_stack and self.container_stack[-1] == "class")
        class_symbol_id = self.class_symbol_stack[-1] if is_method and self.class_symbol_stack else None

        symbol_id = build_symbol_id(self.module_info.module, "function", qualname, node.lineno)
        decorators = [decorator_name(dec) for dec in node.decorator_list]

        symbol = Symbol(
            symbol_id=symbol_id,
            kind="function",
            module=self.module_info.module,
            qualname=qualname,
            name=name,
            file=str(self.module_info.file_path),
            line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            decorators=decorators,
            is_method=is_method,
            class_symbol_id=class_symbol_id,
            in_type_checking=self._in_type_checking(),
            in_test_file=self.module_info.is_test_file,
        )

        if name in ENTRYPOINT_NAMES or name.startswith("test_"):
            symbol.reasons.add("entrypoint_name")

        if decorators:
            symbol.reasons.add("decorated")
            if any(self._decorator_matches_known(d) for d in decorators):
                symbol.reasons.add("framework_decorator")

        if self.module_info.is_test_file:
            symbol.reasons.add("test_file")

        top_level = not self.container_stack
        self._register_symbol(symbol, top_level=top_level)

        complexity = cyclomatic_complexity(node)
        self._add_code_block(symbol=symbol, complexity=complexity, is_method=is_method)
        self.function_count += 1

        self.qualname_stack.append(name)
        self.container_stack.append("function")

        for arg in node.args.args + node.args.kwonlyargs + getattr(node.args, "posonlyargs", []):
            if arg.annotation:
                self._note_annotation(arg.annotation)
        if node.returns:
            self._note_annotation(node.returns)

        self.generic_visit(node)

        self.container_stack.pop()
        self.qualname_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef):
        name = node.name
        qualname = ".".join(self.qualname_stack + [name]) if self.qualname_stack else name

        symbol_id = build_symbol_id(self.module_info.module, "class", qualname, node.lineno)
        decorators = [decorator_name(dec) for dec in node.decorator_list]
        bases = [decorator_name(base) for base in node.bases]

        symbol = Symbol(
            symbol_id=symbol_id,
            kind="class",
            module=self.module_info.module,
            qualname=qualname,
            name=name,
            file=str(self.module_info.file_path),
            line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            decorators=decorators,
            bases=bases,
            in_type_checking=self._in_type_checking(),
            in_test_file=self.module_info.is_test_file,
        )

        if decorators:
            symbol.reasons.add("decorated")
            if any(self._decorator_matches_known(d) for d in decorators):
                symbol.reasons.add("framework_decorator")

        if any(self._base_matches_known(b) for b in bases):
            symbol.reasons.add("known_base_class")

        if self.module_info.is_test_file:
            symbol.reasons.add("test_file")

        top_level = not self.container_stack
        self._register_symbol(symbol, top_level=top_level)
        self.index.class_bases[symbol_id] = bases
        self.class_count += 1

        class_complexity = max(
            1,
            sum(cyclomatic_complexity(stmt) for stmt in node.body if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))),
        )
        self._add_code_block(symbol=symbol, complexity=class_complexity, is_method=False)

        self.qualname_stack.append(name)
        self.container_stack.append("class")
        self.class_symbol_stack.append(symbol_id)

        self.generic_visit(node)

        self.class_symbol_stack.pop()
        self.container_stack.pop()
        self.qualname_stack.pop()

    def visit_If(self, node: ast.If):
        if is_type_checking_test(node.test):
            self.type_checking_stack.append(True)
            for stmt in node.body:
                self.visit(stmt)
            self.type_checking_stack.pop()
            for stmt in node.orelse:
                self.visit(stmt)
        else:
            self.generic_visit(node)

    def _add_code_block(self, symbol: Symbol, complexity: int, is_method: bool) -> None:
        source = ""
        if symbol.line and symbol.end_line and symbol.end_line >= symbol.line:
            start = max(symbol.line - 1, 0)
            end = min(symbol.end_line, len(self.source_lines))
            source = "\n".join(self.source_lines[start:end])

        self.index.code_blocks.append(
            CodeBlock(
                block_id=symbol.symbol_id,
                kind=symbol.kind,
                module=symbol.module,
                qualname=symbol.qualname,
                name=symbol.name,
                file=symbol.file,
                line_start=symbol.line,
                line_end=symbol.end_line,
                lines=max(0, symbol.end_line - symbol.line + 1),
                source=source,
                complexity=complexity,
                is_method=is_method,
            )
        )

    def _register_symbol(self, symbol: Symbol, top_level: bool = False) -> None:
        self.index.symbols[symbol.symbol_id] = symbol

        self.index.symbol_ids_by_module_and_name.setdefault(symbol.module, {}).setdefault(
            symbol.name, set()
        ).add(symbol.symbol_id)

        if symbol.kind == "function":
            self.index.function_lookup[(symbol.module, symbol.qualname, symbol.line)] = symbol.symbol_id
            if symbol.is_method and symbol.class_symbol_id:
                self.index.class_methods.setdefault(symbol.class_symbol_id, {}).setdefault(
                    symbol.name, set()
                ).add(symbol.symbol_id)

        if symbol.kind == "class":
            self.index.class_lookup[(symbol.module, symbol.qualname, symbol.line)] = symbol.symbol_id

        if top_level:
            self.index.top_level_defs_by_module.setdefault(symbol.module, {}).setdefault(
                symbol.name, set()
            ).add(symbol.symbol_id)

    def _register_import(self, binding: ImportBinding) -> None:
        self.index.imports[binding.symbol_id] = binding
        self.module_info.import_ids.append(binding.symbol_id)
        self.module_info.import_bindings_by_name.setdefault(binding.bound_name, []).append(
            binding.symbol_id
        )

    def _collect_module_exports(self, targets: List[ast.AST], value: Optional[ast.AST]):
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                values = extract_string_constants(value)
                if values:
                    self.module_info.exports.update(values)

    def _note_annotation(self, node: ast.AST) -> None:
        if self.module_info.future_annotations:
            self.module_info.has_string_annotations = True
            return
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            self.module_info.has_string_annotations = True

    def _decorator_matches_known(self, name: str) -> bool:
        tail = name.split(".")[-1]
        return tail in self.config.known_decorators or name in self.config.known_decorators

    def _base_matches_known(self, name: str) -> bool:
        tail = name.split(".")[-1]
        return tail in self.config.known_base_classes or name in self.config.known_base_classes

    def _in_type_checking(self) -> bool:
        return bool(self.type_checking_stack and self.type_checking_stack[-1])


def cyclomatic_complexity(node: ast.AST) -> int:
    complexity = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.ExceptHandler)):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += max(1, len(child.values) - 1)
        elif isinstance(child, ast.Try):
            complexity += len(child.handlers)
    return complexity


def _apply_exports(index: RepoIndex) -> None:
    for module_name, module_info in index.modules.items():
        if not module_info.exports:
            continue

        for exported_name in module_info.exports:
            for symbol_id in index.top_level_defs_by_module.get(module_name, {}).get(
                exported_name, set()
            ):
                index.symbols[symbol_id].reasons.add("exported_in_all")

            for import_id in module_info.import_bindings_by_name.get(exported_name, []):
                index.imports[import_id].reasons.add("exported_in_all")


def _resolve_import_targets(index: RepoIndex) -> None:
    for binding in index.imports.values():
        if _module_name_has_side_effect_hint(binding.imported_module):
            binding.reasons.add("side_effect_module_hint")

        if binding.is_star:
            binding.reasons.add("star_import")
            continue

        if binding.imported_name:
            target_ids = index.top_level_defs_by_module.get(binding.imported_module, {}).get(
                binding.imported_name, set()
            )
            if target_ids:
                binding.target_symbol_ids.update(target_ids)

        if binding.imported_name is None and not binding.has_alias:
            binding.reasons.add("side_effect_import")


def _mark_import_bindings_reused_by_other_modules(index: RepoIndex) -> None:
    direct_consumers: Dict[tuple, Set[str]] = {}
    star_consumers: Dict[str, Set[str]] = {}

    for binding in index.imports.values():
        if binding.imported_name:
            key = (binding.imported_module, binding.imported_name)
            direct_consumers.setdefault(key, set()).add(binding.module)
        elif binding.is_star:
            star_consumers.setdefault(binding.imported_module, set()).add(binding.module)

    for binding in index.imports.values():
        if not binding.is_top_level:
            continue

        consumer_modules = direct_consumers.get((binding.module, binding.bound_name), set())
        if any(consumer != binding.module for consumer in consumer_modules):
            binding.reasons.add("imported_by_other_module")

        star_modules = star_consumers.get(binding.module, set())
        if binding.bound_name and not binding.bound_name.startswith("_"):
            if any(consumer != binding.module for consumer in star_modules):
                binding.reasons.add("imported_by_star")


def _mark_reexports_in_init(index: RepoIndex) -> None:
    for module_name, module_info in index.modules.items():
        if module_info.file_path.name != "__init__.py":
            continue

        module_info.flags.add("package_init")
        for import_id in module_info.import_ids:
            binding = index.imports[import_id]
            binding.reasons.add("reexport_in_init")
            for symbol_id in binding.target_symbol_ids:
                index.symbols[symbol_id].reasons.add("reexport_in_init")


def _mark_public_api(index: RepoIndex, config: Config) -> None:
    if not config.treat_public_api_as_live:
        return

    for symbol in index.symbols.values():
        if symbol.is_method:
            continue
        if symbol.name.startswith("_"):
            continue
        symbol.reasons.add("public_api")


def resolve_import_from_module(package: str, level: int, module: Optional[str]) -> str:
    if level <= 0:
        return module or ""

    package_parts = package.split(".") if package else []
    up_levels = max(level - 1, 0)

    if up_levels and package_parts:
        package_parts = package_parts[:-up_levels] if up_levels <= len(package_parts) else []

    if module:
        package_parts.extend(module.split("."))

    return ".".join(part for part in package_parts if part)


def _module_name_has_side_effect_hint(module_name: str) -> bool:
    if not module_name:
        return False
    parts = module_name.split(".")
    return any(part in SIDE_EFFECT_MODULE_HINTS for part in parts)


def decorator_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        return decorator_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        chain = attribute_chain(node)
        if chain:
            return ".".join(chain)
    return ""


def attribute_chain(node: ast.AST) -> Optional[List[str]]:
    parts: List[str] = []
    current = node

    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value

    if isinstance(current, ast.Name):
        parts.append(current.id)
        return list(reversed(parts))

    return None


def extract_string_constants(value: Optional[ast.AST]) -> Set[str]:
    if value is None:
        return set()
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return {value.value}
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        result: Set[str] = set()
        for element in value.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                result.add(element.value)
        return result
    if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
        return extract_string_constants(value.left) | extract_string_constants(value.right)
    return set()


def build_symbol_id(module: str, kind: str, qualname: str, line: int) -> str:
    return f"{module}|{kind}|{qualname}|{line}"


def is_type_checking_test(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "TYPE_CHECKING"
    if isinstance(node, ast.Attribute):
        chain = attribute_chain(node)
        if not chain:
            return False
        return chain[-1] == "TYPE_CHECKING"
    return False
