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

## Usage

```bash
py-code-hygiene scan /path/to/project
```

Common options:

```bash
py-code-hygiene scan /path/to/project \
  --html-output report.html \
  --json-output report.json \
  --min-dup-lines 8 \
  --dup-threshold 0.88 \
  --complexity-threshold 12
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
- global HTML filtering by analyzer/confidence/search text

## Notes
- Review-only by design (no in-report code mutation/autofix in v1).
- Static analysis is conservative but may still miss runtime dynamic behavior.

## License
MIT
