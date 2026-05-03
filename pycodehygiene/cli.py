from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import List, Optional

from pycodehygiene.benchmarks import benchmark_table, run_benchmark, write_benchmark_json
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
    scan_parser.add_argument(
        "--min-confidence",
        choices=["low", "medium", "high"],
        default=None,
        help="Minimum confidence level for dead-code findings",
    )
    scan_parser.add_argument("--min-dup-lines", type=int, default=None, help="Minimum lines for duplicate analysis")
    scan_parser.add_argument("--dup-threshold", type=float, default=None, help="Near-duplicate similarity threshold (0.5-1.0)")
    scan_parser.add_argument("--complexity-threshold", type=int, default=None, help="Complexity hotspot threshold")
    scan_parser.add_argument("--no-html", action="store_true", help="Skip HTML report generation")
    scan_parser.add_argument("--no-json", action="store_true", help="Skip JSON report generation")

    benchmark_parser = subparsers.add_parser(
        "benchmark",
        help="Benchmark dead-code and duplicate analyzers (plus full scan) on a project",
    )
    benchmark_parser.add_argument("path", nargs="?", default=".", help="Target project path (default: current directory)")
    benchmark_parser.add_argument("--config", default=None, help="Path to pycodehygiene.toml")
    benchmark_parser.add_argument("--include", action="append", default=None, help="Include glob pattern (repeatable)")
    benchmark_parser.add_argument("--exclude", action="append", default=None, help="Exclude glob pattern (repeatable)")
    benchmark_parser.add_argument(
        "--min-confidence",
        choices=["low", "medium", "high"],
        default=None,
        help="Minimum confidence level for dead-code findings",
    )
    benchmark_parser.add_argument("--min-dup-lines", type=int, default=None, help="Minimum lines for duplicate analysis")
    benchmark_parser.add_argument("--dup-threshold", type=float, default=None, help="Near-duplicate similarity threshold (0.5-1.0)")
    benchmark_parser.add_argument("--complexity-threshold", type=int, default=None, help="Complexity hotspot threshold")
    benchmark_parser.add_argument("--runs", type=int, default=5, help="Benchmark runs after warmup (default: 5)")
    benchmark_parser.add_argument("--warmups", type=int, default=1, help="Warmup runs before sampling (default: 1)")
    benchmark_parser.add_argument(
        "--json-output",
        default=None,
        help="Optional benchmark JSON filename (written under reports/)",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    target = Path(args.path).resolve()
    include = _flatten_repeatable(args.include)
    exclude = _flatten_repeatable(args.exclude)

    if args.command == "benchmark":
        benchmark = run_benchmark(
            target,
            runs=args.runs,
            warmups=args.warmups,
            config_path=Path(args.config).resolve() if args.config else None,
            include=include,
            exclude=exclude,
            minimum_confidence_to_report=args.min_confidence,
            duplicate_min_lines=args.min_dup_lines,
            duplicate_similarity_threshold=args.dup_threshold,
            complexity_threshold=args.complexity_threshold,
        )
        print(f"[+] Benchmark target: {target}")
        print(
            "[+] Dataset shape: files={files} function_blocks={funcs}".format(
                files=benchmark.get("meta", {}).get("files_analyzed", 0),
                funcs=benchmark.get("meta", {}).get("function_blocks", 0),
            )
        )
        print(benchmark_table(benchmark))
        if args.json_output:
            benchmark_json = _resolve_reports_output_path(args.json_output)
            write_benchmark_json(benchmark_json, benchmark)
            print(f"[+] Benchmark JSON: {benchmark_json}")
        return 0

    if args.command != "scan":
        parser.error("Unsupported command")

    report = scan_project(
        target,
        config_path=Path(args.config).resolve() if args.config else None,
        include=include,
        exclude=exclude,
        minimum_confidence_to_report=args.min_confidence,
        duplicate_min_lines=args.min_dup_lines,
        duplicate_similarity_threshold=args.dup_threshold,
        complexity_threshold=args.complexity_threshold,
    )

    json_path: Optional[Path] = None
    if not args.no_json:
        json_path = _resolve_scan_output_path(target, args.json_output, ".json")
        json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    html_path: Optional[Path] = None
    if not args.no_html:
        html_path = _resolve_scan_output_path(target, args.html_output, ".html")
        ReportGenerator().generate(html_path, report)

    summary = report.get("summary", {})
    analyzer_counts = summary.get("by_analyzer", {}) if isinstance(summary, dict) else {}
    dead_summary = report.get("dead_code", {}).get("summary", {}) if isinstance(report.get("dead_code"), dict) else {}
    dead_suppressed = dead_summary.get("suppressed", 0) if isinstance(dead_summary, dict) else 0
    ai_meta = report.get("ai", {}) if isinstance(report.get("ai"), dict) else {}
    ai_enabled = bool(ai_meta.get("enabled", False))
    ai_provider = str(ai_meta.get("provider", "none"))
    ai_enriched_count = int(ai_meta.get("enriched_count", 0) or 0)
    ai_reason = str(ai_meta.get("reason", ""))
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
    print(f"    dead_code_suppressed={dead_suppressed} (use --min-confidence low to include low-confidence findings)")
    if ai_enabled:
        print(f"    ai_provider={ai_provider} ai_enriched={ai_enriched_count}")
    else:
        print("    ai_provider=none (working without AI; add key in this repo .env for better suggestions)")
    if ai_reason:
        print(f"    ai_note={ai_reason}")
    if json_path is not None:
        print(f"[+] JSON report: {json_path}")
    if html_path is not None:
        print(f"[+] HTML report: {html_path}")
    if json_path is None and html_path is None:
        print("[+] Output reports skipped (--no-json and --no-html)")

    return 0


def _flatten_repeatable(values: Optional[List[str]]) -> Optional[List[str]]:
    if values is None:
        return None
    flattened = [value for value in values if value]
    return flattened or None


def _resolve_scan_output_path(target: Path, raw_output: str, extension: str) -> Path:
    reports_dir = _reports_dir()
    requested = Path(raw_output)

    filename = requested.name
    if not filename:
        filename = f"{_target_report_stem(target)}{extension}"
    elif filename.startswith("pycodehygiene_report"):
        filename = f"{_target_report_stem(target)}{extension}"
    elif "." not in filename:
        filename = f"{filename}{extension}"
    return reports_dir / filename


def _resolve_reports_output_path(raw_output: str) -> Path:
    requested = Path(raw_output)
    return _reports_dir() / requested.name


def _reports_dir() -> Path:
    directory = Path(__file__).resolve().parent.parent / "reports"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _target_report_stem(target: Path) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", target.name).strip("-")
    if not slug:
        slug = "target"
    return f"{slug}_report"


if __name__ == "__main__":
    raise SystemExit(main())
