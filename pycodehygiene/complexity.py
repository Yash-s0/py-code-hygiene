from __future__ import annotations

from typing import Dict, List

from pycodehygiene.config import Config
from pycodehygiene.models import CodeBlock, RepoIndex


def analyze_complexity(index: RepoIndex, config: Config) -> Dict[str, object]:
    function_blocks = [
        block
        for block in index.code_blocks
        if block.kind == "function" and not _is_test_file(block.file, config)
    ]
    class_blocks = [
        block
        for block in index.code_blocks
        if block.kind == "class" and not _is_test_file(block.file, config)
    ]

    top_functions = sorted(function_blocks, key=lambda block: block.complexity, reverse=True)
    top_classes = sorted(class_blocks, key=lambda block: block.complexity, reverse=True)

    hotspots: List[Dict[str, object]] = []
    for block in top_functions:
        if block.complexity < config.complexity_threshold:
            continue

        confidence = "medium"
        if block.complexity >= config.complexity_threshold * 2:
            confidence = "high"

        hotspots.append(
            {
                "id": f"complexity:{block.file}:{block.line_start}:{block.qualname}",
                "analyzer": "complexity",
                "category": "complexity-hotspot",
                "confidence": confidence,
                "risk": "review-for-refactor",
                "file": block.file,
                "line_start": block.line_start,
                "line_end": block.line_end,
                "symbol": block.name,
                "qualname": block.qualname,
                "complexity": block.complexity,
                "message": "Cyclomatic complexity above configured threshold",
                "evidence": [
                    f"Complexity {block.complexity} exceeds threshold {config.complexity_threshold}",
                ],
                "suggested_action": "Consider splitting branches or extracting smaller functions",
            }
        )

    return {
        "summary": {
            "threshold": config.complexity_threshold,
            "functions_analyzed": len(function_blocks),
            "classes_analyzed": len(class_blocks),
            "hotspots": len(hotspots),
        },
        "hotspots": hotspots,
        "top_functions": [_block_to_row(block) for block in top_functions[: config.top_complexity_limit]],
        "top_classes": [_block_to_row(block) for block in top_classes[: config.top_complexity_limit]],
    }


def _block_to_row(block: CodeBlock) -> Dict[str, object]:
    return {
        "file": block.file,
        "name": block.name,
        "qualname": block.qualname,
        "line_start": block.line_start,
        "line_end": block.line_end,
        "complexity": block.complexity,
        "lines": block.lines,
        "kind": block.kind,
    }


def _is_test_file(file_path: str, config: Config) -> bool:
    if not config.ignore_test_files:
        return False
    normalized = file_path.replace("\\", "/")
    parts = normalized.split("/")
    name = parts[-1]
    return "tests" in parts or name.startswith("test_") or name.endswith("_test.py")
