from __future__ import annotations

from datetime import date
from pathlib import Path

import ha_state_archive.retention.quarantine_purger as qp


class FrozenDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 5, 14)


def _folder(root: Path, name: str) -> Path:
    path = root / name
    path.mkdir()
    return path


def _row_by_folder(rows):
    return {row["folder"]: row for row in rows}


def test_q1_allow_purge_missing_or_false_is_policy_error():
    assert qp.ERROR_ALLOW_PURGE in qp.validate_policy({"quarantine_min_age_days": 7})
    assert qp.ERROR_ALLOW_PURGE in qp.validate_policy({"quarantine_min_age_days": 7, "allow_purge": False})


def test_q2_min_age_negative_or_non_integer_is_policy_error():
    assert "quarantine_min_age_days_must_be_positive_integer" in qp.validate_policy({"quarantine_min_age_days": -1, "allow_purge": True})
    assert "quarantine_min_age_days_must_be_positive_integer" in qp.validate_policy({"quarantine_min_age_days": "7", "allow_purge": True})


def test_q3_undated_folder_is_kept_and_not_planned_for_purge(tmp_path, monkeypatch):
    monkeypatch.setattr(qp, "date", FrozenDate)
    _folder(tmp_path, "manual_folder")

    row = _row_by_folder(qp.scan_quarantine(tmp_path, min_age_days=7))["manual_folder"]

    assert row["decision"] == "KEEP_QUARANTINE_UNDATED"
    assert row["purge_planned"] is False


def test_q4_dated_folder_younger_than_min_age_is_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(qp, "date", FrozenDate)
    _folder(tmp_path, "2026-05-10")

    row = _row_by_folder(qp.scan_quarantine(tmp_path, min_age_days=7))["2026-05-10"]

    assert row["decision"] == "KEEP_QUARANTINE_RECENT"
    assert row["purge_planned"] is False


def test_q5_dated_folder_older_or_equal_to_min_age_is_planned_for_purge(tmp_path, monkeypatch):
    monkeypatch.setattr(qp, "date", FrozenDate)
    _folder(tmp_path, "2026-05-07")

    row = _row_by_folder(qp.scan_quarantine(tmp_path, min_age_days=7))["2026-05-07"]

    assert row["decision"] == "PURGE_QUARANTINE_EXPIRED"
    assert row["purge_planned"] is True


def test_q6_path_outside_quarantine_root_is_rejected_without_rmtree(tmp_path, monkeypatch):
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    called = False

    def fake_rmtree(path):
        nonlocal called
        called = True

    monkeypatch.setattr(qp.shutil, "rmtree", fake_rmtree)
    rows = [{
        "folder": "outside",
        "path": outside,
        "age_days": 30,
        "decision": "PURGE_QUARANTINE_EXPIRED",
        "reason": "quarantine_age_expired",
        "purge_planned": True,
        "purge_done": False,
        "purge_error": "",
    }]

    result = qp.apply_purge(rows, quarantine.resolve(), apply=True)

    assert result[0]["decision"] == "PURGE_ERROR"
    assert result[0]["purge_error"] == "target_not_strictly_under_quarantine"
    assert called is False
