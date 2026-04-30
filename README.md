# py-code-hygiene

A Python analysis tool for Python developers and teams to reduce tech debt through a report-driven workflow.

It analyzes codebases for:
- likely dead code
- duplicate logic (exact and near-duplicate)
- complexity hotspots

It generates reports so you can quickly identify cleanup and refactor opportunities.

Unlike basic linters that focus on style and syntax rules, py-code-hygiene is focused on structural maintainability risks and refactor opportunities across a codebase.

## Why use this

- Reduce tech debt with targeted, evidence-based cleanup opportunities.
- Find likely unused code before it silently accumulates.
- Detect exact and near-duplicate logic that increases maintenance overhead.
- Highlight complexity risks early so refactors can be prioritized.

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Jinja2](https://img.shields.io/badge/Jinja2-Template%20Engine-B41717?logo=jinja&logoColor=white)
![TOML](https://img.shields.io/badge/Config-TOML-9C4121?logo=toml&logoColor=white)
![HTML](https://img.shields.io/badge/Report-HTML-E34F26?logo=html5&logoColor=white)
![JSON](https://img.shields.io/badge/Report-JSON-000000?logo=json&logoColor=white)
![CLI](https://img.shields.io/badge/Interface-CLI-2d2d2d?logo=gnubash&logoColor=white)

## Requirements
- Python 3.11+

## Quick Start (Recommended)

```bash
git clone https://github.com/Yash-s0/py-code-hygiene.git
cd py-code-hygiene
python -m venv .venv
source .venv/bin/activate
pip install -e .
py-code-hygiene scan .
```

What this does:
- scans the target project
- writes reports to this repo's `reports/` folder
- shows analysis results and findings directly in the terminal
- Then open the generated HTML report in your browser.

Example terminal output:
```text
[+] Target: /path/to/project
[+] Files analyzed: 128 Python files
[+] Findings: dead_code=8 duplicates=0 complexity=0
[+] HTML report: /path/to/repo/reports/project_report.html
```

## How it works

- Use the CLI only to run analysis.
- Open the generated HTML report in a browser for the full review experience.
- Use JSON output for integrations, automation, or downstream processing.
- No CLI is needed to view the generated results.

## Install

If you already cloned the repo:

```bash
cd py-code-hygiene
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Main Commands

```bash
py-code-hygiene --help
py-code-hygiene scan --help
py-code-hygiene benchmark --help
```

Subcommands:
- `scan`: analyze a project and generate reports
- `benchmark`: measure analyzer/full-scan performance

## Scan Command

Basic usage:

```bash
py-code-hygiene scan /path/to/project
py-code-hygiene scan .
```

Full example:

```bash
py-code-hygiene scan /path/to/project \
  --html-output project_report.html \
  --json-output project_report.json \
  --config /path/to/pycodehygiene.toml \
  --include "app/**/*.py" \
  --exclude "tests/**" \
  --min-confidence low \
  --min-dup-lines 8 \
  --dup-threshold 0.88 \
  --complexity-threshold 12
```

### Scan Options
| Option | Description |
|---|---|
| `path` | Project path to scan (default: current directory) |
| `--html-output`, `-o` | HTML report filename |
| `--json-output` | JSON report filename |
| `--config` | Path to `pycodehygiene.toml` |
| `--include` | Include glob pattern (repeatable) |
| `--exclude` | Exclude glob pattern (repeatable) |
| `--min-confidence` | Dead-code confidence floor: `low`, `medium`, `high` |
| `--min-dup-lines` | Minimum lines for duplicate detection |
| `--dup-threshold` | Near-duplicate similarity threshold (`0.5` to `1.0`) |
| `--complexity-threshold` | Complexity hotspot threshold |
| `--no-html` | Skip HTML generation |
| `--no-json` | Skip JSON generation |

## Benchmark Command

Basic usage:

```bash
py-code-hygiene benchmark /path/to/project
```

Example:

```bash
py-code-hygiene benchmark /path/to/project \
  --runs 8 \
  --warmups 2 \
  --config /path/to/pycodehygiene.toml \
  --include "app/**/*.py" \
  --exclude "tests/**" \
  --min-confidence low \
  --min-dup-lines 8 \
  --dup-threshold 0.88 \
  --complexity-threshold 12 \
  --json-output benchmark_results.json
```

### Benchmark Options
| Option | Description |
|---|---|
| `path` | Project path to benchmark (default: current directory) |
| `--config` | Path to `pycodehygiene.toml` |
| `--include` | Include glob pattern (repeatable) |
| `--exclude` | Exclude glob pattern (repeatable) |
| `--min-confidence` | Dead-code confidence floor: `low`, `medium`, `high` |
| `--min-dup-lines` | Duplicate minimum lines override |
| `--dup-threshold` | Duplicate similarity threshold override |
| `--complexity-threshold` | Complexity threshold override |
| `--runs` | Measured runs (default: `5`) |
| `--warmups` | Warmup runs (default: `1`) |
| `--json-output` | Benchmark JSON filename |

## Report Output Behavior
Scan report files are always written under this repo's `reports/` directory.

Usage flow:
- Open the generated HTML report in your browser.
- Use the JSON report for integrations and automation.
- Use the CLI only to execute analysis and generate outputs.

Rules:
- only the filename portion of output paths is used
- default filenames are:
  - `<target-name>_report.html`
  - `<target-name>_report.json`
- missing file extension is added automatically
- when the default `pycodehygiene_report.*` name is used, it is replaced with `<target-name>_report.*`
- use `--no-html` and/or `--no-json` to control outputs

Examples:
- `py-code-hygiene scan /path/to/project --html-output my.html --json-output my.json`
  - creates `reports/my.html` and `reports/my.json`
- `py-code-hygiene scan /path/to/project --no-html`
  - creates only JSON
- `py-code-hygiene scan /path/to/project --no-json`
  - creates only HTML
- `py-code-hygiene scan /path/to/project --no-html --no-json`
  - creates no report files (terminal summary only)

## Configuration
Config file discovery:
- auto-detected: `pycodehygiene.toml` in scan root
- explicit: `--config /path/to/pycodehygiene.toml`
- reference: `pycodehygiene.toml.example`

Example:

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

complexity_threshold = 25
top_complexity_limit = 30
```

## Optional AI Guidance
If a `.env` file exists in this tool repo, scan checks:
- `OPENAI_API_KEY` (preferred)
- `ANTHROPIC_API_KEY` (fallback)

With a supported key, findings may include AI improvement guidance.
Without a key, scanning still works normally.

## Development / Local Checks

```bash
python -m compileall pycodehygiene
python -m pytest
```

## Sample Output

Placeholder: add a screenshot of the generated HTML report and/or a short JSON snippet example here.

## Limitations

- Static analysis is conservative and may miss runtime-only behavior.
- Dynamic imports/reflection patterns can reduce detection precision.
- Findings are guidance-oriented and should be validated before code deletion.

## Common Recipes

Scan current folder:
```bash
py-code-hygiene scan .
```

Scan JSON only:
```bash
py-code-hygiene scan /path/to/project --no-html
```

Scan HTML only:
```bash
py-code-hygiene scan /path/to/project --no-json
```

Include low-confidence dead-code findings:
```bash
py-code-hygiene scan /path/to/project --min-confidence low
```

Run benchmark with defaults:
```bash
py-code-hygiene benchmark /path/to/project
```

## Notes

- This tool is review-focused and does not auto-modify your code.

## License
MIT
