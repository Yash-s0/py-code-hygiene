from __future__ import annotations

from pathlib import Path
from typing import Dict


def read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="latin-1")
        except OSError:
            return ""
    except OSError:
        return ""


def count_lines(source: str) -> Dict[str, int]:
    lines = source.splitlines()
    total = len(lines)
    blank = sum(1 for line in lines if not line.strip())
    comment = sum(1 for line in lines if line.strip().startswith("#"))
    code = total - blank - comment
    return {
        "total": total,
        "blank": blank,
        "comment": comment,
        "code": code,
    }
