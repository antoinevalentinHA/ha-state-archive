from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


INCLUDE_TAGS = {
    "!include",
    "!include_dir_list",
    "!include_dir_named",
    "!include_dir_merge_list",
    "!include_dir_merge_named",
}

_INCLUDE_RE = re.compile(
    r"(?P<tag>!include(?:_dir_list|_dir_named|_dir_merge_list|_dir_merge_named)?)"
    r"[ \t]+(?P<target>[^\s#\n][^\n]*?)[ \t]*(?:#[^\n]*)?$",
    re.MULTILINE,
)


class IncludeResolverError(Exception):
    """Fatal include resolver error."""


@dataclass
class ResolvedFile:
    path: Path
    content: str
    parent: Path | None
    include_key: str | None
    depth: int
    root: Path


@dataclass
class IncludeEdge:
    parent: Path
    child: Path
    include_key: str
    raw_target: str


@dataclass
class ResolverResult:
    files: list[ResolvedFile] = field(default_factory=list)
    edges: list[IncludeEdge] = field(default_factory=list)
    missing_warnings: list[str] = field(default_factory=list)


@dataclass
class ResolverSummary:
    total_files: int
    max_depth: int
    by_tag: dict[str, int]
    edges: int
    missing_warnings: int


def _read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise IncludeResolverError(f"Unable to read: {path} ({exc})") from exc


def _extract_includes(content: str) -> Iterator[tuple[str, str]]:
    for match in _INCLUDE_RE.finditer(content):
        tag = match.group("tag").strip()
        target = match.group("target").strip()
        if tag in INCLUDE_TAGS and target:
            yield tag, target


def _collect_dir_yaml(directory: Path) -> list[Path]:
    """
    Recursively collect all .yaml/.yml files in a directory.
    Home Assistant handles !include_dir_* tags recursively by design.
    """
    return sorted(
        p for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() in {".yaml", ".yml"}
    )


def _resolve_targets(
    base_file: Path,
    tag: str,
    raw_target: str,
    result: ResolverResult,
) -> list[Path]:
    target = (base_file.parent / raw_target).resolve()

    if tag == "!include":
        if not target.exists() or not target.is_file():
            result.missing_warnings.append(
                f"!include target not found: {target} (from {base_file})"
            )
            return []
        return [target]

    if not target.exists():
        result.missing_warnings.append(
            f"Directory not found: {target} (tag {tag} from {base_file})"
        )
        return []
    if not target.is_dir():
        result.missing_warnings.append(
            f"Path is not a directory: {target} (tag {tag} from {base_file})"
        )
        return []
    return _collect_dir_yaml(target)


def _visit(
    current: Path,
    parent: Path | None,
    include_key: str | None,
    depth: int,
    stack: tuple[Path, ...],
    seen: set[Path],
    root: Path,
    result: ResolverResult,
) -> None:
    current = current.resolve()

    if current in stack:
        cycle = " -> ".join(str(p) for p in (*stack, current))
        raise IncludeResolverError(f"Include cycle detected: {cycle}")

    if not current.exists() or not current.is_file():
        result.missing_warnings.append(f"Missing file during traversal: {current}")
        return

    content = _read_file(current)

    if current not in seen:
        result.files.append(ResolvedFile(
            path=current,
            content=content,
            parent=parent,
            include_key=include_key,
            depth=depth,
            root=root,
        ))
        seen.add(current)

    new_stack = (*stack, current)

    for tag, raw_target in _extract_includes(content):
        child_paths = _resolve_targets(current, tag, raw_target, result)
        for child_path in child_paths:
            result.edges.append(IncludeEdge(
                parent=current,
                child=child_path.resolve(),
                include_key=tag,
                raw_target=raw_target,
            ))
            _visit(
                current=child_path,
                parent=current,
                include_key=tag,
                depth=depth + 1,
                stack=new_stack,
                seen=seen,
                root=root,
                result=result,
            )


def resolve_includes(root_path: str | Path) -> ResolverResult:
    root = Path(root_path).resolve()
    if not root.exists():
        raise IncludeResolverError(f"Root file not found: {root}")
    if not root.is_file():
        raise IncludeResolverError(f"Root path is not a file: {root}")

    result = ResolverResult()
    _visit(
        current=root,
        parent=None,
        include_key=None,
        depth=0,
        stack=tuple(),
        seen=set(),
        root=root,
        result=result,
    )
    return result


def summarize_resolver(result: ResolverResult) -> ResolverSummary:
    by_tag: dict[str, int] = {}
    max_depth = 0

    for edge in result.edges:
        by_tag[edge.include_key] = by_tag.get(edge.include_key, 0) + 1

    for f in result.files:
        if f.depth > max_depth:
            max_depth = f.depth

    return ResolverSummary(
        total_files=len(result.files),
        max_depth=max_depth,
        by_tag=dict(sorted(by_tag.items())),
        edges=len(result.edges),
        missing_warnings=len(result.missing_warnings),
    )
