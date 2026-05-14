from __future__ import annotations

from pathlib import Path

from ha_state_archive.diff.release_diff import consecutive_couples, scan_anchors


def _dir(root: Path, name: str) -> Path:
    path = root / name
    path.mkdir()
    return path


def test_d1_folder_with_major_or_minor_release_tag_is_detected_as_anchor(tmp_path):
    _dir(tmp_path, "2026-05-01_10-00_Arsenal_v15_hash")
    _dir(tmp_path, "2026-05-02_10-00_Arsenal_v15.1_hash")

    anchors, duplicates = scan_anchors(tmp_path)

    assert [anchor.tag for anchor in anchors] == ["v15", "v15.1"]
    assert duplicates == {}


def test_d2_duplicate_tags_are_rejected_from_anchors(tmp_path):
    _dir(tmp_path, "2026-05-01_10-00_Arsenal_v15_hash1")
    _dir(tmp_path, "2026-05-02_10-00_Arsenal_v15_hash2")
    _dir(tmp_path, "2026-05-03_10-00_Arsenal_v15.1_hash3")

    anchors, duplicates = scan_anchors(tmp_path)

    assert [anchor.tag for anchor in anchors] == ["v15.1"]
    assert set(duplicates) == {"v15"}
    assert len(duplicates["v15"]) == 2


def test_d3_anchors_are_sorted_by_major_minor(tmp_path):
    _dir(tmp_path, "2026-05-03_10-00_Arsenal_v16_hash")
    _dir(tmp_path, "2026-05-02_10-00_Arsenal_v15.2_hash")
    _dir(tmp_path, "2026-05-01_10-00_Arsenal_v15_hash")
    _dir(tmp_path, "2026-05-04_10-00_Arsenal_v15.1_hash")

    anchors, _ = scan_anchors(tmp_path)

    assert [(anchor.major, anchor.minor) for anchor in anchors] == [(15, 0), (15, 1), (15, 2), (16, 0)]


def test_d4_consecutive_couples_returns_n_minus_one_pairs(tmp_path):
    for name in [
        "2026-05-01_10-00_Arsenal_v15_hash",
        "2026-05-02_10-00_Arsenal_v15.1_hash",
        "2026-05-03_10-00_Arsenal_v15.2_hash",
    ]:
        _dir(tmp_path, name)
    anchors, _ = scan_anchors(tmp_path)

    couples = consecutive_couples(anchors)

    assert len(couples) == len(anchors) - 1
    assert [(left.tag, right.tag) for left, right in couples] == [("v15", "v15.1"), ("v15.1", "v15.2")]
