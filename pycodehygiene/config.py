from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

import tomllib

CONFIDENCE_LEVELS = {"low": 0, "medium": 1, "high": 2}

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".eggs",
    ".idea",
    ".vscode",
    "site-packages",
    "migrations",
    "vendor",
    "vendored",
}

PRESET_DECORATORS: Dict[str, Set[str]] = {
    "fastapi": {
        "get",
        "post",
        "put",
        "delete",
        "patch",
        "options",
        "head",
        "websocket",
        "api_route",
        "on_event",
    },
    "flask": {"route", "before_request", "after_request", "teardown_request"},
    "django": {
        "receiver",
        "admin.register",
        "register",
    },
    "pytest": {"fixture", "mark.parametrize", "parametrize"},
    "click": {"command", "group", "option", "argument", "pass_context", "pass_obj"},
    "typer": {"command", "callback"},
    "pydantic": {
        "validator",
        "root_validator",
        "field_validator",
        "model_validator",
        "field_serializer",
        "model_serializer",
        "computed_field",
    },
    "sqlalchemy": {"declared_attr", "event.listens_for", "listens_for"},
    "celery": {"task", "shared_task"},
    "dataclasses": {"dataclass"},
    "attrs": {"define", "frozen", "mutable", "attrs", "attr.s"},
    "marshmallow": {
        "pre_load",
        "post_load",
        "pre_dump",
        "post_dump",
        "validates",
        "validates_schema",
    },
}

PRESET_BASE_CLASSES: Dict[str, Set[str]] = {
    "django": {"models.Model", "Model"},
    "sqlalchemy": {"Base", "DeclarativeBase", "Model"},
    "pydantic": {"BaseModel"},
    "celery": {"Task"},
}


@dataclass
class Config:
    include: List[str] = field(default_factory=list)
    exclude: List[str] = field(default_factory=list)
    exclude_dirs: Set[str] = field(default_factory=lambda: set(DEFAULT_EXCLUDE_DIRS))

    minimum_confidence_to_report: str = "medium"
    treat_public_api_as_live: bool = True
    ignore_magic_methods: bool = True
    ignore_test_files: bool = True

    known_decorators: Set[str] = field(default_factory=set)
    known_base_classes: Set[str] = field(default_factory=set)
    framework_presets: List[str] = field(
        default_factory=lambda: [
            "fastapi",
            "flask",
            "django",
            "pytest",
            "click",
            "typer",
            "pydantic",
            "sqlalchemy",
            "celery",
            "dataclasses",
            "attrs",
            "marshmallow",
        ]
    )

    duplicate_min_lines: int = 6
    duplicate_similarity_threshold: float = 0.84
    duplicate_shingle_size: int = 5
    duplicate_minhash_permutations: int = 48
    duplicate_lsh_bands: int = 12

    complexity_threshold: int = 10
    top_complexity_limit: int = 30

    report_title: str = "Py Code Hygiene Report"

    def confidence_allows(self, level: str) -> bool:
        return CONFIDENCE_LEVELS.get(level, 0) >= CONFIDENCE_LEVELS.get(
            self.minimum_confidence_to_report, 0
        )


def _normalize_name(value: str) -> str:
    return value.strip()


def _ensure_list(value: Optional[Iterable[str]]) -> List[str]:
    if not value:
        return []
    return [str(item) for item in value]


def _extract_section(data: Dict) -> Dict:
    if "tool" in data and isinstance(data["tool"], dict):
        if "pycodehygiene" in data["tool"]:
            return data["tool"]["pycodehygiene"] or {}
    return data.get("pycodehygiene", {}) or {}


def _apply_presets(config: Config) -> None:
    decorators: Set[str] = set()
    base_classes: Set[str] = set()
    for preset in config.framework_presets:
        decorators.update(PRESET_DECORATORS.get(preset, set()))
        base_classes.update(PRESET_BASE_CLASSES.get(preset, set()))
    config.known_decorators.update(decorators)
    config.known_base_classes.update(base_classes)


def _validate_config(config: Config) -> None:
    valid_conf = set(CONFIDENCE_LEVELS.keys())
    if config.minimum_confidence_to_report not in valid_conf:
        raise ValueError(
            "minimum_confidence_to_report must be one of: "
            + ", ".join(sorted(valid_conf))
        )

    if config.duplicate_min_lines < 1:
        raise ValueError("duplicate_min_lines must be >= 1")

    if not (0.5 <= config.duplicate_similarity_threshold <= 1.0):
        raise ValueError("duplicate_similarity_threshold must be between 0.5 and 1.0")

    if config.duplicate_shingle_size < 2:
        raise ValueError("duplicate_shingle_size must be >= 2")

    if config.duplicate_minhash_permutations < 16:
        raise ValueError("duplicate_minhash_permutations must be >= 16")

    if config.duplicate_lsh_bands < 1:
        raise ValueError("duplicate_lsh_bands must be >= 1")

    if config.complexity_threshold < 1:
        raise ValueError("complexity_threshold must be >= 1")

    if config.top_complexity_limit < 1:
        raise ValueError("top_complexity_limit must be >= 1")


