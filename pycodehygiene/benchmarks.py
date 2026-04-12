from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from time import perf_counter
from typing import Dict, List, Optional

from pycodehygiene.analyzer import analyze_dead_code
from pycodehygiene.config import apply_cli_overrides, load_config
from pycodehygiene.discovery import discover_python_files
from pycodehygiene.duplicates import analyze_duplicates
from pycodehygiene.indexer import build_index
from pycodehygiene.scanner import scan_project


def run_benchmark(
    root: Path | str,
    *,
    runs: int = 5,
    warmups: int = 1,
    config_path: Optional[Path] = None,
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
    duplicate_min_lines: Optional[int] = None,
    duplicate_similarity_threshold: Optional[float] = None,
    complexity_threshold: Optional[int] = None,
) -> Dict[str, object]:
    if runs < 1:
        raise ValueError("runs must be >= 1")
    if warmups < 0:
        raise ValueError("warmups must be >= 0")

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

    file_count = len(index.file_stats)
    function_blocks = sum(1 for block in index.code_blocks if block.kind == "function")

    for _ in range(warmups):
        analyze_dead_code(index=index, discovery=discovery, config=config)
        analyze_duplicates(index, config)

    dead_samples_ms: List[float] = []
    duplicate_samples_ms: List[float] = []
    full_scan_samples_ms: List[float] = []

    last_dead: Dict[str, object] = {}
    last_dups: Dict[str, object] = {}
    last_full: Dict[str, object] = {}

    for _ in range(runs):
        start = perf_counter()
        last_dead = analyze_dead_code(index=index, discovery=discovery, config=config)
        dead_samples_ms.append((perf_counter() - start) * 1000)

        start = perf_counter()
        last_dups = analyze_duplicates(index, config)
        duplicate_samples_ms.append((perf_counter() - start) * 1000)

        start = perf_counter()
        last_full = scan_project(
            root_path,
            config_path=config_path,
            include=include,
            exclude=exclude,
            duplicate_min_lines=duplicate_min_lines,
            duplicate_similarity_threshold=duplicate_similarity_threshold,
            complexity_threshold=complexity_threshold,
        )
        full_scan_samples_ms.append((perf_counter() - start) * 1000)

    return {
        "meta": {
            "target": str(discovery.root),
            "runs": runs,
            "warmups": warmups,
            "files_analyzed": file_count,
            "function_blocks": function_blocks,
        },
        "timings": {
            "dead_code_ms": _summarize(dead_samples_ms),
            "duplicates_ms": _summarize(duplicate_samples_ms),
            "full_scan_ms": _summarize(full_scan_samples_ms),
            "raw": {
                "dead_code_ms": _round_series(dead_samples_ms),
                "duplicates_ms": _round_series(duplicate_samples_ms),
                "full_scan_ms": _round_series(full_scan_samples_ms),
            },
        },
        "latest_counts": {
            "dead_code_findings": int(last_dead.get("summary", {}).get("total", 0))
            if isinstance(last_dead.get("summary"), dict)
            else 0,
            "duplicate_groups": int(last_dups.get("summary", {}).get("groups", 0))
            if isinstance(last_dups.get("summary"), dict)
            else 0,
            "full_scan_findings": int(last_full.get("summary", {}).get("total_findings", 0))
            if isinstance(last_full.get("summary"), dict)
            else 0,
        },
    }


def benchmark_table(benchmark: Dict[str, object]) -> str:
    timings = benchmark.get("timings", {}) if isinstance(benchmark.get("timings"), dict) else {}
    lines = [
        "Benchmark Results (ms)",
        "metric       mean    median    p95    min    max",
    ]
    for key, label in (
        ("dead_code_ms", "dead_code"),
        ("duplicates_ms", "duplicates"),
        ("full_scan_ms", "full_scan"),
    ):
        metric = timings.get(key, {}) if isinstance(timings.get(key), dict) else {}
        lines.append(
            "{label:<11}{mean:>8.2f}{median:>10.2f}{p95:>8.2f}{minv:>8.2f}{maxv:>8.2f}".format(
                label=label,
                mean=float(metric.get("mean", 0.0)),
                median=float(metric.get("median", 0.0)),
                p95=float(metric.get("p95", 0.0)),
                minv=float(metric.get("min", 0.0)),
                maxv=float(metric.get("max", 0.0)),
            )
        )
    return "\n".join(lines)


def write_benchmark_json(path: Path | str, benchmark: Dict[str, object]) -> None:
    Path(path).write_text(json.dumps(benchmark, indent=2), encoding="utf-8")


def _round_series(values: List[float]) -> List[float]:
    return [round(value, 3) for value in values]


def _summarize(samples_ms: List[float]) -> Dict[str, float]:
    if not samples_ms:
        return {"mean": 0.0, "median": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0}

    ordered = sorted(samples_ms)
    return {
        "mean": round(statistics.mean(ordered), 3),
        "median": round(statistics.median(ordered), 3),
        "p95": round(_percentile(ordered, 0.95), 3),
        "min": round(ordered[0], 3),
        "max": round(ordered[-1], 3),
    }


def _percentile(sorted_samples: List[float], q: float) -> float:
    if not sorted_samples:
        return 0.0
    idx = max(0, min(len(sorted_samples) - 1, math.ceil(q * len(sorted_samples)) - 1))
    return sorted_samples[idx]
