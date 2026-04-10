from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Set

from pycodehygiene.config import Config


@dataclass
class DiscoveryResult:
    root: Path
    python_files: List[Path]
    packages: Set[Path]


def find_project_root(start: Path) -> Path:
    current = start.resolve()
    return current.parent if current.is_file() else current


def _matches_any(path_str: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(path_str, pattern):
            return True
    return False


def _is_test_file(path: Path) -> bool:
    name = path.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return "tests" in path.parts


def discover_python_files(root: Path, config: Config) -> DiscoveryResult:
    project_root = find_project_root(root)

    python_files: List[Path] = []
    packages: Set[Path] = set()

    include_patterns = list(config.include)
    exclude_patterns = list(config.exclude)

    for dirpath, dirnames, filenames in os_walk_sorted(project_root):
        dirpath_path = Path(dirpath)
        rel_dir = dirpath_path.relative_to(project_root)
        rel_dir_str = str(rel_dir) if str(rel_dir) != "." else ""

        dirnames[:] = [
            name
            for name in dirnames
            if name not in config.exclude_dirs
            and not _matches_any(str(Path(rel_dir_str, name)), exclude_patterns)
        ]

        if (dirpath_path / "__init__.py").exists():
            packages.add(dirpath_path)

        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            file_path = dirpath_path / filename
            rel_path = file_path.relative_to(project_root)
            rel_path_str = str(rel_path)

            if exclude_patterns and _matches_any(rel_path_str, exclude_patterns):
                continue
            if include_patterns and not _matches_any(rel_path_str, include_patterns):
                continue

            python_files.append(file_path)

    return DiscoveryResult(root=project_root, python_files=sorted(python_files), packages=packages)


def os_walk_sorted(root: Path):
    import os

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        filenames.sort()
        yield dirpath, dirnames, filenames


__all__ = ["DiscoveryResult", "discover_python_files", "find_project_root", "_is_test_file"]
