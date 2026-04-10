from __future__ import annotations

import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from pycodehygiene.analyzer import analyze_dead_code
from pycodehygiene.complexity import analyze_complexity
from pycodehygiene.config import Config, apply_cli_overrides, config_to_dict, load_config
from pycodehygiene.discovery import discover_python_files
from pycodehygiene.duplicates import analyze_duplicates
from pycodehygiene.indexer import build_index


def scan_project(
    root: Path | str,
    *,
    config_path: Optional[Path] = None,
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
    duplicate_min_lines: Optional[int] = None,
    duplicate_similarity_threshold: Optional[float] = None,
    complexity_threshold: Optional[int] = None,
) -> Dict[str, object]:
    root_path = Path(root).resolve()

    config = load_config(root_path, config_path)
    apply_cli_overrides(
        config,
        include=include,
        exclude=exclude,
        duplicate_min_lines=duplicate_min_lines,
        duplicate_similarity_threshold=duplicate_similarity_threshold,
        complexity_threshold=complexity_threshold,
    )

    discovery = discover_python_files(root_path, config)
    index = build_index(discovery, config)

    dead_code = analyze_dead_code(index=index, discovery=discovery, config=config)
    duplicates = analyze_duplicates(index, config)
    complexity = analyze_complexity(index, config)

    duplicate_findings = _duplicate_groups_to_findings(duplicates.get("groups", []))
    complexity_findings = list(complexity.get("hotspots", []))
    all_findings = list(dead_code.get("findings", [])) + duplicate_findings + complexity_findings

    dead_total = int(dead_code.get("summary", {}).get("total", 0))
    duplicate_total = len(duplicate_findings)
    complexity_total = len(complexity_findings)

    score = _health_score(dead_code, duplicates, complexity)

    return {
        "meta": {
            "tool": "py-code-hygiene",
            "version": "0.1.0",
            "generated_at": datetime.now(timezone.utc).astimezone().strftime("%b %d, %Y %H:%M %Z"),
            "target": str(discovery.root),
            "python": platform.python_version(),
        },
        "config": config_to_dict(config),
        "summary": {
            "files_analyzed": len(index.file_stats),
            "parse_errors": len(index.parse_errors),
            "total_findings": len(all_findings),
            "health_score": score,
            "by_analyzer": {
                "dead_code": dead_total,
                "duplicates": duplicate_total,
                "complexity": complexity_total,
            },
        },
        "files": [
            {
                "file": stat.file,
                "total_lines": stat.total_lines,
                "code_lines": stat.code_lines,
                "comment_lines": stat.comment_lines,
                "blank_lines": stat.blank_lines,
                "function_count": stat.function_count,
                "class_count": stat.class_count,
            }
            for stat in sorted(index.file_stats.values(), key=lambda item: item.file)
        ],
        "parse_errors": index.parse_errors,
        "dead_code": dead_code,
        "duplicates": duplicates,
        "complexity": complexity,
        "findings": all_findings,
    }


def _duplicate_groups_to_findings(groups: List[Dict[str, object]]) -> List[Dict[str, object]]:
    findings: List[Dict[str, object]] = []
    for group in groups:
        items = group.get("items", [])
        if not items:
            continue

        head = items[0]
        kind = str(group.get("kind", "near"))
        category = f"duplicate-{kind}"

        findings.append(
            {
                "id": str(group.get("id", "duplicate-group")),
                "analyzer": "duplicates",
                "category": category,
                "kind": "code-block",
                "confidence": str(group.get("confidence", "medium")),
                "risk": "review-for-refactor",
                "file": str(head.get("file", "")),
                "line_start": int(head.get("line_start", 0)),
                "line_end": int(head.get("line_end", 0)),
                "symbol": str(head.get("name", "")),
                "qualname": str(head.get("qualname", "")),
                "message": "Duplicate code group detected",
                "evidence": [
                    str(group.get("reason", "Duplicate pattern detected")),
                    f"Group size: {group.get('count', 0)}",
                    f"Similarity: {group.get('similarity', 0)}",
                ],
                "suggested_action": "Extract shared helper or consolidate repeated logic",
                "group": group,
            }
        )
    return findings


def _health_score(
    dead_code: Dict[str, object],
    duplicates: Dict[str, object],
    complexity: Dict[str, object],
) -> int:
    dead_summary = dead_code.get("grouped", {}).get("counts", {}) if isinstance(dead_code.get("grouped"), dict) else {}

    high = int(dead_summary.get("high_confidence", {}).get("total", 0)) if isinstance(dead_summary.get("high_confidence"), dict) else 0
    potential = int(dead_summary.get("potentially_used", {}).get("total", 0)) if isinstance(dead_summary.get("potentially_used"), dict) else 0
    unreachable = int(dead_summary.get("unreachable", 0))

    duplicate_groups = int(duplicates.get("summary", {}).get("groups", 0)) if isinstance(duplicates.get("summary"), dict) else 0
    complexity_hotspots = int(complexity.get("summary", {}).get("hotspots", 0)) if isinstance(complexity.get("summary"), dict) else 0

    weighted = high + int(round(potential * 0.4)) + unreachable + duplicate_groups * 2 + complexity_hotspots

    if weighted == 0:
        return 100
    if weighted <= 5:
        return 95
    if weighted <= 15:
        return 86
    if weighted <= 30:
        return 72
    if weighted <= 60:
        return 55
    return max(10, 100 - weighted)
