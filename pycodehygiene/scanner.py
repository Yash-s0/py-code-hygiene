from __future__ import annotations

import platform
from collections import defaultdict
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
    minimum_confidence_to_report: Optional[str] = None,
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
        minimum_confidence_to_report=minimum_confidence_to_report,
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
    source_lines_by_file = {
        str(module_info.file_path): module_info.source.splitlines()
        for module_info in index.modules.values()
    }

    file_rows = [
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
    ]

    dead_total = int(dead_code.get("summary", {}).get("total", 0))
    duplicate_total = len(duplicate_findings)
    complexity_total = len(complexity_findings)
    total_code_lines = sum(int(row.get("code_lines", 0)) for row in file_rows)
    finding_density = round((len(all_findings) * 1000.0) / total_code_lines, 2) if total_code_lines else 0.0
    confidence_breakdown = _confidence_breakdown(all_findings)
    priority_rows = _priority_rows(
        dead_findings=list(dead_code.get("findings", [])),
        duplicate_groups=list(duplicates.get("groups", [])),
        complexity_findings=complexity_findings,
        source_lines_by_file=source_lines_by_file,
    )

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
            "code_lines": total_code_lines,
            "parse_errors": len(index.parse_errors),
            "total_findings": len(all_findings),
            "finding_density_per_kloc": finding_density,
            "health_score": score,
            "by_analyzer": {
                "dead_code": dead_total,
                "duplicates": duplicate_total,
                "complexity": complexity_total,
            },
            "by_confidence": confidence_breakdown,
            "top_files": priority_rows[:20],
        },
        "files": file_rows,
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


def _confidence_breakdown(findings: List[Dict[str, object]]) -> Dict[str, int]:
    counts = {"high": 0, "medium": 0, "low": 0}
    for finding in findings:
        confidence = str(finding.get("confidence", "low"))
        if confidence in counts:
            counts[confidence] += 1
    return counts


def _priority_rows(
    *,
    dead_findings: List[Dict[str, object]],
    duplicate_groups: List[Dict[str, object]],
    complexity_findings: List[Dict[str, object]],
    source_lines_by_file: Dict[str, List[str]],
) -> List[Dict[str, object]]:
    rows: Dict[str, Dict[str, object]] = defaultdict(
        lambda: {
            "file": "",
            "total_findings": 0,
            "dead_code": 0,
            "duplicates": 0,
            "duplicate_instances": 0,
            "complexity": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "first_line": 0,
            "first_kind": "",
            "issues": [],
            "priority_score": 0.0,
        }
    )

    for finding in dead_findings:
        file_path = str(finding.get("file", ""))
        if not file_path:
            continue
        row = rows[file_path]
        row["file"] = file_path
        row["dead_code"] = int(row["dead_code"]) + 1
        row["total_findings"] = int(row["total_findings"]) + 1
        line = int(finding.get("line_start", 0))
        _update_first_location(row, line, "dead_code")
        _append_issue(
            row,
            {
                "analyzer": "dead_code",
                "category": str(finding.get("category", "unused")),
                "line": line,
                "confidence": str(finding.get("confidence", "low")),
                "symbol": str(finding.get("symbol", "")),
                "message": str(finding.get("message", "")),
                "code": _line_excerpt(source_lines_by_file, file_path, line),
            },
        )
        _inc_confidence(row, str(finding.get("confidence", "low")))

    for finding in complexity_findings:
        file_path = str(finding.get("file", ""))
        if not file_path:
            continue
        row = rows[file_path]
        row["file"] = file_path
        row["complexity"] = int(row["complexity"]) + 1
        row["total_findings"] = int(row["total_findings"]) + 1
        line = int(finding.get("line_start", 0))
        _update_first_location(row, line, "complexity")
        _append_issue(
            row,
            {
                "analyzer": "complexity",
                "category": str(finding.get("category", "complexity-hotspot")),
                "line": line,
                "confidence": str(finding.get("confidence", "medium")),
                "symbol": str(finding.get("symbol", "")),
                "message": str(finding.get("message", "")),
                "code": _line_excerpt(source_lines_by_file, file_path, line),
            },
        )
        _inc_confidence(row, str(finding.get("confidence", "low")))

    for group in duplicate_groups:
        confidence = str(group.get("confidence", "medium"))
        seen_files: set[str] = set()
        for item in group.get("items", []):
            if not isinstance(item, dict):
                continue
            file_path = str(item.get("file", ""))
            if not file_path:
                continue
            row = rows[file_path]
            row["file"] = file_path
            row["duplicate_instances"] = int(row["duplicate_instances"]) + 1
            line = int(item.get("line_start", 0))
            _update_first_location(row, line, "duplicates")
            _append_issue(
                row,
                {
                    "analyzer": "duplicates",
                    "category": f"duplicate-{group.get('kind', 'near')}",
                    "line": line,
                    "confidence": confidence,
                    "symbol": str(item.get("name", "")),
                    "message": str(group.get("reason", "Duplicate pattern detected")),
                    "code": _short_snippet(str(item.get("snippet", ""))),
                },
            )
            if file_path in seen_files:
                continue
            seen_files.add(file_path)
            row["duplicates"] = int(row["duplicates"]) + 1
            row["total_findings"] = int(row["total_findings"]) + 1
            _inc_confidence(row, confidence)

    output: List[Dict[str, object]] = []
    for row in rows.values():
        high = int(row["high"])
        medium = int(row["medium"])
        low = int(row["low"])
        duplicates = int(row["duplicates"])
        complexity = int(row["complexity"])
        issues = list(row.get("issues", []))
        issues.sort(
            key=lambda issue: (
                int(issue.get("line", 0)),
                str(issue.get("analyzer", "")),
                str(issue.get("category", "")),
            )
        )
        row["issues_total"] = len(issues)
        row["issues"] = issues[:25]
        row["priority_score"] = round((high * 3.0) + (medium * 2.0) + low + (duplicates * 1.5) + complexity, 2)
        output.append(row)

    output.sort(
        key=lambda row: (
            float(row.get("priority_score", 0.0)),
            int(row.get("total_findings", 0)),
            int(row.get("high", 0)),
        ),
        reverse=True,
    )
    return output


def _inc_confidence(row: Dict[str, object], confidence: str) -> None:
    if confidence in {"high", "medium", "low"}:
        row[confidence] = int(row[confidence]) + 1


def _append_issue(row: Dict[str, object], issue: Dict[str, object]) -> None:
    issues = row.get("issues")
    if isinstance(issues, list):
        issues.append(issue)


def _update_first_location(row: Dict[str, object], line: int, kind: str) -> None:
    if line <= 0:
        return
    current = int(row.get("first_line", 0))
    if current == 0 or line < current:
        row["first_line"] = line
        row["first_kind"] = kind


def _line_excerpt(source_lines_by_file: Dict[str, List[str]], file_path: str, line: int) -> str:
    if line <= 0:
        return ""
    lines = source_lines_by_file.get(file_path)
    if not lines:
        return ""
    index = line - 1
    if index < 0 or index >= len(lines):
        return ""
    return lines[index].strip()


def _short_snippet(snippet: str) -> str:
    if not snippet:
        return ""
    lines = [line.rstrip() for line in snippet.splitlines() if line.strip()]
    compact = " ".join(lines[:3]).strip()
    if len(compact) > 240:
        return compact[:237].rstrip() + "..."
    return compact
