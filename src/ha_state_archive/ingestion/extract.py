#!/usr/bin/env python3
"""
extract.py -- Home Assistant backup ingestion for ha-state-archive.

Detects Home Assistant encrypted backups stored on an external infrastructure
(e.g. a NAS), extracts the relevant configuration and state files using
hassio-tar, and produces immutable versioned directories ready for audit
and diff processing.

Design goals:
- backup source directory is never modified;
- decryption key is never logged;
- temporary extraction directories are always cleaned up;
- partial extractions due to older backup structures are tolerated;
- state file prevents redundant reprocessing;
- extraction is atomic: target directory is only committed on success.

Prerequisites:
- HASSIO_PASSWORD must be set in the environment;
- hassio-tar binary must be present and executable at the path
  configured via --hassio-tar or HSA_HASSIO_TAR.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Patrimoine paths
# ---------------------------------------------------------------------------

# Paths extracted from each backup.
# Absent paths are tolerated: older backup structures may not include all of them.
_PATRIMOINE_PATHS = [
    "data/configuration.yaml",
    "data/recorder.yaml",
    "data/utility_meter.yaml",
    # Minimal registry required by the audit engine.
    # Only core.entity_registry is extracted.
    # Other .storage files are excluded as they may contain
    # credentials, tokens or authentication data.
    # The diff engine explicitly excludes .storage from its scope
    # (see release_diff.py EXCLUDE_PATTERNS).
    "data/.storage/core.entity_registry",
    "data/00_documentation",
    "data/01_customize",
    "data/02_groups",
    "data/03_input_numbers",
    "data/04_input_texts",
    "data/05_input_booleans",
    "data/06_input_selects",
    "data/07_input_datetimes",
    "data/08_timers",
    "data/09_counters",
    "data/10_scripts",
    "data/11_automations",
    "data/12_template_sensors",
    "data/13_sensor_platforms",
    "data/14_mqtt_sensors",
    "data/15_mqtt_binary_sensors",
    "data/16_template_alarm_panels",
    "data/17_zones",
    "data/18_lovelace",
    "data/19_button_card_templates",
]

# Extraction is rejected if this path is absent from the backup.
_REQUIRED_PATH = "data/configuration.yaml"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class ExtractionResult:
    def __init__(
        self,
        *,
        status: str,
        target: Path,
        extracted_paths: List[str],
        missing_paths: List[str],
    ) -> None:
        self.status = status
        self.target = target
        self.extracted_paths = extracted_paths
        self.missing_paths = missing_paths


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(message: str) -> None:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {message}", flush=True)


def _fail(message: str, code: int = 1) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# State file
# ---------------------------------------------------------------------------

def _load_state(state_path: Path) -> Dict[str, Dict]:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"State file is not valid JSON: {state_path}: {exc}") from exc


def _save_state(state_path: Path, state: Dict[str, Dict]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(state_path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _sanitize_label(value: str) -> str:
    value = value.strip().replace(" ", "_")
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_") or "backup"


def _parse_date_from_filename(name: str) -> Optional[dt.datetime]:
    m = re.search(r"(?P<date>\d{4}-\d{2}-\d{2})_(?P<h>\d{2})\.(?P<m>\d{2})", name)
    if not m:
        return None
    return dt.datetime.strptime(
        f"{m.group('date')} {m.group('h')}:{m.group('m')}",
        "%Y-%m-%d %H:%M",
    )


def _parse_date_arg(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d_%H-%M", "%Y-%m-%d %H:%M"):
        try:
            return dt.datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise ValueError(
        f"Invalid date: {value!r}. Accepted formats: YYYY-MM-DD or YYYY-MM-DD_HH-MM"
    )


def _read_meta(backup: Path) -> Dict:
    meta_path = backup.with_name(backup.stem + "_meta.json")
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid meta JSON: {meta_path}: {exc}") from exc


def _backup_datetime(backup: Path, meta: Dict) -> dt.datetime:
    date_raw = meta.get("date")
    if isinstance(date_raw, str):
        try:
            return dt.datetime.fromisoformat(date_raw).replace(tzinfo=None)
        except ValueError:
            pass

    parsed = _parse_date_from_filename(backup.name)
    if parsed is not None:
        return parsed

    return dt.datetime.fromtimestamp(backup.stat().st_mtime)


def _version_dir_name(backup: Path, meta: Dict) -> str:
    backup_id = str(meta.get("backup_id") or "")
    display_name = str(meta.get("name") or backup.stem)

    ts = _backup_datetime(backup, meta)
    date_part = ts.strftime("%Y-%m-%d_%H-%M")
    label = _sanitize_label(display_name)

    m = re.search(r"_(\d{8})\.tar$", backup.name)
    file_id = m.group(1) if m else ""
    suffix = backup_id or file_id

    if suffix:
        return f"{date_part}_{label}_{_sanitize_label(suffix)}"
    return f"{date_part}_{label}"


# ---------------------------------------------------------------------------
# Backup listing
# ---------------------------------------------------------------------------

def _list_backups(
    backup_dir: Path,
    *,
    since_date: Optional[dt.datetime],
    limit: Optional[int],
) -> List[Tuple[Path, Dict]]:
    items: List[Tuple[Path, Dict, dt.datetime]] = []

    for backup in backup_dir.glob("*.tar"):
        meta = _read_meta(backup)
        ts = _backup_datetime(backup, meta)

        if since_date and ts < since_date:
            continue

        items.append((backup, meta, ts))

    items.sort(key=lambda x: x[2])

    if limit is not None and limit > 0:
        items = items[-limit:]

    return [(backup, meta) for backup, meta, _ in items]


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

def _check_prerequisites(backup_dir: Path, hassio_tar: Path) -> None:
    if not backup_dir.exists() or not backup_dir.is_dir():
        _fail(f"Backup directory not found: {backup_dir}")

    if not hassio_tar.exists():
        _fail(f"hassio-tar binary not found: {hassio_tar}")

    if not os.access(hassio_tar, os.X_OK):
        _fail(f"hassio-tar is not executable: {hassio_tar}")

    if not os.environ.get("HASSIO_PASSWORD"):
        _fail(
            "HASSIO_PASSWORD is not set. "
            "Set it before running: "
            "read -ersp 'Backup password: ' HASSIO_PASSWORD && export HASSIO_PASSWORD"
        )


# ---------------------------------------------------------------------------
# Archive inspection and extraction
# ---------------------------------------------------------------------------

def _list_inner_paths(backup: Path, hassio_tar: Path) -> List[str]:
    cmd = (
        f'tar -xOf "{backup}" homeassistant.tar.gz'
        f' | "{hassio_tar}"'
        f' | tar -tz'
    )
    result = subprocess.run(
        ["/bin/sh", "-c", cmd],
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to list encrypted archive: {backup}\n"
            f"STDERR:\n{result.stderr}"
        )
    return [line.strip().lstrip("./") for line in result.stdout.splitlines() if line.strip()]


def _resolve_present_paths(
    available: List[str],
) -> Tuple[List[str], List[str]]:
    available_set = set(available)
    present: List[str] = []
    missing: List[str] = []

    for wanted in _PATRIMOINE_PATHS:
        normalized = wanted.strip().lstrip("./")
        dir_prefix = normalized.rstrip("/") + "/"

        if normalized in available_set or any(p.startswith(dir_prefix) for p in available_set):
            present.append(normalized)
        else:
            missing.append(normalized)

    return present, missing


def _extract_backup(
    backup: Path,
    target: Path,
    temp_dir: Path,
    hassio_tar: Path,
    *,
    force: bool,
) -> ExtractionResult:
    if target.exists():
        if not force:
            raise RuntimeError(f"Version already extracted: {target}")
        shutil.rmtree(target)

    _log(f"Listing archive contents: {backup.name}")
    available = _list_inner_paths(backup, hassio_tar)
    present, missing = _resolve_present_paths(available)

    if not present:
        raise RuntimeError("No extractable paths found in archive.")

    if _REQUIRED_PATH not in present:
        raise RuntimeError(f"Extraction refused: {_REQUIRED_PATH} is absent.")

    tmp = temp_dir / f".extract_{target.name}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    _log(f"Extracting: {backup.name} -> {tmp.name}")
    if missing:
        _log(f"Tolerated absent paths: {len(missing)}")

    cmd = (
        f'tar -xOf "{backup}" homeassistant.tar.gz'
        f' | "{hassio_tar}"'
        f' | tar -xz -C "{tmp}" --strip-components=1'
        + " " + " ".join(f'"{p}"' for p in present)
    )

    result = subprocess.run(
        ["/bin/sh", "-c", cmd],
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(
            f"Extraction failed: {backup}\n"
            f"STDERR:\n{result.stderr}"
        )

    if not (tmp / "configuration.yaml").exists():
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError("Extraction inconsistent: configuration.yaml missing after extract.")

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp.replace(target)

    status = "partial" if missing else "ok"
    _log(f"Version created: {target.name} [{status}]")

    return ExtractionResult(
        status=status,
        target=target,
        extracted_paths=present,
        missing_paths=missing,
    )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def _state_entry(
    *,
    backup: Path,
    backup_sha: str,
    target_name: str,
    meta: Dict,
    status: str,
    extracted_paths: List[str],
    missing_paths: List[str],
    error: str,
) -> Dict:
    return {
        "sha256": backup_sha,
        "version_dir": target_name,
        "processed_at": dt.datetime.now().isoformat(timespec="seconds"),
        "meta_name": str(meta.get("name", "")),
        "meta_date": str(meta.get("date", "")),
        "homeassistant_version": str(meta.get("homeassistant_version", "")),
        "status": status,
        "extracted_paths": extracted_paths,
        "missing_paths": missing_paths,
        "error": error,
    }


def _process(
    *,
    backup_dir: Path,
    versions_dir: Path,
    temp_dir: Path,
    state_path: Path,
    hassio_tar: Path,
    latest_only: bool,
    limit: Optional[int],
    since_date: Optional[dt.datetime],
    force: bool,
    dry_run: bool,
    continue_on_error: bool,
) -> int:
    versions_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    _check_prerequisites(backup_dir, hassio_tar)

    state = _load_state(state_path)

    effective_limit = 1 if latest_only else limit
    backups = _list_backups(backup_dir, since_date=since_date, limit=effective_limit)

    if not backups:
        _log("No backups found matching the current filters.")
        return 0

    processed = 0
    failed = 0

    for backup, meta in backups:
        backup_sha = _sha256_file(backup)
        target_name = _version_dir_name(backup, meta)
        target = versions_dir / target_name

        previous = state.get(backup.name, {})
        already_done = (
            previous.get("status") in ("ok", "partial")
            and previous.get("sha256") == backup_sha
            and target.exists()
        )

        if already_done and not force:
            _log(f"Already processed, skipping: {backup.name}")
            continue

        _log(f"Candidate: {backup.name}")
        _log(f"Target version: {target_name}")

        if dry_run:
            continue

        try:
            result = _extract_backup(
                backup, target, temp_dir, hassio_tar, force=force
            )
            state[backup.name] = _state_entry(
                backup=backup,
                backup_sha=backup_sha,
                target_name=target.name,
                meta=meta,
                status=result.status,
                extracted_paths=result.extracted_paths,
                missing_paths=result.missing_paths,
                error="",
            )
            _save_state(state_path, state)
            processed += 1

        except Exception as exc:
            failed += 1
            _log(f"Extraction failed: {backup.name}: {exc}")
            state[backup.name] = _state_entry(
                backup=backup,
                backup_sha=backup_sha,
                target_name=target_name,
                meta=meta,
                status="failed",
                extracted_paths=[],
                missing_paths=[],
                error=str(exc),
            )
            _save_state(state_path, state)
            if not continue_on_error:
                raise

    if not processed and not failed:
        _log("No new backups to process.")

    if failed:
        _log(f"Failed extractions: {failed}")

    return processed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="extract",
        description=(
            "Ingest Home Assistant encrypted backups into versioned "
            "immutable directories for ha-state-archive processing."
        ),
    )

    parser.add_argument(
        "--backup-dir",
        required=True,
        help="Directory containing Home Assistant .tar backup files.",
    )
    parser.add_argument(
        "--versions-dir",
        required=True,
        help="Output directory for extracted immutable version directories.",
    )
    parser.add_argument(
        "--temp-dir",
        required=True,
        help="Temporary directory used during atomic extraction.",
    )
    parser.add_argument(
        "--state",
        required=True,
        help="Path to the JSON state file tracking processed backups.",
    )
    parser.add_argument(
        "--hassio-tar",
        default=os.environ.get("HSA_HASSIO_TAR", ""),
        help=(
            "Path to the hassio-tar binary used to decrypt backups. "
            "Can also be set via HSA_HASSIO_TAR."
        ),
    )
    parser.add_argument(
        "--latest-only",
        action="store_true",
        help="Process only the most recent backup.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N most recent backups after filtering.",
    )
    parser.add_argument(
        "--since-date",
        default=None,
        help="Skip backups older than this date. Formats: YYYY-MM-DD or YYYY-MM-DD_HH-MM.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract even if the backup has already been processed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List candidates without performing any extraction.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop on first extraction failure. By default errors are logged and skipped.",
    )

    args = parser.parse_args(argv)

    if not args.hassio_tar:
        _fail(
            "hassio-tar path is required. "
            "Use --hassio-tar or set HSA_HASSIO_TAR."
        )

    try:
        since_date = _parse_date_arg(args.since_date)
    except ValueError as exc:
        _fail(str(exc))
        return 1  # unreachable, satisfies type checker

    try:
        _process(
            backup_dir=Path(args.backup_dir),
            versions_dir=Path(args.versions_dir),
            temp_dir=Path(args.temp_dir),
            state_path=Path(args.state),
            hassio_tar=Path(args.hassio_tar),
            latest_only=args.latest_only,
            limit=args.limit,
            since_date=since_date,
            force=args.force,
            dry_run=args.dry_run,
            continue_on_error=not args.stop_on_error,
        )
    except Exception as exc:
        _log(f"FATAL: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
