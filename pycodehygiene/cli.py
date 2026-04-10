from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from pycodehygiene.report import ReportGenerator
from pycodehygiene.scanner import scan_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="py-code-hygiene",
        description="Unified Python code hygiene scanner (dead code, duplicates, complexity).",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan a project and generate JSON/HTML reports")
    scan_parser.add_argument("path", nargs="?", default=".", help="Target project path (default: current directory)")
    scan_parser.add_argument("--html-output", "-o", default="pycodehygiene_report.html", help="Output HTML report path")
    scan_parser.add_argument("--json-output", default="pycodehygiene_report.json", help="Output JSON report path")
    scan_parser.add_argument("--config", default=None, help="Path to pycodehygiene.toml")
    scan_parser.add_argument("--include", action="append", default=None, help="Include glob pattern (repeatable)")
    scan_parser.add_argument("--exclude", action="append", default=None, help="Exclude glob pattern (repeatable)")
    scan_parser.add_argument("--min-dup-lines", type=int, default=None, help="Minimum lines for duplicate analysis")
    scan_parser.add_argument("--dup-threshold", type=float, default=None, help="Near-duplicate similarity threshold (0.5-1.0)")
    scan_parser.add_argument("--complexity-threshold", type=int, default=None, help="Complexity hotspot threshold")
    scan_parser.add_argument("--no-html", action="store_true", help="Skip HTML report generation")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command != "scan":
        parser.error("Unsupported command")

    target = Path(args.path).resolve()
    include = _flatten_repeatable(args.include)
    exclude = _flatten_repeatable(args.exclude)

    report = scan_project(
        target,
        config_path=Path(args.config).resolve() if args.config else None,
        include=include,
        exclude=exclude,
        duplicate_min_lines=args.min_dup_lines,
        duplicate_similarity_threshold=args.dup_threshold,
        complexity_threshold=args.complexity_threshold,
    )

    json_path = Path(args.json_output)
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if not args.no_html:
        ReportGenerator().generate(args.html_output, report)

    summary = report.get("summary", {})
    analyzer_counts = summary.get("by_analyzer", {}) if isinstance(summary, dict) else {}
    print(f"[+] Target: {target}")
    print(f"[+] Files analyzed: {summary.get('files_analyzed', 0)}")
    print(f"[+] Findings: {summary.get('total_findings', 0)}")
    print(
        "    dead_code={dead} duplicates={dup} complexity={comp}".format(
            dead=analyzer_counts.get("dead_code", 0),
            dup=analyzer_counts.get("duplicates", 0),
            comp=analyzer_counts.get("complexity", 0),
        )
    )
    print(f"[+] JSON report: {json_path}")
    if not args.no_html:
        print(f"[+] HTML report: {args.html_output}")

    return 0


def _flatten_repeatable(values: Optional[List[str]]) -> Optional[List[str]]:
    if values is None:
        return None
    flattened = [value for value in values if value]
    return flattened or None


if __name__ == "__main__":
    raise SystemExit(main())
