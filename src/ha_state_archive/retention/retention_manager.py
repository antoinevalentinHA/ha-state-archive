#!/usr/bin/env python3
"""
retention_manager.py — Home Assistant state archive retention manager.

Design goals:
- dry-run by default;
- asymmetric retention;
- quarantine-before-purge;
- explicit blast-radius control;
- traceable Markdown reports.
"""

from __future__ import annotations

import argparse
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import yaml


DECISION_KEEP_MAJOR = "KEEP_MAJOR"
DECISION_KEEP_CRITICAL = "KEEP_CRITICAL"
DECISION_KEEP_AUTOMATIC_RECENT = "KEEP_AUTOMATIC_RECENT"
DECISION_QUARANTINE_AUTOMATIC_OLD = "QUARANTINE_AUTOMATIC_OLD"
DECISION_KEEP_RECENT = "KEEP_RECENT"
DECISION_KEEP_DAILY = "KEEP_DAILY"
DECISION_KEEP_WEEKLY = "KEEP_WEEKLY"
DECISION_CANDIDATE_DELETE = "CANDIDATE_DELETE"


def load_policy(policy_path: Path) -> dict:
    with policy_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def extract_logical_name(name: str) -> str:
    """Extract the logical label from a versioned directory name.

    Expected format produced by the ingestion layer:
        YYYY-MM-DD_HH-MM_<label>_<id>

    Where:
        parts[0] = date        (YYYY-MM-DD)
        parts[1] = time        (HH-MM)
        parts[2:-1] = label    (one or more segments)
        parts[-1] = identifier (backup id or short hash)

    A minimum of 5 underscore-separated parts is required to extract
    a non-empty label. If the name does not conform to this structure,
    the full name is returned unchanged and a warning is emitted.
    This fallback preserves classification behaviour for non-standard
    names at the cost of reduced accuracy.
    """
    parts = name.split("_")

    if len(parts) >= 5:
        return "_".join(parts[2:-1])

    import sys
    print(
        f"[retention_manager] WARNING: directory name does not match expected "
        f"format YYYY-MM-DD_HH-MM_<label>_<id>: {name!r}. "
        f"Falling back to full name for classification.",
        file=sys.stderr,
    )
    return name


def extract_date(path: Path) -> tuple[datetime, str]:
    name = path.name

    patterns = [
        r"(20\d{2})-(\d{2})-(\d{2})",
        r"(20\d{2})(\d{2})(\d{2})",
    ]

    for pattern in patterns:
        match = re.search(pattern, name)

        if not match:
            continue

        try:
            year, month, day = map(int, match.groups())
            return datetime(year, month, day), "name"
        except ValueError:
            continue

    return datetime.fromtimestamp(path.stat().st_mtime), "mtime"


def is_protected_by_prefix(name: str, prefixes: list[str]) -> bool:
    logical_name = extract_logical_name(name)
    normalized = logical_name.replace("_", " ")

    return any(normalized.startswith(prefix) for prefix in prefixes)


def is_critical_by_name(name: str, patterns: list[str]) -> bool:
    lowered = name.lower()

    return any(pattern.lower() in lowered for pattern in patterns)


def is_automatic_backup(name: str, prefixes: list[str]) -> bool:
    logical_name = extract_logical_name(name)

    return any(logical_name.startswith(prefix) for prefix in prefixes)


def scan_artifacts(root: Path) -> list[Path]:
    if not root.exists():
        return []

    return sorted(
        [p for p in root.iterdir() if p.is_file() or p.is_dir()],
        key=lambda p: p.name.lower(),
    )


