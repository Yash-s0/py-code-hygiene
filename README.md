# py-code-hygiene

Unified Python code hygiene scanner for:
- dead code
- duplicates
- complexity hotspots

It produces one developer-friendly HTML report and one JSON report per scan.

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Jinja2](https://img.shields.io/badge/Jinja2-Template%20Engine-B41717?logo=jinja&logoColor=white)
![TOML](https://img.shields.io/badge/Config-TOML-9C4121?logo=toml&logoColor=white)
![HTML](https://img.shields.io/badge/Report-HTML-E34F26?logo=html5&logoColor=white)
![JSON](https://img.shields.io/badge/Report-JSON-000000?logo=json&logoColor=white)
![CLI](https://img.shields.io/badge/Interface-CLI-2d2d2d?logo=gnubash&logoColor=white)

## Why developers use it
- catches likely removable code with confidence scoring
- finds exact and near duplicates
- highlights complex functions to refactor first
- keeps outputs centralized in this repo's `reports/` folder

## Requirements
- Python 3.11+

## Install
```bash
cd py-code-hygiene
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Quick Start
```bash
py-code-hygiene scan /path/to/project
```

What happens:
- analyzes the target project
- writes reports in `reports/`
- prints summary stats in terminal

## Command Help
```bash
py-code-hygiene --help
py-code-hygiene scan --help
py-code-hygiene benchmark --help
```

Subcommands:
- `scan`: run analysis and generate reports
- `benchmark`: measure analyzer/full-scan performance

## Scan Command (Line-by-Line)
```bash
py-code-hygiene scan /path/to/project \
  --html-output project_report.html \
  --json-output project_report.json \
  --config /path/to/pycodehygiene.toml \
  --include "app/**/*.py" \
  --exclude "tests/**" \
  --min-dup-lines 8 \
  --dup-threshold 0.88 \
  --complexity-threshold 12
```

Explanation of each line:
1. `py-code-hygiene scan /path/to/project`
   runs scan on this folder (defaults to `.` if path is not provided).
2. `--html-output project_report.html`
   sets HTML report filename (`-o` is a shortcut).
3. `--json-output project_report.json`
   sets JSON report filename.
4. `--config /path/to/pycodehygiene.toml`
   uses explicit config file.
5. `--include "app/**/*.py"`
   include glob filter (repeatable).
6. `--exclude "tests/**"`
   exclude glob filter (repeatable).
7. `--min-dup-lines 8`
   minimum duplicate block size.
8. `--dup-threshold 0.88`
   near-duplicate similarity threshold (`0.5` to `1.0`).
9. `--complexity-threshold 12`
   complexity hotspot threshold.

### Scan Options
| Option | Meaning |
|---|---|
| `path` | Project path to scan (default: current directory) |
| `--html-output`, `-o` | HTML output filename |
| `--json-output` | JSON output filename |
| `--config` | Path to `pycodehygiene.toml` |
| `--include` | Include glob pattern (repeatable) |
| `--exclude` | Exclude glob pattern (repeatable) |
| `--min-dup-lines` | Override duplicate minimum lines |
| `--dup-threshold` | Override duplicate similarity threshold |
| `--complexity-threshold` | Override complexity threshold |
| `--no-html` | Skip HTML generation (JSON still generated) |

## Benchmark Command (Line-by-Line)
```bash
py-code-hygiene benchmark /path/to/project \
  --runs 8 \
  --warmups 2 \
  --config /path/to/pycodehygiene.toml \
  --include "app/**/*.py" \
  --exclude "tests/**" \
  --min-dup-lines 8 \
  --dup-threshold 0.88 \
  --complexity-threshold 12 \
  --json-output benchmark_results.json
```

Explanation of each line:
1. `py-code-hygiene benchmark /path/to/project`
   runs benchmark for analyzers + full scan.
2. `--runs 8`
   measured runs after warmup.
3. `--warmups 2`
   warmup runs before measurements.
4. `--config /path/to/pycodehygiene.toml`
   benchmark with specific config.
5. `--include "app/**/*.py"`
   include glob filter (repeatable).
6. `--exclude "tests/**"`
   exclude glob filter (repeatable).
7. `--min-dup-lines 8`
   duplicate analyzer override.
8. `--dup-threshold 0.88`
   similarity override.
9. `--complexity-threshold 12`
   complexity override.
10. `--json-output benchmark_results.json`
    write benchmark JSON artifact to `reports/`.

### Benchmark Options
| Option | Meaning |
|---|---|
| `path` | Project path to benchmark (default: current directory) |
| `--config` | Path to `pycodehygiene.toml` |
| `--include` | Include glob pattern (repeatable) |
| `--exclude` | Exclude glob pattern (repeatable) |
| `--min-dup-lines` | Duplicate minimum lines override |
| `--dup-threshold` | Duplicate similarity threshold override |
| `--complexity-threshold` | Complexity threshold override |
| `--runs` | Measured runs (default: `5`) |
| `--warmups` | Warmup runs (default: `1`) |
| `--json-output` | Benchmark JSON filename (saved in `reports/`) |

## Report Output Rules
- scan outputs are always written under this repo's `reports/` directory
- only the filename part of output paths is used
- default scan filenames are:
  - `<target-folder>_report.html`
  - `<target-folder>_report.json`
- if extension is omitted, it is added automatically
- scan always writes JSON, even if `--no-html` is used

Examples:
- `py-code-hygiene scan /path/to/project --html-output my.html --json-output my.json`
  creates `reports/my.html` and `reports/my.json`.
- `py-code-hygiene scan /path/to/project --no-html`
  creates only `reports/<target>_report.json`.

## Common Recipes
Scan current folder:
```bash
py-code-hygiene scan .
```

Scan with JSON only:
```bash
py-code-hygiene scan /path/to/project --no-html
```

Benchmark with defaults:
```bash
py-code-hygiene benchmark /path/to/project
```

## Config
Config file locations:
- auto-detected: `pycodehygiene.toml` in scan root
- explicit: `--config /path/to/pycodehygiene.toml`
- reference schema: `pycodehygiene.toml.example`

Example config:
```toml
[tool.pycodehygiene]
minimum_confidence_to_report = "medium"
treat_public_api_as_live = true
ignore_magic_methods = true
ignore_test_files = true

include = ["src/**/*.py"]
exclude = ["build/**"]
exclude_dirs = [".venv"]

framework_presets = ["fastapi", "flask", "pytest", "pydantic"]
known_decorators = ["register"]
known_base_classes = ["BaseModel"]

duplicate_min_lines = 6
duplicate_similarity_threshold = 0.84
duplicate_shingle_size = 5
duplicate_minhash_permutations = 48
duplicate_lsh_bands = 12

complexity_threshold = 10
top_complexity_limit = 30
```

## What the Report Includes
- overview metrics and parse errors
- dead-code findings with confidence + evidence
- duplicate groups with snippets + similarity
- complexity hotspots + top functions
- HTML filtering, sorting, and issue preview interactions

## Notes
- Review-only by design (no autofix mutation in report).
- Static analysis is conservative and may miss runtime-only behavior.

## License
MIT
