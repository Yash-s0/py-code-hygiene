from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class ModuleInfo:
    file_path: Path
    module: str
    package: str
    tree: object
    source: str
    exports: Set[str] = field(default_factory=set)
    future_annotations: bool = False
    has_string_annotations: bool = False
    import_ids: List[str] = field(default_factory=list)
    import_bindings_by_name: Dict[str, List[str]] = field(default_factory=dict)
    module_aliases: Dict[str, Set[str]] = field(default_factory=dict)
    flags: Set[str] = field(default_factory=set)
    is_test_file: bool = False


@dataclass
class Symbol:
    symbol_id: str
    kind: str
    module: str
    qualname: str
    name: str
    file: str
    line: int
    end_line: int
    decorators: List[str] = field(default_factory=list)
    bases: List[str] = field(default_factory=list)
    is_method: bool = False
    class_symbol_id: Optional[str] = None
    in_type_checking: bool = False
    in_test_file: bool = False
    reasons: Set[str] = field(default_factory=set)

    @property
    def is_private(self) -> bool:
        return self.name.startswith("_") and not self.name.startswith("__")

    @property
    def is_magic(self) -> bool:
        return self.name.startswith("__") and self.name.endswith("__")


@dataclass
class ImportBinding:
    symbol_id: str
    module: str
    file: str
    line: int
    end_line: int
    bound_name: str
    report_name: str
    imported_module: str
    imported_name: Optional[str]
    has_alias: bool
    is_star: bool = False
    in_type_checking: bool = False
    reasons: Set[str] = field(default_factory=set)
    target_symbol_ids: Set[str] = field(default_factory=set)


@dataclass
class CodeBlock:
    block_id: str
    kind: str
    module: str
    qualname: str
    name: str
    file: str
    line_start: int
    line_end: int
    lines: int
    source: str
    complexity: int
    is_method: bool = False


@dataclass
class FileStat:
    file: str
    total_lines: int
    code_lines: int
    comment_lines: int
    blank_lines: int
    function_count: int
    class_count: int


@dataclass
class Finding:
    finding_id: str
    category: str
    kind: str
    confidence: str
    risk: str
    file: str
    line_start: int
    line_end: int
    symbol: str
    qualname: str
    message: str
    evidence: List[str]
    suggested_action: str
    autofix_allowed: bool
    suppressed: bool = False
    suppression_reason: Optional[str] = None


@dataclass
class RepoIndex:
    root: Path
    modules: Dict[str, ModuleInfo] = field(default_factory=dict)
    symbols: Dict[str, Symbol] = field(default_factory=dict)
    imports: Dict[str, ImportBinding] = field(default_factory=dict)
    top_level_defs_by_module: Dict[str, Dict[str, Set[str]]] = field(default_factory=dict)
    symbol_ids_by_module_and_name: Dict[str, Dict[str, Set[str]]] = field(default_factory=dict)
    function_lookup: Dict[Tuple[str, str, int], str] = field(default_factory=dict)
    class_lookup: Dict[Tuple[str, str, int], str] = field(default_factory=dict)
    class_methods: Dict[str, Dict[str, Set[str]]] = field(default_factory=dict)
    class_bases: Dict[str, List[str]] = field(default_factory=dict)
    code_blocks: List[CodeBlock] = field(default_factory=list)
    file_stats: Dict[str, FileStat] = field(default_factory=dict)
    parse_errors: Dict[str, str] = field(default_factory=dict)


@dataclass
class UsageSummary:
    used_symbols: Set[str] = field(default_factory=set)
    used_imports: Set[str] = field(default_factory=set)
    symbol_contexts: Dict[str, Set[str]] = field(default_factory=dict)
    import_contexts: Dict[str, Set[str]] = field(default_factory=dict)
    potential_symbol_reasons: Dict[str, Set[str]] = field(default_factory=dict)
    unused_locals: Dict[str, List[Tuple[int, str, bool]]] = field(default_factory=dict)


@dataclass
class ReachabilitySummary:
    unreachable: Dict[str, List[Tuple[int, int, str]]] = field(default_factory=dict)


@dataclass
class Report:
    root: str
    findings: List[Finding]
    suppressed_findings: List[Finding]
    summary: Dict[str, object]
    config: Dict[str, object]
