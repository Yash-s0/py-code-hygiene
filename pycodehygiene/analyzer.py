from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from pycodehygiene.config import Config, config_to_dict, load_config
from pycodehygiene.discovery import DiscoveryResult, discover_python_files
from pycodehygiene.indexer import build_index
from pycodehygiene.models import Finding, RepoIndex, Report
from pycodehygiene.reference_graph import ReferenceGraphBuilder
from pycodehygiene.reachability import ReachabilityAnalyzer
from pycodehygiene.rules import RuleEngine
from pycodehygiene.suppressions import build_suppressions


class DeadCodeAnalyzer:
    def __init__(self, root: Path | str, config_path: Optional[str] = None, config: Optional[Config] = None):
        self.root = Path(root)
        self.config = config or load_config(self.root, Path(config_path) if config_path else None)
        self.report: Optional[Report] = None
        self.discovery: Optional[DiscoveryResult] = None
        self.index: Optional[RepoIndex] = None

    def scan(self) -> None:
        discovery = discover_python_files(self.root, self.config)
        index = build_index(discovery, self.config)
        self.discovery = discovery
        self.index = index

        report_dict = analyze_dead_code(index=index, discovery=discovery, config=self.config)

        self.report = Report(
            root=report_dict["root"],
            findings=[_dict_to_finding(item) for item in report_dict["findings"]],
            suppressed_findings=[_dict_to_finding(item) for item in report_dict["suppressed_findings"]],
            summary=report_dict["summary"],
            config=report_dict["config"],
        )

    def get_report(self) -> Dict[str, object]:
        if self.report is None or self.discovery is None or self.index is None:
            raise RuntimeError("scan() must be called before get_report()")
        return analyze_dead_code(index=self.index, discovery=self.discovery, config=self.config)


def analyze_dead_code(*, index: RepoIndex, discovery: DiscoveryResult, config: Config) -> Dict[str, object]:
    usage = ReferenceGraphBuilder(index, config).build()
    reachability = ReachabilityAnalyzer(index).build()
    suppressions = build_suppressions(discovery.python_files)

    findings, suppressed = RuleEngine(
        index=index,
        usage=usage,
        reachability=reachability,
        config=config,
        suppressions=suppressions,
    ).run()

    summary = build_summary(findings, suppressed)
    grouped = group_findings(findings)

    report_dict = {
        "root": str(discovery.root),
        "summary": summary,
        "config": config_to_dict(config),
        "findings": [finding_to_dict(f) for f in findings],
        "suppressed_findings": [finding_to_dict(f) for f in suppressed],
        "grouped": grouped,
        "high_confidence": grouped["high_confidence"],
        "potentially_used": grouped["potentially_used"],
        "unreachable_code": grouped["unreachable_code"],
        "counts": grouped["counts"],
        "generated_at": datetime.now(timezone.utc).astimezone().strftime("%b %d, %Y %H:%M %Z"),
    }
    return report_dict


def build_summary(findings: List[Finding], suppressed: List[Finding]) -> Dict[str, object]:
    summary: Dict[str, object] = {
        "total": len(findings),
        "suppressed": len(suppressed),
        "by_confidence": {"high": 0, "medium": 0, "low": 0},
        "by_category": {},
    }

    for finding in findings:
        summary["by_confidence"][finding.confidence] = (
            summary["by_confidence"].get(finding.confidence, 0) + 1
        )
        summary["by_category"].setdefault(finding.category, 0)
        summary["by_category"][finding.category] += 1

    return summary


def finding_to_dict(finding: Finding) -> Dict[str, object]:
    return {
        "id": finding.finding_id,
        "category": finding.category,
        "kind": finding.kind,
        "confidence": finding.confidence,
        "risk": finding.risk,
        "file": finding.file,
        "line_start": finding.line_start,
        "line_end": finding.line_end,
        "symbol": finding.symbol,
        "qualname": finding.qualname,
        "message": finding.message,
        "evidence": finding.evidence,
        "suggested_action": finding.suggested_action,
        "autofix_allowed": finding.autofix_allowed,
        "suppressed": finding.suppressed,
        "suppression_reason": finding.suppression_reason,
        "analyzer": "dead_code",
    }