def classify_artifacts(artifacts: list[Path], policy: dict) -> list[dict]:
    now = datetime.now()

    protected_prefixes = policy.get("protected_name_prefixes", [])
    critical_patterns = policy.get("critical_name_patterns", [])
    automatic_prefixes = policy.get("automatic_backup_prefixes", [])
    automatic_keep_count = policy.get("automatic_backup_keep_count", 10)

    keep_all_days = policy["retention"]["keep_all_days"]
    keep_daily_days = policy["retention"]["keep_daily_days"]
    keep_weekly_days = policy["retention"]["keep_weekly_days"]

    protected = []
    critical = []
    automatic = []
    temporal_candidates = []

    for artifact in artifacts:
        artifact_date, date_source = extract_date(artifact)
        name = artifact.name

        if is_protected_by_prefix(name, protected_prefixes):
            protected.append(
                {
                    "path": artifact,
                    "date": artifact_date,
                    "date_source": date_source,
                    "decision": DECISION_KEEP_MAJOR,
                    "reason": "protected_major_release",
                }
            )
            continue

        if is_critical_by_name(name, critical_patterns):
            critical.append(
                {
                    "path": artifact,
                    "date": artifact_date,
                    "date_source": date_source,
                    "decision": DECISION_KEEP_CRITICAL,
                    "reason": "critical_artifact_name",
                }
            )
            continue

        if is_automatic_backup(name, automatic_prefixes):
            automatic.append(
                {
                    "path": artifact,
                    "date": artifact_date,
                    "date_source": date_source,
                }
            )
            continue

        temporal_candidates.append(
            {
                "path": artifact,
                "date": artifact_date,
                "date_source": date_source,
            }
        )

    results = protected + critical

    automatic.sort(key=lambda x: x["date"], reverse=True)

    for index, item in enumerate(automatic):
        if index < automatic_keep_count:
            decision = DECISION_KEEP_AUTOMATIC_RECENT
            reason = f"top_{automatic_keep_count}_recent"
        else:
            decision = DECISION_QUARANTINE_AUTOMATIC_OLD
            reason = f"outside_top_{automatic_keep_count}_quarantine"

        results.append(
            {
                "path": item["path"],
                "date": item["date"],
                "date_source": item["date_source"],
                "decision": decision,
                "reason": reason,
            }
        )

    daily_kept = set()
    weekly_kept = set()

    temporal_candidates.sort(key=lambda x: x["date"], reverse=True)

    for item in temporal_candidates:
        age = now - item["date"]
        day_key = item["date"].date().isoformat()
        iso_year, iso_week, _ = item["date"].isocalendar()
        week_key = f"{iso_year}-W{iso_week:02d}"

        if age <= timedelta(days=keep_all_days):
            decision = DECISION_KEEP_RECENT
            reason = "recent_keep_all_period"

        elif age <= timedelta(days=keep_daily_days) and day_key not in daily_kept:
            decision = DECISION_KEEP_DAILY
            reason = "daily_retention"

            daily_kept.add(day_key)

        elif age <= timedelta(days=keep_weekly_days) and week_key not in weekly_kept:
            decision = DECISION_KEEP_WEEKLY
            reason = "weekly_retention"

            weekly_kept.add(week_key)

        else:
            decision = DECISION_CANDIDATE_DELETE
            reason = "outside_retention_policy"

        results.append(
            {
                "path": item["path"],
                "date": item["date"],
                "date_source": item["date_source"],
                "decision": decision,
                "reason": reason,
            }
        )

    return sorted(results, key=lambda x: x["date"], reverse=True)


def quarantine_artifacts(
    results: list[dict],
    quarantine_dir: Path,
    quarantine_only_automatic: bool,
    quarantine_candidate_delete: bool,
    apply_mode: bool,
) -> list[dict]:
    today_dir = datetime.now().strftime("%Y-%m-%d")

    eligible_decisions = {DECISION_QUARANTINE_AUTOMATIC_OLD}

    if quarantine_candidate_delete is True:
        eligible_decisions.add(DECISION_CANDIDATE_DELETE)

    for item in results:
        item["move_planned"] = False
        item["move_target"] = None
        item["move_done"] = False
        item["move_error"] = None

        decision = item["decision"]

        if decision not in eligible_decisions:
            continue

        if decision == DECISION_QUARANTINE_AUTOMATIC_OLD and quarantine_only_automatic is not True:
            item["move_error"] = "quarantine_only_automatic_backups_must_be_true"
            continue

        if decision == DECISION_CANDIDATE_DELETE and quarantine_candidate_delete is not True:
            item["move_error"] = "quarantine_candidate_delete_must_be_true"
            continue

        target_dir = quarantine_dir / today_dir
        target_path = target_dir / item["path"].name

        item["move_planned"] = True
        item["move_target"] = str(target_path)

        if not apply_mode:
            continue

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item["path"]), str(target_path))
            item["move_done"] = True
        except Exception as exc:
            item["move_error"] = str(exc)

    return results


