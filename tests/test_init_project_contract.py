"""
test_init_project_contract.py — contractual tests for ha-state-init.

Invariants:
    I1  dry-run produces no filesystem changes
    I2  --apply creates all expected directories
    I3  --apply creates retention_policy.yaml
    I4  second --apply skips existing items (no overwrite) and returns exit 1
    I5  retention_policy.yaml content is not overwritten on second apply
    I6  install_check reports no FAIL after --apply
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


INIT_SCRIPT = Path(__file__).parent.parent / "scripts" / "init_project.py"
CHECK_SCRIPT = Path(__file__).parent.parent / "scripts" / "install_check.py"

EXPECTED_DIRS = ["versions", "quarantine", "config", "reports", "diffs", "logs"]
RETENTION_POLICY = Path("config") / "retention_policy.yaml"


def run_init(root: Path, apply: bool = False) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(INIT_SCRIPT), "--root", str(root)]
    if apply:
        cmd.append("--apply")
    return subprocess.run(cmd, capture_output=True, text=True)


def run_check(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECK_SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# I1 — dry-run produces no filesystem changes
# ---------------------------------------------------------------------------

def test_I1_dryrun_no_filesystem_changes(tmp_path):
    root = tmp_path / "ha_archive"
    result = run_init(root, apply=False)

    assert result.returncode == 0
    assert not root.exists(), "dry-run must not create root directory"
    assert "DRY-RUN" in result.stdout


# ---------------------------------------------------------------------------
# I2 — --apply creates all expected directories
# ---------------------------------------------------------------------------

def test_I2_apply_creates_expected_directories(tmp_path):
    root = tmp_path / "ha_archive"
    result = run_init(root, apply=True)

    assert result.returncode == 0
    for name in EXPECTED_DIRS:
        assert (root / name).is_dir(), f"expected directory missing: {name}/"


# ---------------------------------------------------------------------------
# I3 — --apply creates retention_policy.yaml
# ---------------------------------------------------------------------------

def test_I3_apply_creates_retention_policy(tmp_path):
    root = tmp_path / "ha_archive"
    run_init(root, apply=True)

    policy = root / RETENTION_POLICY
    assert policy.exists(), "retention_policy.yaml must be created"
    assert policy.stat().st_size > 0, "retention_policy.yaml must not be empty"


# ---------------------------------------------------------------------------
# I4 — second --apply skips existing items and returns exit 1
# ---------------------------------------------------------------------------

def test_I4_second_apply_skips_and_returns_1(tmp_path):
    root = tmp_path / "ha_archive"
    run_init(root, apply=True)
    result = run_init(root, apply=True)

    assert result.returncode == 1, "second apply must return exit 1 (partial/skipped)"
    assert "SKIP" in result.stdout


# ---------------------------------------------------------------------------
# I5 — retention_policy.yaml is never overwritten
# ---------------------------------------------------------------------------

def test_I5_retention_policy_not_overwritten(tmp_path):
    root = tmp_path / "ha_archive"
    run_init(root, apply=True)

    policy = root / RETENTION_POLICY
    sentinel = "# SENTINEL_DO_NOT_OVERWRITE\n"
    original = policy.read_text(encoding="utf-8")
    policy.write_text(sentinel + original, encoding="utf-8")

    run_init(root, apply=True)

    content = policy.read_text(encoding="utf-8")
    assert content.startswith(sentinel), "retention_policy.yaml must not be overwritten"


# ---------------------------------------------------------------------------
# I6 — install_check reports no FAIL after --apply
# ---------------------------------------------------------------------------

def test_I6_install_check_no_fail_after_apply(tmp_path):
    root = tmp_path / "ha_archive"
    run_init(root, apply=True)

    result = run_check(root)

    assert "[FAIL]" not in result.stdout, (
        f"install_check must report no FAIL after ha-state-init --apply\n{result.stdout}"
    )
    # exit 0 (ready) or 1 (warnings) are both acceptable
    assert result.returncode in (0, 1)