def group_findings(findings: List[Finding]) -> Dict[str, object]:
    high_imports: Dict[str, List[tuple]] = {}
    potential_imports: Dict[str, List[tuple]] = {}

    high_functions: List[tuple] = []
    potential_functions: List[tuple] = []

    high_classes: List[tuple] = []
    potential_classes: List[tuple] = []

    high_variables: Dict[str, List[tuple]] = {}
    potential_variables: Dict[str, List[tuple]] = {}

    unreachable: Dict[str, List[tuple]] = {}

    for finding in findings:
        if finding.category == "unreachable":
            unreachable.setdefault(finding.file, []).append(
                (finding.line_start, finding.message or "unreachable")
            )
            continue

        if finding.category == "unused-import":
            if finding.confidence == "high":
                high_imports.setdefault(finding.file, []).append((finding.symbol, finding.line_start))
            else:
                potential_imports.setdefault(finding.file, []).append(
                    (finding.symbol, finding.line_start, "; ".join(finding.evidence) if finding.evidence else "")
                )
            continue

        if finding.category in {"unused-private-function", "unused-public-symbol"} and finding.kind == "function":
            if finding.confidence == "high":
                high_functions.append((finding.file, finding.line_start, finding.symbol))
            else:
                potential_functions.append(
                    (finding.file, finding.line_start, finding.symbol, "; ".join(finding.evidence))
                )
            continue

        if finding.category in {"unused-private-class", "unused-public-symbol"} and finding.kind == "class":
            if finding.confidence == "high":
                high_classes.append((finding.file, finding.line_start, finding.symbol))
            else:
                potential_classes.append(
                    (finding.file, finding.line_start, finding.symbol, "; ".join(finding.evidence))
                )
            continue

        if finding.category == "unused-local":
            target = high_variables if finding.confidence == "high" else potential_variables
            target.setdefault(finding.file, []).append((finding.line_start, finding.symbol))
            continue

    for mapping in (high_imports, potential_imports):
        for file, items in mapping.items():
            mapping[file] = sorted(items, key=lambda item: (item[1], item[0]))
    high_functions.sort(key=lambda item: (item[0], item[1], item[2]))
    high_classes.sort(key=lambda item: (item[0], item[1], item[2]))
    potential_functions.sort(key=lambda item: (item[0], item[1], item[2]))
    potential_classes.sort(key=lambda item: (item[0], item[1], item[2]))

    for mapping in (high_variables, potential_variables, unreachable):
        for file, items in mapping.items():
            mapping[file] = sorted(items, key=lambda item: (item[0], str(item[1])))

    high_counts = {
        "imports": sum(len(items) for items in high_imports.values()),
        "functions": len(high_functions),
        "classes": len(high_classes),
        "variables": sum(len(items) for items in high_variables.values()),
    }
    high_counts["total"] = sum(high_counts.values())

    potential_counts = {
        "imports": sum(len(items) for items in potential_imports.values()),
        "functions": len(potential_functions),
        "classes": len(potential_classes),
        "variables": sum(len(items) for items in potential_variables.values()),
    }
    potential_counts["total"] = sum(potential_counts.values())

    unreachable_count = sum(len(items) for items in unreachable.values())

    counts = {
        "high_confidence": high_counts,
        "potentially_used": potential_counts,
        "unreachable": unreachable_count,
        "total_findings": high_counts["total"] + potential_counts["total"] + unreachable_count,
    }

    return {
        "high_confidence": {
            "unused_imports": dict(sorted(high_imports.items())),
            "unused_functions": high_functions,
            "unused_classes": high_classes,
            "unused_variables": dict(sorted(high_variables.items())),
        },
        "potentially_used": {
            "unused_imports": dict(sorted(potential_imports.items())),
            "unused_functions": potential_functions,
            "unused_classes": potential_classes,
            "unused_variables": dict(sorted(potential_variables.items())),
        },
        "unreachable_code": dict(sorted(unreachable.items())),
        "counts": counts,
    }


def _dict_to_finding(data: Dict[str, object]) -> Finding:
    return Finding(
        finding_id=str(data.get("id", "")),
        category=str(data.get("category", "")),
        kind=str(data.get("kind", "")),
        confidence=str(data.get("confidence", "low")),
        risk=str(data.get("risk", "needs-review")),
        file=str(data.get("file", "")),
        line_start=int(data.get("line_start", 0)),
        line_end=int(data.get("line_end", 0)),
        symbol=str(data.get("symbol", "")),
        qualname=str(data.get("qualname", "")),
        message=str(data.get("message", "")),
        evidence=[str(item) for item in data.get("evidence", [])],
        suggested_action=str(data.get("suggested_action", "")),
        autofix_allowed=bool(data.get("autofix_allowed", False)),
        suppressed=bool(data.get("suppressed", False)),
        suppression_reason=(
            str(data.get("suppression_reason")) if data.get("suppression_reason") is not None else None
        ),
    )
