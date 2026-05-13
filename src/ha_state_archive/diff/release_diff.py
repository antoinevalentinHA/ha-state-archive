#!/usr/bin/env python3
"""
release_diff.py — Home Assistant state release diff engine.

Generates Markdown diffs and digests between versioned Home Assistant snapshots.

Design goals:
- deterministic snapshot indexing;
- canonical release anchor graph;
- bounded Markdown output;
- binary-safe diffing;
- idempotent generation;
- persistent release state.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


ANCHOR_RE = re.compile(r"(^|_)v(\d+)(?:\.(\d+))?(_|$)")
CAPTURE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})_")

MAX_LINES_PER_FILE = 500
MAX_DETAILED_FILES = 100
MAX_OUTPUT_SIZE_BYTES = 5 * 1024 * 1024
DIFF_CONTEXT_LINES = 5


@dataclass(frozen=True)
class Anchor:
    tag: str
    major: int
    minor: int
    dirname: str
    path: Path
    captured_at: Optional[datetime]

    @property
    def sort_key(self) -> Tuple[int, int]:
        return (self.major, self.minor)


@dataclass(frozen=True)
class FileEntry:
    sha256: str
    size: int


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()

    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)

    return h.hexdigest()


def snapshot_sha256(snapshot_dir: Path) -> str:
    h = hashlib.sha256()

    files = sorted(
        [p for p in snapshot_dir.rglob("*") if p.is_file()],
        key=lambda p: p.relative_to(snapshot_dir).as_posix(),
    )

    for p in files:
        rel = p.relative_to(snapshot_dir).as_posix()
        file_hash = sha256_file(p)

        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(file_hash.encode("ascii"))
        h.update(b"\n")

    return h.hexdigest()


def index_snapshot(snapshot_dir: Path) -> Dict[str, FileEntry]:
    out: Dict[str, FileEntry] = {}

    files = sorted(
        [p for p in snapshot_dir.rglob("*") if p.is_file()],
        key=lambda p: p.relative_to(snapshot_dir).as_posix(),
    )

    for p in files:
        rel = p.relative_to(snapshot_dir).as_posix()
        out[rel] = FileEntry(
            sha256=sha256_file(p),
            size=p.stat().st_size,
        )

    return out


def parse_capture_datetime(dirname: str) -> Optional[datetime]:
    match = CAPTURE_RE.match(dirname)

    if not match:
        return None

    try:
        return datetime.fromisoformat(
            f"{match.group(1)}T{match.group(2)}:{match.group(3)}:00"
        )
    except ValueError:
        return None


def parse_anchor(path: Path) -> Optional[Anchor]:
    match = ANCHOR_RE.search(path.name)

    if not match:
        return None

    major = int(match.group(2))
    minor = int(match.group(3) or 0)
    tag = f"v{major}" if minor == 0 else f"v{major}.{minor}"

    return Anchor(
        tag=tag,
        major=major,
        minor=minor,
        dirname=path.name,
        path=path,
        captured_at=parse_capture_datetime(path.name),
    )


def scan_anchors(versions_dir: Path) -> Tuple[List[Anchor], Dict[str, List[Anchor]]]:
    if not versions_dir.exists():
        raise FileNotFoundError(f"versions directory does not exist: {versions_dir}")

    if not versions_dir.is_dir():
        raise NotADirectoryError(f"versions path is not a directory: {versions_dir}")

    by_tag: Dict[str, List[Anchor]] = {}

    for p in versions_dir.iterdir():
        if not p.is_dir():
            continue

        if p.name.startswith(".") or p.name.startswith("_"):
            continue

        anchor = parse_anchor(p)

        if anchor is None:
            continue

        by_tag.setdefault(anchor.tag, []).append(anchor)

    duplicates = {tag: items for tag, items in by_tag.items() if len(items) > 1}
    anchors = [items[0] for tag, items in by_tag.items() if tag not in duplicates]
    anchors.sort(key=lambda a: a.sort_key)

    return anchors, duplicates


def detect_lineage_warnings(anchors: List[Anchor]) -> List[Tuple[Anchor, List[Anchor]]]:
    warnings: List[Tuple[Anchor, List[Anchor]]] = []

    for i, anchor in enumerate(anchors):
        if anchor.captured_at is None:
            continue

        later_than = [
            higher
            for higher in anchors[i + 1 :]
            if higher.captured_at is not None and anchor.captured_at > higher.captured_at
        ]

        if later_than:
            warnings.append((anchor, later_than))

    return warnings


def consecutive_couples(anchors: List[Anchor]) -> List[Tuple[Anchor, Anchor]]:
    return list(zip(anchors, anchors[1:]))


def consecutive_tag_pairs(anchors: List[Anchor]) -> set[Tuple[str, str]]:
    return {(a.tag, b.tag) for a, b in consecutive_couples(anchors)}


def resolve_anchor(tag: str, anchors: List[Anchor]) -> Anchor:
    by_tag = {a.tag: a for a in anchors}

    if tag not in by_tag:
        raise ValueError(f"anchor not found in graph: {tag}")

    return by_tag[tag]


def selected_couples(
    anchors: List[Anchor],
    couple: Optional[List[str]],
) -> List[Tuple[Anchor, Anchor]]:
    if couple is None:
        return consecutive_couples(anchors)

    left = resolve_anchor(couple[0], anchors)
    right = resolve_anchor(couple[1], anchors)

    if left.tag == right.tag:
        raise ValueError("--couple does not allow identical anchors")

    if left.sort_key > right.sort_key:
        raise ValueError("--couple does not allow descending canonical order")

    return [(left, right)]


def load_state(path: Path) -> Dict:
    if not path.exists():
        return {
            "schema_version": 1,
            "couples": [],
            "lineage_warnings": [],
            "rejected": [],
        }

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    data.setdefault("schema_version", 1)
    data.setdefault("couples", [])
    data.setdefault("lineage_warnings", [])
    data.setdefault("rejected", [])

    return data


def save_state(path: Path, data: Dict) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def record_rejections(data: Dict, duplicates: Dict[str, List[Anchor]]) -> None:
    data["rejected"] = []
    detected_at = now_iso()

    for tag, items in sorted(duplicates.items()):
        data["rejected"].append(
            {
                "reason": "anchor_ambiguous",
                "anchor": tag,
                "version_dirs": [a.dirname for a in items],
                "detected_at": detected_at,
            }
        )


def record_lineage_warnings(
    data: Dict,
    warnings: List[Tuple[Anchor, List[Anchor]]],
) -> None:
    data["lineage_warnings"] = []
    detected_at = now_iso()

    for anchor, later_than in warnings:
        data["lineage_warnings"].append(
            {
                "anchor": anchor.tag,
                "captured_at": (
                    anchor.captured_at.isoformat(timespec="minutes")
                    if anchor.captured_at
                    else None
                ),
                "later_than": [a.tag for a in later_than],
                "detected_at": detected_at,
            }
        )


def read_utf8(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def unified_diff_for_file(
    old_path: Path,
    new_path: Path,
    rel: str,
    from_label: str,
    to_label: str,
) -> Tuple[List[str], int, bool, bool]:
    old_text = read_utf8(old_path)
    new_text = read_utf8(new_path)

    if old_text is None or new_text is None:
        return [], 0, False, False

    diff_lines_full = list(
        difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile=f"{from_label}:{rel}",
            tofile=f"{to_label}:{rel}",
            lineterm="",
            n=DIFF_CONTEXT_LINES,
        )
    )

    changed_volume = sum(
        1
        for line in diff_lines_full
        if (line.startswith("+") or line.startswith("-"))
        and not line.startswith("+++")
        and not line.startswith("---")
    )

    truncated = False
    diff_lines = diff_lines_full

    if len(diff_lines_full) > MAX_LINES_PER_FILE:
        hidden = len(diff_lines_full) - MAX_LINES_PER_FILE
        diff_lines = diff_lines_full[:MAX_LINES_PER_FILE]
        diff_lines.append(f"[... {hidden} additional lines hidden]")
        truncated = True

    return diff_lines, changed_volume, True, truncated


def top_domain(path: str) -> str:
    first = path.split("/", 1)[0]
    return first if first else "(root)"


def extension_of(path: str) -> str:
    suffix = Path(path).suffix
    return suffix if suffix else "(no extension)"


def compare_snapshots(left: Anchor, right: Anchor) -> Dict:
    old_index = index_snapshot(left.path)
    new_index = index_snapshot(right.path)

    old_keys = set(old_index)
    new_keys = set(new_index)

    added = sorted(new_keys - old_keys)
    deleted = sorted(old_keys - new_keys)
    modified = sorted(
        k
        for k in old_keys & new_keys
        if old_index[k].sha256 != new_index[k].sha256
        or old_index[k].size != new_index[k].size
    )

    detailed_files = []
    additional_modified = []
    binary_modified = []
    truncated_files = []
    total_output_bytes = 0
    output_size_truncated = False

    for rel in modified:
        old_path = left.path / rel
        new_path = right.path / rel

        if len(detailed_files) >= MAX_DETAILED_FILES:
            additional_modified.append(rel)
            continue

        diff_lines, changed_volume, is_text, was_truncated = unified_diff_for_file(
            old_path,
            new_path,
            rel,
            left.tag,
            right.tag,
        )

        if not is_text:
            binary_modified.append(rel)
            continue

        block = "\n".join(diff_lines)
        block_bytes = len(block.encode("utf-8"))

        if total_output_bytes + block_bytes > MAX_OUTPUT_SIZE_BYTES:
            output_size_truncated = True
            additional_modified.append(rel)
            continue

        total_output_bytes += block_bytes

        if was_truncated:
            truncated_files.append(rel)

        detailed_files.append(
            {
                "path": rel,
                "lines": diff_lines,
                "changed_volume": changed_volume,
            }
        )

    return {
        "added": added,
        "deleted": deleted,
        "modified": modified,
        "detailed_files": detailed_files,
        "additional_modified": additional_modified,
        "binary_modified": binary_modified,
        "truncated_files": truncated_files,
        "output_size_truncated": output_size_truncated,
        "old_index": old_index,
        "new_index": new_index,
    }


def build_diff_markdown(
    left: Anchor,
    right: Anchor,
    from_hash: str,
    to_hash: str,
    result: Dict,
) -> str:
    lines: List[str] = []

    lines.append(f"# Release diff {left.tag} → {right.tag}")
    lines.append("")
    lines.append("## Header")
    lines.append("")
    lines.append(f"- From: `{left.tag}` — `{left.dirname}`")
    lines.append(f"- To: `{right.tag}` — `{right.dirname}`")
    lines.append(f"- From sha256: `{from_hash}`")
    lines.append(f"- To sha256: `{to_hash}`")
    lines.append(f"- Produced at: `{now_iso()}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Added files: {len(result['added'])}")
    lines.append(f"- Deleted files: {len(result['deleted'])}")
    lines.append(f"- Modified files: {len(result['modified'])}")
    lines.append(f"- Detailed text files: {len(result['detailed_files'])}")
    lines.append(f"- Modified binary files: {len(result['binary_modified'])}")
    lines.append(f"- Modified files not detailed: {len(result['additional_modified'])}")
    lines.append("")

    lines.append("## Added files")
    lines.append("")

    if result["added"]:
        for p in result["added"]:
            lines.append(f"- `{p}`")
    else:
        lines.append("- None.")

    lines.append("")
    lines.append("## Deleted files")
    lines.append("")

    if result["deleted"]:
        for p in result["deleted"]:
            lines.append(f"- `{p}`")
    else:
        lines.append("- None.")

    lines.append("")

    if result["binary_modified"]:
        lines.append("## Modified binary files")
        lines.append("")

        for p in result["binary_modified"]:
            old = result["old_index"][p].sha256
            new = result["new_index"][p].sha256
            lines.append(f"- `{p}`: `{old}` → `{new}`")

        lines.append("")

    lines.append("## Detailed modified files")
    lines.append("")

    if result["detailed_files"]:
        for item in result["detailed_files"]:
            lines.append(f"### `{item['path']}`")
            lines.append("")
            lines.append("```diff")
            lines.extend(item["lines"])
            lines.append("```")
            lines.append("")
    else:
        lines.append("- No detailed modified text file.")
        lines.append("")

    if result["additional_modified"]:
        lines.append("## Additional modified files not detailed")
        lines.append("")
        lines.append(
            "The following files were modified but not detailed because safety limits were reached."
        )
        lines.append("")

        for p in result["additional_modified"]:
            lines.append(f"- `{p}`")

        lines.append("")

    if result["truncated_files"] or result["output_size_truncated"]:
        lines.append("## Truncation")
        lines.append("")
        lines.append(f"- max lines per file: {MAX_LINES_PER_FILE}")
        lines.append(f"- max detailed files: {MAX_DETAILED_FILES}")
        lines.append(f"- max Markdown size: {MAX_OUTPUT_SIZE_BYTES} bytes")

        if result["output_size_truncated"]:
            lines.append("- `max_output_size` limit reached.")

        if result["truncated_files"]:
            lines.append("- truncated files:")

            for p in result["truncated_files"]:
                lines.append(f"  - `{p}`")

        lines.append("")

    lines.append("## Note")
    lines.append("")
    lines.append("Renames are not interpreted: a rename appears as deletion + addition.")
    lines.append("")

    return "\n".join(lines)


def build_digest_markdown(left: Anchor, right: Anchor, result: Dict) -> str:
    all_paths = result["added"] + result["deleted"] + result["modified"]

    by_domain: Dict[str, int] = {}
    by_ext: Dict[str, int] = {}

    for p in all_paths:
        by_domain[top_domain(p)] = by_domain.get(top_domain(p), 0) + 1
        by_ext[extension_of(p)] = by_ext.get(extension_of(p), 0) + 1

    top_files = sorted(
        [(item["path"], item["changed_volume"]) for item in result["detailed_files"]],
        key=lambda x: (-x[1], x[0]),
    )[:10]

    lines: List[str] = []

    lines.append(f"# Release digest {left.tag} → {right.tag}")
    lines.append("")
    lines.append("## Statistics")
    lines.append("")
    lines.append(f"- Added: {len(result['added'])}")
    lines.append(f"- Deleted: {len(result['deleted'])}")
    lines.append(f"- Modified: {len(result['modified'])}")
    lines.append(f"- Modified binaries: {len(result['binary_modified'])}")
    lines.append(f"- Detailed text files: {len(result['detailed_files'])}")
    lines.append(f"- Not detailed: {len(result['additional_modified'])}")
    lines.append("")
    lines.append("## Top domains")
    lines.append("")

    for domain, count in sorted(by_domain.items(), key=lambda x: (-x[1], x[0]))[:20]:
        lines.append(f"- `{domain}`: {count}")

    if not by_domain:
        lines.append("- None.")

    lines.append("")
    lines.append("## Top extensions")
    lines.append("")

    for ext, count in sorted(by_ext.items(), key=lambda x: (-x[1], x[0]))[:20]:
        lines.append(f"- `{ext}`: {count}")

    if not by_ext:
        lines.append("- None.")

    lines.append("")
    lines.append("## Top modified files")
    lines.append("")

    if top_files:
        for path, volume in top_files:
            lines.append(f"- `{path}`: {volume} +/- lines")
    else:
        lines.append("- No detailed modified text file.")

    lines.append("")
    lines.append("## Limits")
    lines.append("")
    lines.append(f"- max lines per file: {MAX_LINES_PER_FILE}")
    lines.append(f"- max detailed files: {MAX_DETAILED_FILES}")
    lines.append(f"- max Markdown size: {MAX_OUTPUT_SIZE_BYTES} bytes")
    lines.append(f"- truncated files: {len(result['truncated_files'])}")
    lines.append(f"- max output size reached: {result['output_size_truncated']}")
    lines.append("")
    lines.append("## Note")
    lines.append("")
    lines.append("Statistical digest only. No semantic classification is performed.")
    lines.append("")

    return "\n".join(lines)


def produce_artifacts(
    left: Anchor,
    right: Anchor,
    releases_dir: Path,
    from_hash: str,
    to_hash: str,
) -> Tuple[Path, Path]:
    result = compare_snapshots(left, right)

    diff_path = releases_dir / f"{left.tag}__to__{right.tag}.md"
    digest_path = releases_dir / f"{left.tag}__to__{right.tag}__digest.md"

    atomic_write_text(
        diff_path,
        build_diff_markdown(left, right, from_hash, to_hash, result),
    )
    atomic_write_text(
        digest_path,
        build_digest_markdown(left, right, result),
    )

    return diff_path, digest_path


def find_existing_couple(data: Dict, left: Anchor, right: Anchor) -> Optional[Dict]:
    for item in data["couples"]:
        if item.get("from") == left.tag and item.get("to") == right.tag:
            return item

    return None


def relative_to_or_absolute(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def upsert_couple(
    data: Dict,
    left: Anchor,
    right: Anchor,
    releases_dir: Path,
    state_root: Path,
    force: bool,
    hash_cache: Dict[Path, str],
) -> None:
    diff_path = releases_dir / f"{left.tag}__to__{right.tag}.md"
    digest_path = releases_dir / f"{left.tag}__to__{right.tag}__digest.md"

    from_hash = hash_cache.setdefault(left.path, snapshot_sha256(left.path))
    to_hash = hash_cache.setdefault(right.path, snapshot_sha256(right.path))

    existing = find_existing_couple(data, left, right)
    same_hashes = (
        existing is not None
        and existing.get("from_sha256") == from_hash
        and existing.get("to_sha256") == to_hash
    )

    should_skip = (
        not force
        and existing is not None
        and same_hashes
        and existing.get("status") == "ok"
        and diff_path.exists()
        and digest_path.exists()
    )

    produced_at = existing.get("produced_at") if existing and same_hashes else None
    status = "ok" if should_skip else "pending"

    if not should_skip:
        produce_artifacts(left, right, releases_dir, from_hash, to_hash)
        produced_at = now_iso()
        status = "ok"

    record = {
        "from": left.tag,
        "to": right.tag,
        "from_version_dir": left.dirname,
        "to_version_dir": right.dirname,
        "from_sha256": from_hash,
        "to_sha256": to_hash,
        "status": status,
        "produced_at": produced_at,
        "last_seen_at": now_iso(),
        "is_consecutive": False,
        "diff_path": relative_to_or_absolute(diff_path, state_root),
        "digest_path": relative_to_or_absolute(digest_path, state_root),
    }

    if existing is None:
        data["couples"].append(record)
    else:
        existing.update(record)


def recompute_is_consecutive(data: Dict, anchors: List[Anchor]) -> None:
    pairs = consecutive_tag_pairs(anchors)

    for item in data["couples"]:
        item["is_consecutive"] = (item.get("from"), item.get("to")) in pairs


def version_key(tag: str) -> Tuple[int, int]:
    match = re.match(r"^v(\d+)(?:\.(\d+))?$", tag)

    if not match:
        return (-1, -1)

    return int(match.group(1)), int(match.group(2) or 0)


def write_index(releases_dir: Path, data: Dict) -> None:
    couples = list(data.get("couples", []))
    consecutive = [c for c in couples if c.get("is_consecutive") is True]
    non_consecutive = [c for c in couples if c.get("is_consecutive") is not True]

    consecutive.sort(key=lambda c: version_key(c["to"]), reverse=True)
    non_consecutive.sort(key=lambda c: version_key(c["to"]), reverse=True)

    lines: List[str] = []

    lines.append("# Release diffs")
    lines.append("")
    lines.append("## Consecutive couples")
    lines.append("")

    if consecutive:
        for c in consecutive:
            lines.append(
                f"- `{c['from']} → {c['to']}` — "
                f"[{Path(c['diff_path']).name}]({Path(c['diff_path']).name}) / "
                f"[{Path(c['digest_path']).name}]({Path(c['digest_path']).name}) "
                f"— `{c['status']}`"
            )
    else:
        lines.append("- No consecutive couple recorded.")

    lines.append("")
    lines.append("## Non-consecutive couples")
    lines.append("")

    if non_consecutive:
        for c in non_consecutive:
            lines.append(
                f"- `{c['from']} → {c['to']}` — "
                f"[{Path(c['diff_path']).name}]({Path(c['diff_path']).name}) / "
                f"[{Path(c['digest_path']).name}]({Path(c['digest_path']).name}) "
                f"— `{c['status']}`"
            )
    else:
        lines.append("- No non-consecutive couple recorded.")

    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- Index generated from the release state file.")
    lines.append(
        "- `ok` means that both detailed diff and digest were produced for the recorded hashes."
    )
    lines.append("")

    atomic_write_text(releases_dir / "INDEX_RELEASES.md", "\n".join(lines))


def print_report(
    anchors: List[Anchor],
    duplicates: Dict[str, List[Anchor]],
    lineage_warnings: List[Tuple[Anchor, List[Anchor]]],
    couples: List[Tuple[Anchor, Anchor]],
    dry_run: bool,
    force: bool,
) -> None:
    print("release_diff — release diff engine")
    print(f"dry_run: {dry_run}")
    print(f"force: {force}")
    print("")
    print(f"ANCHORS detected: {len(anchors)}")

    for a in anchors:
        captured = a.captured_at.isoformat(timespec="minutes") if a.captured_at else "unknown"
        print(f"  - {a.tag} | {captured} | {a.dirname}")

    if not anchors:
        print("  - none")

    print("")
    print(f"DUPLICATES rejected: {len(duplicates)}")

    if not duplicates:
        print("  - none")
    else:
        for tag, items in sorted(duplicates.items()):
            print(f"  - {tag}: {', '.join(a.dirname for a in items)}")

    print("")
    print(f"LINEAGE warnings: {len(lineage_warnings)}")

    if not lineage_warnings:
        print("  - none")
    else:
        for anchor, later_than in lineage_warnings:
            print(f"  - {anchor.tag} captured later than {', '.join(a.tag for a in later_than)}")

    print("")
    print(f"COUPLES selected: {len(couples)}")

    pairs = consecutive_tag_pairs(anchors)

    for left, right in couples:
        print(
            f"  - {left.tag} -> {right.tag} | "
            f"consecutive={'yes' if (left.tag, right.tag) in pairs else 'no'}"
        )

    if not couples:
        print("  - none")

    print("")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate release diffs between versioned Home Assistant snapshots."
    )

    parser.add_argument(
        "--versions-dir",
        required=True,
        help="Directory containing immutable extracted versions.",
    )
    parser.add_argument(
        "--releases-dir",
        required=True,
        help="Directory where release diff Markdown files will be written.",
    )
    parser.add_argument(
        "--state-path",
        required=True,
        help="Path to the persistent processed releases JSON state file.",
    )
    parser.add_argument(
        "--state-root",
        default=None,
        help="Optional root used to store relative artifact paths in state.",
    )
    parser.add_argument(
        "--couple",
        nargs=2,
        metavar=("FROM", "TO"),
        help="Generate a diff for a specific release couple, for example: --couple v1 v2.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print detected anchors and selected couples without writing files.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate artifacts even when hashes and outputs are already present.",
    )

    args = parser.parse_args(argv)

    versions_dir = Path(args.versions_dir).expanduser().resolve()
    releases_dir = Path(args.releases_dir).expanduser().resolve()
    state_path = Path(args.state_path).expanduser().resolve()
    state_root = (
        Path(args.state_root).expanduser().resolve()
        if args.state_root
        else state_path.parent.parent
    )

    try:
        anchors, duplicates = scan_anchors(versions_dir)
        lineage_warnings = detect_lineage_warnings(anchors)
        couples = selected_couples(anchors, args.couple)

        print_report(
            anchors=anchors,
            duplicates=duplicates,
            lineage_warnings=lineage_warnings,
            couples=couples,
            dry_run=args.dry_run,
            force=args.force,
        )

        if args.dry_run:
            print("WRITE: none")
            print("DIFF: none")
            return 0

        releases_dir.mkdir(parents=True, exist_ok=True)

        data = load_state(state_path)

        record_rejections(data, duplicates)
        record_lineage_warnings(data, lineage_warnings)

        hash_cache: Dict[Path, str] = {}

        for left, right in couples:
            upsert_couple(
                data=data,
                left=left,
                right=right,
                releases_dir=releases_dir,
                state_root=state_root,
                force=args.force,
                hash_cache=hash_cache,
            )

        recompute_is_consecutive(data, anchors)
        save_state(state_path, data)
        write_index(releases_dir, data)

        print(f"WRITE: {state_path}")
        print(f"WRITE: {releases_dir / 'INDEX_RELEASES.md'}")
        print("DIFF: produced/skipped according to idempotence")

        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())