def write_report(
    results: list[dict],
    report_path: Path,
    apply_mode: bool,
    quarantine_dir: Path,
    quarantine_only_automatic: bool,
    quarantine_candidate_delete: bool,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mode_label = "apply" if apply_mode else "dry-run"

    lines = [
        "# Retention report",
        "",
        f"- Generated at: `{now}`",
        "- Script version: `0.1.0`",
        f"- Mode: `{mode_label}`",
        f"- Quarantine: `{quarantine_dir}`",
        f"- Quarantine only automatic backups: `{quarantine_only_automatic}`",
        f"- Quarantine candidate delete: `{quarantine_candidate_delete}`",
        "- Scan mode: `flat`",
        "",
        "## Summary",
        "",
    ]

    counts = {}

    for item in results:
        counts[item["decision"]] = counts.get(item["decision"], 0) + 1

    for decision, count in sorted(counts.items()):
        lines.append(f"- `{decision}`: {count}")

    moves_planned = sum(1 for r in results if r.get("move_planned"))
    moves_done = sum(1 for r in results if r.get("move_done"))
    moves_error = sum(1 for r in results if r.get("move_error"))

    lines.extend(
        [
            "",
            "## Quarantine",
            "",
            f"- Planned moves: {moves_planned}",
            f"- Completed moves: {moves_done}",
            f"- Move errors: {moves_error}",
            "",
            "## Details",
            "",
            "| Decision | Date | Date source | Name | Reason | Move |",
            "|---|---:|---|---|---|---|",
        ]
    )

    for item in results:
        if item.get("move_done"):
            move_label = f"→ `{item['move_target']}`"
        elif item.get("move_error"):
            move_label = f"error: `{item['move_error']}`"
        elif item.get("move_planned"):
            move_label = f"planned: `{item['move_target']}`"
        else:
            move_label = "—"

        lines.append(
            f"| `{item['decision']}` | "
            f"{item['date'].strftime('%Y-%m-%d')} | "
            f"`{item['date_source']}` | "
            f"`{item['path'].name}` | "
            f"`{item['reason']}` | "
            f"{move_label} |"
        )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Home Assistant state archive retention manager."
    )

    parser.add_argument(
        "--root",
        required=True,
        help="Directory to analyze.",
    )

    parser.add_argument(
        "--policy",
        required=True,
        help="Retention policy YAML file.",
    )

    parser.add_argument(
        "--report",
        required=True,
        help="Markdown report to produce.",
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply quarantine moves. Without this flag, strict dry-run mode is used.",
    )

    args = parser.parse_args()

    root = Path(args.root)
    policy_path = Path(args.policy)
    report_path = Path(args.report)

    policy = load_policy(policy_path)

    quarantine_dir_raw = policy.get("quarantine_dir", "_quarantine")
    quarantine_dir = Path(quarantine_dir_raw)

    if not quarantine_dir.is_absolute():
        quarantine_dir = root / quarantine_dir

    quarantine_only_automatic = policy.get(
        "quarantine_only_automatic_backups",
        True,
    )

    quarantine_candidate_delete = policy.get(
        "quarantine_candidate_delete",
        False,
    )

    artifacts = scan_artifacts(root)

    artifacts = [
        a for a in artifacts
        if a.resolve() != quarantine_dir.resolve()
    ]

    results = classify_artifacts(artifacts, policy)

    results = quarantine_artifacts(
        results,
        quarantine_dir=quarantine_dir,
        quarantine_only_automatic=quarantine_only_automatic,
        quarantine_candidate_delete=quarantine_candidate_delete,
        apply_mode=args.apply,
    )

    write_report(
        results,
        report_path,
        apply_mode=args.apply,
        quarantine_dir=quarantine_dir,
        quarantine_only_automatic=quarantine_only_automatic,
        quarantine_candidate_delete=quarantine_candidate_delete,
    )


if __name__ == "__main__":
    main()