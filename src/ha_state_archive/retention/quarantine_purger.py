#!/usr/bin/env python3
"""
quarantine_purger.py — Home Assistant archive delayed purge engine.

Design goals:
- safe path validation (strictly under quarantine root);
- mandatory double-confirmation (policy flag + CLI flag);
- dated directory targeting (YYYY-MM-DD);
- traceable Markdown reporting;
- zero-deletion by default.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime, date
from pathlib import Path

import yaml

VERSION = "0.1.0"
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ERROR_ALLOW_PURGE = "allow_purge_must_be_true_in_policy"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Home Assistant archive quarantine purger")
    parser.add_argument("--quarantine", required=True, help="Path to the _quarantine directory")
    parser.add_argument("--policy", required=True, help="Path to the purge policy YAML file")
    parser.add_argument("--report", required=True, help="Path to the Markdown report to produce")
    parser.add_argument("--apply", action="store_true", help="Apply planned deletions")
    return parser.parse_args()


def load_policy(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return {
        "quarantine_min_age_days": data.get("quarantine_min_age_days"),
        "allow_purge": data.get("allow_purge"),
    }


def validate_policy(policy: dict) -> list[str]:
    errors = []
    min_age = policy.get("quarantine_min_age_days")
    if not isinstance(min_age, int) or min_age < 0:
        errors.append("quarantine_min_age_days_must_be_positive_integer")
    if policy.get("allow_purge") is not True:
        errors.append(ERROR_ALLOW_PURGE)
    return errors


def resolve_path(path: str) -> Path:
    return Path(path).expanduser().resolve()


def is_strictly_under(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return child != parent
    except ValueError:
        return False


def parse_folder_date(name: str) -> date | None:
    if not DATE_PATTERN.match(name):
        return None
    try:
        return datetime.strptime(name, "%Y-%m-%d").date()
    except ValueError:
        return None


def scan_quarantine(quarantine_path: Path, min_age_days: int) -> list[dict]:
    today = date.today()
    rows = []

    if not quarantine_path.exists():
        return []

    for item in sorted(quarantine_path.iterdir(), key=lambda p: p.name):
        folder_date = parse_folder_date(item.name)

        if not item.is_dir():
            rows.append({
                "folder": item.name,
                "path": item,
                "age_days": "",
                "decision": "KEEP_QUARANTINE_INVALID",
                "reason": "not_a_directory",
                "purge_planned": False,
                "purge_done": False,
                "purge_error": "",
            })
            continue

        if folder_date is None:
            rows.append({
                "folder": item.name,
                "path": item,
                "age_days": "",
                "decision": "KEEP_QUARANTINE_UNDATED",
                "reason": "folder_name_not_matching_YYYY-MM-DD",
                "purge_planned": False,
                "purge_done": False,
                "purge_error": "",
            })
            continue

        age_days = (today - folder_date).days

        if age_days >= min_age_days:
            decision = "PURGE_QUARANTINE_EXPIRED"
            purge_planned = True
            reason = "quarantine_age_expired"
        else:
            decision = "KEEP_QUARANTINE_RECENT"
            purge_planned = False
            reason = "quarantine_age_below_threshold"

        rows.append({
            "folder": item.name,
            "path": item,
            "age_days": age_days,
            "decision": decision,
            "reason": reason,
            "purge_planned": purge_planned,
            "purge_done": False,
            "purge_error": "",
        })

    return rows


def apply_purge(rows: list[dict], quarantine_path: Path, apply: bool) -> list[dict]:
    if not apply:
        return rows

    for row in rows:
        if row["decision"] != "PURGE_QUARANTINE_EXPIRED":
            continue

        target = row["path"].resolve()

        if target == quarantine_path:
            row["decision"] = "PURGE_ERROR"
            row["purge_error"] = "refusing_to_purge_quarantine_root"
            continue

        if not is_strictly_under(target, quarantine_path):
            row["decision"] = "PURGE_ERROR"
            row["purge_error"] = "target_not_strictly_under_quarantine"
            continue

        try:
            shutil.rmtree(target)
            row["purge_done"] = True
        except Exception as exc:
            row["decision"] = "PURGE_ERROR"
            row["purge_error"] = str(exc)

    return rows


def render_report(
    quarantine_path: Path,
    policy: dict,
    rows: list[dict],
    mode: str,
    policy_errors: list[str],
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    counts = {}
    for row in rows:
        counts[row["decision"]] = counts.get(row["decision"], 0) + 1

    planned = sum(1 for row in rows if row["purge_planned"])
    done = sum(1 for row in rows if row["purge_done"])
    errors = sum(1 for row in rows if row["purge_error"])

    lines = [
        "# Quarantine purge report",
        "",
        "## Execution details",
        "",
        f"- **Timestamp**: {now}",
        f"- **Module version**: {VERSION}",
        f"- **Mode**: {mode}",
        f"- **Quarantine directory**: `{quarantine_path}`",
        f"- **Min age days**: {policy.get('quarantine_min_age_days')}",
        f"- **Allow purge (policy)**: `{policy.get('allow_purge')}`",
        "",
    ]

    if policy_errors:
        lines.extend(["## Policy errors", ""])
        for error in policy_errors:
            lines.append(f"- `{error}`")
        lines.extend(["", "> No actions performed. Correct the policy before execution.", ""])

    lines.extend([
        "## Summary by decision",
        "",
        "| Decision | Count |",
        "|---|---:|",
    ])

    for decision in sorted(counts):
        lines.append(f"| `{decision}` | {counts[decision]} |")

    lines.extend([
        "",
        "## Purge summary",
        "",
        f"- **Planned deletions**: {planned}",
        f"- **Completed deletions**: {done}",
        f"- **Errors**: {errors}",
        "",
        "## Detail",
        "",
        "| Folder | Age (days) | Decision | Reason | Planned | Done | Error |",
        "|---|---:|---|---|:---:|:---:|---|",
    ])

    for row in rows:
        lines.append(
            f"| `{row['folder']}` | "
            f"{row['age_days']} | "
            f"`{row['decision']}` | "
            f"`{row['reason']}` | "
            f"{row['purge_planned']} | "
            f"{row['purge_done']} | "
            f"`{row['purge_error']}` |"
        )

    return "\n".join(lines)


def write_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    args = parse_args()
    quarantine_path = resolve_path(args.quarantine)
    policy_path = resolve_path(args.policy)
    mode = "apply" if args.apply else "dry-run"

    policy = load_policy(policy_path)
    policy_errors = validate_policy(policy)

    if not quarantine_path.exists() or not quarantine_path.is_dir():
        policy_errors.append("quarantine_path_must_exist_and_be_directory")

    if policy_errors:
        rows = []
    else:
        rows = scan_quarantine(quarantine_path, policy["quarantine_min_age_days"])
        rows = apply_purge(rows, quarantine_path, args.apply)

    content = render_report(quarantine_path, policy, rows, mode, policy_errors)
    
    report_path = resolve_path(args.report)
    write_report(report_path, content)

    if policy_errors:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()