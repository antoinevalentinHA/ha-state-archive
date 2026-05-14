from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import ha_state_archive.retention.retention_manager as rm


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 5, 14, 12, 0, 0)
        if tz is not None:
            return value.replace(tzinfo=tz)
        return value


def _policy(**overrides):
    policy = {
        "protected_name_prefixes": ["Arsenal"],
        "critical_name_patterns": ["critical", "manual"],
        "automatic_backup_prefixes": ["Automatic_backup"],
        "automatic_backup_keep_count": 2,
        "retention": {
            "keep_all_days": 3,
            "keep_daily_days": 10,
            "keep_weekly_days": 30,
        },
    }
    for key, value in overrides.items():
        if key == "retention":
            policy["retention"].update(value)
        else:
            policy[key] = value
    return policy


def _artifact(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir()
    return path


def _decisions(results):
    return {row["path"].name: row["decision"] for row in results}


def test_r1_protected_prefix_has_highest_priority(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "datetime", FrozenDateTime)
    artifact = _artifact(
        tmp_path,
        "2026-05-01_10-00_Arsenal_critical_Automatic_backup_abcd",
    )

    results = rm.classify_artifacts([artifact], _policy())

    assert results[0]["decision"] == rm.DECISION_KEEP_MAJOR


def test_r2_critical_artifact_is_never_quarantined_as_old_automatic(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "datetime", FrozenDateTime)
    artifact = _artifact(tmp_path, "2026-01-01_10-00_manual_critical_backup_abcd")

    results = rm.classify_artifacts([artifact], _policy(automatic_backup_keep_count=0))

    assert results[0]["decision"] == rm.DECISION_KEEP_CRITICAL
    assert results[0]["decision"] != rm.DECISION_QUARANTINE_AUTOMATIC_OLD


def test_r3_automatic_backups_are_kept_by_descending_date_then_quarantined(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "datetime", FrozenDateTime)
    artifacts = [
        _artifact(tmp_path, "2026-05-14_02-30_Automatic_backup_2026.5.3_hash"),
        _artifact(tmp_path, "2026-05-13_02-30_Automatic_backup_2026.5.2_hash"),
        _artifact(tmp_path, "2026-05-12_02-30_Automatic_backup_2026.5.1_hash"),
    ]

    decisions = _decisions(rm.classify_artifacts(artifacts, _policy(automatic_backup_keep_count=2)))

    assert decisions["2026-05-14_02-30_Automatic_backup_2026.5.3_hash"] == rm.DECISION_KEEP_AUTOMATIC_RECENT
    assert decisions["2026-05-13_02-30_Automatic_backup_2026.5.2_hash"] == rm.DECISION_KEEP_AUTOMATIC_RECENT
    assert decisions["2026-05-12_02-30_Automatic_backup_2026.5.1_hash"] == rm.DECISION_QUARANTINE_AUTOMATIC_OLD


def test_r4_keep_recent_precedes_daily_and_weekly(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "datetime", FrozenDateTime)
    artifact = _artifact(tmp_path, "2026-05-12_10-00_regular_snapshot_hash")

    results = rm.classify_artifacts([artifact], _policy(retention={"keep_all_days": 3, "keep_daily_days": 10, "keep_weekly_days": 30}))

    assert results[0]["decision"] == rm.DECISION_KEEP_RECENT


def test_r5_keep_daily_keeps_only_one_artifact_per_day(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "datetime", FrozenDateTime)
    newer = _artifact(tmp_path, "snapshot_newer")
    older = _artifact(tmp_path, "snapshot_older")

    base = FrozenDateTime(2026, 5, 10, 12, 0, 0).timestamp()
    newer_mtime = base + 3600
    older_mtime = base
    newer.touch()
    older.touch()
    newer.chmod(0o755)
    older.chmod(0o755)
    import os
    os.utime(newer, (newer_mtime, newer_mtime))
    os.utime(older, (older_mtime, older_mtime))

    decisions = _decisions(
        rm.classify_artifacts(
            [older, newer],
            _policy(retention={"keep_all_days": 1, "keep_daily_days": 10, "keep_weekly_days": 0}),
        )
    )

    assert decisions["snapshot_newer"] == rm.DECISION_KEEP_DAILY
    assert decisions["snapshot_older"] == rm.DECISION_CANDIDATE_DELETE


def test_r6_artifact_outside_all_windows_is_candidate_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "datetime", FrozenDateTime)
    artifact = _artifact(tmp_path, "2026-01-01_10-00_regular_snapshot_hash")

    results = rm.classify_artifacts([artifact], _policy(retention={"keep_all_days": 1, "keep_daily_days": 2, "keep_weekly_days": 3}))

    assert results[0]["decision"] == rm.DECISION_CANDIDATE_DELETE
