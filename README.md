# py-code-hygiene

Unified Python code hygiene scanner that combines:
- dead code analysis (unused imports/symbols/locals + unreachable code)
- duplicate detection (exact normalized clones + near duplicates via MinHash/LSH + Jaccard verification)
- complexity hotspots (cyclomatic complexity thresholding)

It generates a single JSON and HTML report for review-first cleanup workflows.

## Requirements
- Python 3.11+

## Install

```bash
cd py-code-hygiene
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Commands (Current CLI)

```bash
py-code-hygiene --help
py-code-hygiene scan --help
py-code-hygiene benchmark --help
```

Available subcommands:
- `scan`: run analyzers and generate reports
- `benchmark`: measure analyzer/full-scan performance

## Usage

### 1) Basic scan (quick start)

```bash
py-code-hygiene scan /path/to/project
```

What this does:
- scans the target path
- writes JSON + HTML reports
- prints summary counts in terminal

### 2) Full scan command with line-by-line explanation

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

Line-by-line:
1. `py-code-hygiene scan /path/to/project`
   scans this project folder (if omitted, default is current directory `.`).
2. `--html-output project_report.html`
   sets HTML output filename (`-o` is an alias for this option).
3. `--json-output project_report.json`
   sets JSON output filename.
4. `--config /path/to/pycodehygiene.toml`
   loads config from an explicit TOML file.
5. `--include "app/**/*.py"`
   include filter (repeatable). Use multiple `--include` lines if needed.
6. `--exclude "tests/**"`
   exclude filter (repeatable). Use multiple `--exclude` lines if needed.
7. `--min-dup-lines 8`
   minimum block length used for duplicate detection.
8. `--dup-threshold 0.88`
   near-duplicate similarity threshold (valid range: `0.5` to `1.0`).
9. `--complexity-threshold 12`
   complexity score cutoff for reporting hotspots.

### 3) Scan options (all)

- `path`
  target project path (default: current directory).
- `--html-output`, `-o`
  output HTML report filename.
- `--json-output`
  output JSON report filename.
- `--config`
  config file path.
- `--include` (repeatable)
  include glob(s), for example `--include "src/**/*.py"`.
- `--exclude` (repeatable)
  exclude glob(s), for example `--exclude "migrations/**"`.
- `--min-dup-lines`
  override duplicate minimum lines.
- `--dup-threshold`
  override near-duplicate threshold.
- `--complexity-threshold`
  override complexity threshold.
- `--no-html`
  skip HTML generation (JSON still generated).

### 4) Scan output behavior (important)

- All scan outputs are written under this repo's `reports/` directory.
- Output path values are normalized to filename only (directory parts are ignored).
- Default names are target-based:
  - `<target-folder>_report.html`
  - `<target-folder>_report.json`
- If output filename has no extension, the proper one is added.
- JSON is always generated for `scan`.

Examples:
- `py-code-hygiene scan /path/to/project --html-output my.html --json-output my.json`
  writes:
  - `reports/my.html`
  - `reports/my.json`
- `py-code-hygiene scan /path/to/project --no-html`
  writes:
  - `reports/<target>_report.json`

### 5) Benchmark command with line-by-line explanation

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

Line-by-line:
1. `py-code-hygiene benchmark /path/to/project`
   runs performance benchmark on this target.
2. `--runs 8`
   number of measured runs after warmup.
3. `--warmups 2`
   warmup runs before measured runs.
4. `--config /path/to/pycodehygiene.toml`
   config path for benchmarked scan settings.
5. `--include "app/**/*.py"`
   include filter (repeatable).
6. `--exclude "tests/**"`
   exclude filter (repeatable).
7. `--min-dup-lines 8`
   duplicate analyzer override for benchmark.
8. `--dup-threshold 0.88`
   duplicate similarity override for benchmark.
9. `--complexity-threshold 12`
   complexity override for benchmark.
10. `--json-output benchmark_results.json`
    writes benchmark JSON artifact into `reports/`.

### 6) Benchmark options (all)

- `path`
  target project path (default: current directory).
- `--config`
  config file path.
- `--include` (repeatable)
  include glob filters.
- `--exclude` (repeatable)
  exclude glob filters.
- `--min-dup-lines`
  duplicate min lines override.
- `--dup-threshold`
  duplicate similarity threshold override.
- `--complexity-threshold`
  complexity threshold override.
- `--runs`
  measured benchmark runs (default: `5`).
- `--warmups`
  warmup runs before measurements (default: `1`).
- `--json-output`
  optional benchmark JSON filename (saved in `reports/`).

### 7) Useful command recipes

Scan current directory:
```bash
py-code-hygiene scan .
```

Scan with only JSON output:
```bash
py-code-hygiene scan /path/to/project --no-html
```

Benchmark with defaults:
```bash
py-code-hygiene benchmark /path/to/project
```

Config file support:
- default: `pycodehygiene.toml` in the scan root
- explicit: `--config /path/to/pycodehygiene.toml`
- schema example: `pycodehygiene.toml.example`

## Config schema

Top-level tool table:

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

## Output

The unified report includes:
- overview metrics and parse errors
- dead-code findings with confidence and evidence
- duplicate groups with snippets and similarity
- complexity hotspots and top-complexity functions
- sticky filter bar for quick review in long reports
- global HTML filtering by analyzer/confidence/severity/search text
- sortable tables for overview, dead-code, and complexity sections

## Notes
- Review-only by design (no in-report code mutation/autofix in v1).
- Static analysis is conservative but may still miss runtime dynamic behavior.

## License
MIT
