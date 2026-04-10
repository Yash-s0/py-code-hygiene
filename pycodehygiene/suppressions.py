from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

SUPPRESSION_RE = re.compile(r"pycodehygiene:\s*ignore(?:\[(?P<cats>[^\]]+)\])?")


@dataclass
class SuppressionIndex:
    file_level: Dict[str, Set[str]] = field(default_factory=dict)
    line_level: Dict[str, Dict[int, Set[str]]] = field(default_factory=dict)

    def is_suppressed(self, file_path: str, line: int, category_tags: Iterable[str]) -> Optional[str]:
        tags = {tag.lower() for tag in category_tags}
        file_tags = self.file_level.get(file_path, set())
        if file_tags and ("all" in file_tags or tags & file_tags):
            return "file-level suppression"

        line_tags = self.line_level.get(file_path, {}).get(line, set())
        if line_tags and ("all" in line_tags or tags & line_tags):
            return "inline suppression"

        return None


def _parse_categories(raw: Optional[str]) -> Set[str]:
    if not raw:
        return {"all"}
    categories = {item.strip().lower() for item in raw.split(",") if item.strip()}
    return categories or {"all"}


def _docstring_end_line(source: str) -> int:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0

    if not tree.body:
        return 0

    first = tree.body[0]
    if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
        if isinstance(first.value.value, str):
            return getattr(first, "end_lineno", first.lineno)
    return 0


def build_suppressions(file_paths: Iterable[Path]) -> SuppressionIndex:
    index = SuppressionIndex()

    for path in file_paths:
        file_path = str(path)
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue

        docstring_end = _docstring_end_line(source)
        lines = source.splitlines()
        seen_code = False
        pending_categories: Optional[Set[str]] = None

        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()

            if pending_categories and stripped and not stripped.startswith("#"):
                index.line_level.setdefault(file_path, {}).setdefault(lineno, set()).update(
                    pending_categories
                )
                pending_categories = None

            if not stripped:
                continue

            match = SUPPRESSION_RE.search(line)
            if match:
                categories = _parse_categories(match.group("cats"))
                code_part = line.split("#", 1)[0].strip()

                if code_part:
                    index.line_level.setdefault(file_path, {}).setdefault(lineno, set()).update(
                        categories
                    )
                else:
                    if not seen_code and lineno > docstring_end:
                        index.file_level.setdefault(file_path, set()).update(categories)
                    else:
                        pending_categories = categories
                continue

            if stripped.startswith("#"):
                continue

            if lineno > docstring_end:
                seen_code = True

    return index
