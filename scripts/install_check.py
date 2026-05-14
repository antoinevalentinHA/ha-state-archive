#!/usr/bin/env python3
"""
install_check.py — ha-state-archive environment verifier.

Verifies that the local environment meets the requirements to run
ha-state-archive. Does not modify anything.

Usage:
    python3 install_check.py --root /volume1/Backups_HA/ha_backup_timeline
    python3 install_check.py --root /volume1/Backups_HA/ha_backup_timeline \\
                             --mqtt-env /volume1/Backups_HA/ha_backup_timeline/config/mqtt.env

Exit codes:
    0  All checks passed (warnings allowed).
    1  One or more warnings (non-blocking).
    2  One or more errors (blocking).

Design rule:
    This script has no dependency on the package it verifies.
    It uses stdlib only and can be executed before installation.
"""

from __future__ import annotations

import argparse
import importlib
import os
import shutil
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

OK   = "OK"
WARN = "WARN"
FAIL = "FAIL"

_results: list[tuple[str, str]] = []


def record(status: str, message: str) -> None:
    _results.append((status, message))
    label = f"[{status}]"
    print(f"{label:<8} {message}")


def ok(message: str)   -> None: record(OK,   message)
def warn(message: str) -> None: record(WARN, message)
def fail(message: str) -> None: record(FAIL, message)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_python_version() -> None:
    major, minor = sys.version_info[:2]
    version_str = f"Python {major}.{minor}"

    if (major, minor) >= (3, 11):
        ok(f"{version_str}")
    else:
        fail(f"{version_str} — Python >= 3.11 required")


def check_root(root: Path) -> bool:
    """Returns True if root exists and is usable, False otherwise."""
    if not root.exists():
        fail(f"root path does not exist: {root}")
        return False

    if not root.is_dir():
        fail(f"root path is not a directory: {root}")
        return False

    ok(f"root path exists: {root}")

    if os.access(root, os.W_OK):
        ok(f"root path is writable")
    else:
        fail(f"root path is not writable: {root}")

    return True


EXPECTED_SUBDIRS = [
    "versions",
    "reports",
    "diffs",
    "quarantine",
    "config",
    "logs",
]


def check_subdirs(root: Path) -> None:
    for name in EXPECTED_SUBDIRS:
        path = root / name

        if path.exists() and path.is_dir():
            ok(f"subdirectory present: {name}/")
        elif path.exists():
            fail(f"subdirectory path exists but is not a directory: {name}")
        else:
            warn(f"subdirectory missing: {name}/")


def check_retention_policy(root: Path) -> None:
    candidates = [
        root / "config" / "retention_policy.yaml",
        root / "config" / "retention_policy.yml",
    ]

    for path in candidates:
        if path.exists():
            if os.access(path, os.R_OK):
                ok(f"retention policy found: {path.relative_to(root)}")
            else:
                fail(f"retention policy not readable: {path.relative_to(root)}")
            return

    fail(f"retention policy missing (expected: config/retention_policy.yaml)")


_REQUIRED_MQTT_KEYS = (
    "MQTT_HOST",
    "MQTT_PORT",
    "MQTT_USERNAME",
    "MQTT_PASSWORD",
)

_ENV_LINE_PREFIXES = tuple(f"{k}=" for k in _REQUIRED_MQTT_KEYS)


def check_mqtt_env(mqtt_env_path: Path) -> None:
    if not mqtt_env_path.exists():
        fail(f"MQTT env file not found: {mqtt_env_path}")
        return

    if not os.access(mqtt_env_path, os.R_OK):
        fail(f"MQTT env file not readable: {mqtt_env_path}")
        return

    try:
        content = mqtt_env_path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"MQTT env file could not be read: {exc}")
        return

    found_keys: set[str] = set()

    for line in content.splitlines():
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        for key in _REQUIRED_MQTT_KEYS:
            if line.startswith(f"{key}=") or line.startswith(f'{key}="'):
                found_keys.add(key)

    missing = [k for k in _REQUIRED_MQTT_KEYS if k not in found_keys]

    if missing:
        fail(f"MQTT env file missing keys: {', '.join(missing)}")
    else:
        ok(f"MQTT env file valid: {mqtt_env_path}")


def check_package_importable() -> None:
    try:
        importlib.import_module("ha_state_archive")
        ok("package importable: ha_state_archive")
    except ImportError:
        warn("package not importable: ha_state_archive (not installed or not in PYTHONPATH)")


def check_commands() -> None:
    for cmd in ("tar", "gzip"):
        path = shutil.which(cmd)

        if path:
            ok(f"command available: {cmd} ({path})")
        else:
            fail(f"command not found: {cmd}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="install_check",
        description=(
            "Verify that the local environment meets ha-state-archive requirements. "
            "Does not modify anything."
        ),
    )
    parser.add_argument(
        "--root",
        required=True,
        metavar="PATH",
        help="Root directory of the ha-state-archive timeline.",
    )
    parser.add_argument(
        "--mqtt-env",
        default=None,
        metavar="PATH",
        help=(
            "Path to the MQTT credentials env file. "
            "If not provided, MQTT configuration is not checked."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).expanduser().resolve()

    print(f"ha-state-archive — install check")
    print(f"root: {root}")
    if args.mqtt_env:
        print(f"mqtt-env: {args.mqtt_env}")
    print()

    check_python_version()
    root_ok = check_root(root)

    if root_ok:
        check_subdirs(root)
        check_retention_policy(root)

    if args.mqtt_env:
        check_mqtt_env(Path(args.mqtt_env).expanduser().resolve())
    else:
        warn("MQTT configuration not checked (--mqtt-env not provided)")

    check_package_importable()
    check_commands()

    print()

    has_fail = any(s == FAIL for s, _ in _results)
    has_warn = any(s == WARN for s, _ in _results)

    fails = sum(1 for s, _ in _results if s == FAIL)
    warns = sum(1 for s, _ in _results if s == WARN)
    oks   = sum(1 for s, _ in _results if s == OK)

    print(f"Results: {oks} OK, {warns} WARN, {fails} FAIL")

    if has_fail:
        print("Status: ENVIRONMENT NOT READY")
        return 2

    if has_warn:
        print("Status: READY WITH WARNINGS")
        return 1

    print("Status: READY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
