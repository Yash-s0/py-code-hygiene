from __future__ import annotations

import ast
import hashlib
import itertools
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from pycodehygiene.config import Config
from pycodehygiene.models import CodeBlock, RepoIndex


@dataclass
class PreparedBlock:
    block: CodeBlock
    canonical: str
    exact_fingerprint: str
    tokens: List[str]
    shingles: Set[str]
    signature: List[int]


def analyze_duplicates(index: RepoIndex, config: Config) -> Dict[str, object]:
    candidates = [
        block
        for block in index.code_blocks
        if block.kind == "function"
        and block.lines >= config.duplicate_min_lines
        and not _is_ignored_file(block.file, config)
    ]

    prepared: List[PreparedBlock] = []
    for block in candidates:
        canonical = _canonicalize_source(block.source)
        if not canonical.strip():
            continue

        tokens = _tokenize(canonical)
        if len(tokens) < 8:
            continue

        shingles = _shingles(tokens, config.duplicate_shingle_size)
        if not shingles:
            continue

        signature = _minhash_signature(shingles, config.duplicate_minhash_permutations)
        exact_fingerprint = hashlib.sha1(canonical.encode("utf-8")).hexdigest()

        prepared.append(
            PreparedBlock(
                block=block,
                canonical=canonical,
                exact_fingerprint=exact_fingerprint,
                tokens=tokens,
                shingles=shingles,
                signature=signature,
            )
        )

    exact_groups = _build_exact_groups(prepared)
    near_groups = _build_near_groups(prepared, exact_groups, config)

    all_groups = exact_groups + near_groups
    all_groups.sort(key=lambda item: (item["kind"] != "exact", -item["count"], -item["similarity"]))

    return {
        "summary": {
            "functions_considered": len(prepared),
            "groups": len(all_groups),
            "exact_groups": len(exact_groups),
            "near_groups": len(near_groups),
            "duplicate_functions": sum(group["count"] for group in all_groups),
        },
        "groups": all_groups,
    }


def _build_exact_groups(prepared: List[PreparedBlock]) -> List[Dict[str, object]]:
    grouped: Dict[str, List[PreparedBlock]] = defaultdict(list)
    for item in prepared:
        grouped[item.exact_fingerprint].append(item)

    groups: List[Dict[str, object]] = []
    for fingerprint, items in grouped.items():
        if len(items) < 2:
            continue

        groups.append(
            {
                "id": f"exact-{fingerprint[:12]}",
                "kind": "exact",
                "confidence": "high",
                "similarity": 1.0,
                "reason": "Exact match after AST normalization",
                "count": len(items),
                "items": [_item_to_dict(item.block) for item in sorted(items, key=lambda it: (it.block.file, it.block.line_start))],
            }
        )

    groups.sort(key=lambda item: item["count"], reverse=True)
    return groups