def load_config(root: Path, explicit_path: Optional[Path] = None) -> Config:
    config = Config()

    config_path: Optional[Path]
    if explicit_path:
        config_path = explicit_path
    else:
        candidate = root / "pycodehygiene.toml"
        config_path = candidate if candidate.exists() else None

    if config_path and config_path.exists():
        data = _extract_section(tomllib.loads(config_path.read_text(encoding="utf-8")))

        config.include = _ensure_list(data.get("include"))
        config.exclude = _ensure_list(data.get("exclude"))

        exclude_dirs = data.get("exclude_dirs") or []
        if exclude_dirs:
            config.exclude_dirs.update({str(item) for item in exclude_dirs})

        config.minimum_confidence_to_report = str(
            data.get("minimum_confidence_to_report", config.minimum_confidence_to_report)
        ).lower()
        config.treat_public_api_as_live = bool(
            data.get("treat_public_api_as_live", config.treat_public_api_as_live)
        )
        config.ignore_magic_methods = bool(
            data.get("ignore_magic_methods", config.ignore_magic_methods)
        )
        config.ignore_test_files = bool(
            data.get("ignore_test_files", config.ignore_test_files)
        )

        config.framework_presets = _ensure_list(
            data.get("framework_presets", config.framework_presets)
        )

        config.known_decorators.update(
            {_normalize_name(item) for item in _ensure_list(data.get("known_decorators"))}
        )
        config.known_base_classes.update(
            {_normalize_name(item) for item in _ensure_list(data.get("known_base_classes"))}
        )

        config.duplicate_min_lines = int(data.get("duplicate_min_lines", config.duplicate_min_lines))
        config.duplicate_similarity_threshold = float(
            data.get("duplicate_similarity_threshold", config.duplicate_similarity_threshold)
        )
        config.duplicate_shingle_size = int(
            data.get("duplicate_shingle_size", config.duplicate_shingle_size)
        )
        config.duplicate_minhash_permutations = int(
            data.get("duplicate_minhash_permutations", config.duplicate_minhash_permutations)
        )
        config.duplicate_lsh_bands = int(
            data.get("duplicate_lsh_bands", config.duplicate_lsh_bands)
        )

        config.complexity_threshold = int(data.get("complexity_threshold", config.complexity_threshold))
        config.top_complexity_limit = int(data.get("top_complexity_limit", config.top_complexity_limit))
        config.report_title = str(data.get("report_title", config.report_title))

    _apply_presets(config)
    _validate_config(config)
    return config


def apply_cli_overrides(
    config: Config,
    *,
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
    duplicate_min_lines: Optional[int] = None,
    duplicate_similarity_threshold: Optional[float] = None,
    complexity_threshold: Optional[int] = None,
) -> Config:
    if include is not None:
        config.include = include
    if exclude is not None:
        config.exclude = exclude

    if duplicate_min_lines is not None:
        config.duplicate_min_lines = duplicate_min_lines
    if duplicate_similarity_threshold is not None:
        config.duplicate_similarity_threshold = duplicate_similarity_threshold
    if complexity_threshold is not None:
        config.complexity_threshold = complexity_threshold

    _validate_config(config)
    return config


def config_to_dict(config: Config) -> Dict[str, object]:
    return {
        "include": list(config.include),
        "exclude": list(config.exclude),
        "exclude_dirs": sorted(config.exclude_dirs),
        "minimum_confidence_to_report": config.minimum_confidence_to_report,
        "treat_public_api_as_live": config.treat_public_api_as_live,
        "ignore_magic_methods": config.ignore_magic_methods,
        "ignore_test_files": config.ignore_test_files,
        "framework_presets": list(config.framework_presets),
        "known_decorators": sorted(config.known_decorators),
        "known_base_classes": sorted(config.known_base_classes),
        "duplicate_min_lines": config.duplicate_min_lines,
        "duplicate_similarity_threshold": config.duplicate_similarity_threshold,
        "duplicate_shingle_size": config.duplicate_shingle_size,
        "duplicate_minhash_permutations": config.duplicate_minhash_permutations,
        "duplicate_lsh_bands": config.duplicate_lsh_bands,
        "complexity_threshold": config.complexity_threshold,
        "top_complexity_limit": config.top_complexity_limit,
        "report_title": config.report_title,
    }