def _build_near_groups(
    prepared: List[PreparedBlock],
    exact_groups: List[Dict[str, object]],
    config: Config,
) -> List[Dict[str, object]]:
    exact_member_ids: Set[str] = set()
    for group in exact_groups:
        for item in group["items"]:
            exact_member_ids.add(_block_key(item["file"], item["line_start"], item["name"]))

    candidates = [item for item in prepared if _block_key(item.block.file, item.block.line_start, item.block.name) not in exact_member_ids]
    if len(candidates) < 2:
        return []

    bands = max(1, min(config.duplicate_lsh_bands, len(candidates[0].signature)))
    buckets: Dict[Tuple[int, Tuple[int, ...]], List[int]] = defaultdict(list)

    for idx, item in enumerate(candidates):
        for band_index, band in _bands(item.signature, bands):
            buckets[(band_index, band)].append(idx)

    candidate_pairs: Set[Tuple[int, int]] = set()
    for member_indices in buckets.values():
        if len(member_indices) < 2:
            continue
        for left, right in itertools.combinations(sorted(set(member_indices)), 2):
            candidate_pairs.add((left, right))

    adjacency: Dict[int, Set[int]] = defaultdict(set)
    similarity_map: Dict[Tuple[int, int], float] = {}

    for left, right in candidate_pairs:
        sim = _jaccard(candidates[left].shingles, candidates[right].shingles)
        if sim < config.duplicate_similarity_threshold:
            continue
        adjacency[left].add(right)
        adjacency[right].add(left)
        similarity_map[(left, right)] = sim
        similarity_map[(right, left)] = sim

    visited: Set[int] = set()
    groups: List[Dict[str, object]] = []

    for start in sorted(adjacency):
        if start in visited:
            continue

        queue = [start]
        component: List[int] = []
        visited.add(start)

        while queue:
            current = queue.pop()
            component.append(current)
            for neighbor in adjacency[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        if len(component) < 2:
            continue

        sims: List[float] = []
        for left, right in itertools.combinations(component, 2):
            sim = similarity_map.get((left, right))
            if sim is not None:
                sims.append(sim)

        if not sims:
            continue

        avg_similarity = sum(sims) / len(sims)
        confidence = "low"
        if avg_similarity >= 0.93:
            confidence = "high"
        elif avg_similarity >= 0.88:
            confidence = "medium"

        snippet_hash = hashlib.sha1("|".join(str(idx) for idx in sorted(component)).encode("utf-8")).hexdigest()
        groups.append(
            {
                "id": f"near-{snippet_hash[:12]}",
                "kind": "near",
                "confidence": confidence,
                "similarity": round(avg_similarity, 3),
                "reason": "Near-duplicate detected via MinHash/LSH with Jaccard verification",
                "count": len(component),
                "items": [
                    _item_to_dict(candidates[idx].block)
                    for idx in sorted(component, key=lambda idx: (candidates[idx].block.file, candidates[idx].block.line_start))
                ],
            }
        )

    groups.sort(key=lambda item: (item["count"], item["similarity"]), reverse=True)
    return groups


def _is_ignored_file(file_path: str, config: Config) -> bool:
    if not config.ignore_test_files:
        return False
    parts = file_path.replace("\\", "/").split("/")
    name = parts[-1]
    return "tests" in parts or name.startswith("test_") or name.endswith("_test.py")


def _canonicalize_source(source: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _strip_comments(source)

    normalizer = _Normalizer()
    normalized = normalizer.visit(tree)
    ast.fix_missing_locations(normalized)

    try:
        return ast.unparse(normalized)
    except Exception:
        return ast.dump(normalized, include_attributes=False)


def _strip_comments(source: str) -> str:
    return "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))


class _Normalizer(ast.NodeTransformer):
    def __init__(self):
        self.name_map: Dict[str, str] = {}
        self.counter = 0

    def _map_name(self, name: str) -> str:
        if name in {"self", "cls"}:
            return name
        if name not in self.name_map:
            self.counter += 1
            self.name_map[name] = f"v{self.counter}"
        return self.name_map[name]

    def visit_FunctionDef(self, node: ast.FunctionDef):
        node = self.generic_visit(node)
        node.name = "fn"
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        node = self.generic_visit(node)
        node.name = "fn"
        return node

    def visit_ClassDef(self, node: ast.ClassDef):
        node = self.generic_visit(node)
        node.name = "cls"
        return node

    def visit_Name(self, node: ast.Name):
        return ast.copy_location(ast.Name(id=self._map_name(node.id), ctx=node.ctx), node)

    def visit_arg(self, node: ast.arg):
        node.arg = self._map_name(node.arg)
        return self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        node = self.generic_visit(node)
        if node.attr.startswith("__") and node.attr.endswith("__"):
            return node
        node.attr = "attr"
        return node

    def visit_Constant(self, node: ast.Constant):
        value = node.value
        if isinstance(value, str):
            return ast.copy_location(ast.Constant(value="str"), node)
        if isinstance(value, (int, float, complex)):
            return ast.copy_location(ast.Constant(value=0), node)
        if isinstance(value, bytes):
            return ast.copy_location(ast.Constant(value=b"bytes"), node)
        return node


def _tokenize(code: str) -> List[str]:
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+|\S", code)


def _shingles(tokens: List[str], size: int) -> Set[str]:
    if len(tokens) < size:
        return set()
    return {" ".join(tokens[idx : idx + size]) for idx in range(0, len(tokens) - size + 1)}


def _minhash_signature(shingles: Set[str], permutations: int) -> List[int]:
    signature: List[int] = []
    for seed in range(permutations):
        minimum = None
        seed_bytes = seed.to_bytes(4, "big", signed=False)
        for item in shingles:
            digest = hashlib.blake2b(seed_bytes + item.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big", signed=False)
            if minimum is None or value < minimum:
                minimum = value
        signature.append(minimum if minimum is not None else 0)
    return signature


def _bands(signature: List[int], bands: int) -> Iterable[Tuple[int, Tuple[int, ...]]]:
    if bands <= 1:
        yield 0, tuple(signature)
        return

    size = max(1, len(signature) // bands)
    for band_index in range(bands):
        start = band_index * size
        if start >= len(signature):
            break
        end = len(signature) if band_index == bands - 1 else min(len(signature), start + size)
        yield band_index, tuple(signature[start:end])


def _jaccard(left: Set[str], right: Set[str]) -> float:
    if not left or not right:
        return 0.0
    inter = len(left & right)
    union = len(left | right)
    if union == 0:
        return 0.0
    return inter / union


def _item_to_dict(block: CodeBlock) -> Dict[str, object]:
    return {
        "file": block.file,
        "name": block.name,
        "qualname": block.qualname,
        "line_start": block.line_start,
        "line_end": block.line_end,
        "lines": block.lines,
        "snippet": "\n".join(block.source.splitlines()[:14]),
    }


def _block_key(file_path: str, line_start: int, name: str) -> str:
    return f"{file_path}:{line_start}:{name}"
