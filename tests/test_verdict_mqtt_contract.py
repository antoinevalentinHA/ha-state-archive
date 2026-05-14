from __future__ import annotations

import json
from pathlib import Path

from ha_state_archive.audit.audit_engine import AuditAnomaly, AuditResult, _write_verdict_json
from ha_state_archive.mqtt.publish_audit_mqtt import read_verdict_json

REQUIRED_VERDICT_KEYS = {
    "contract_version",
    "engine_version",
    "published_at",
    "audited_version",
    "verdict",
    "total_anomalies",
    "anomaly_categories",
    "report_path",
}


def _valid_payload(**overrides):
    payload = {
        "contract_version": "1.0.0",
        "engine_version": "1.1.1",
        "published_at": "2026-05-14T13:51:14Z",
        "audited_version": "2026-05-14_02-30_Automatic_backup_2026.5.1_7475de67",
        "verdict": "ok",
        "total_anomalies": 0,
        "anomaly_categories": [],
        "report_path": "/tmp/ha-test/reports/audit.md",
    }
    payload.update(overrides)
    return payload


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _read(path: Path):
    data, mtime, present, valid = read_verdict_json(str(path))
    return data, mtime, present, valid


def test_v1_valid_verdict_contains_the_eight_contract_keys(tmp_path):
    path = _write_json(tmp_path / "verdict.json", _valid_payload())

    data, _, present, valid = _read(path)

    assert present is True
    assert valid is True
    assert REQUIRED_VERDICT_KEYS.issubset(data.keys())


def test_v2_verdict_vocabulary_is_accepted(tmp_path):
    for verdict in ("ok", "degraded", "critical", "error", "unknown"):
        path = _write_json(tmp_path / f"{verdict}.json", _valid_payload(verdict=verdict))
        _, _, present, valid = _read(path)
        assert present is True
        assert valid is True


def test_v3_zero_anomaly_audit_writes_ok_verdict(tmp_path):
    path = tmp_path / "verdict.json"

    _write_verdict_json(path, AuditResult(anomalies=[]), tmp_path / "snapshot", "2026-05-14T13:51:14Z")

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["verdict"] == "ok"
    assert payload["total_anomalies"] == 0


def test_v4_any_p0_anomaly_writes_critical_verdict(tmp_path):
    path = tmp_path / "verdict.json"
    anomaly = AuditAnomaly(
        entity_id="sensor.test",
        anomaly_type="broken_reference",
        severity="P0",
        confidence="high",
        evidence=["test"],
        notes="test",
    )

    _write_verdict_json(path, AuditResult(anomalies=[anomaly]), tmp_path / "snapshot", "2026-05-14T13:51:14Z")

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["verdict"] == "critical"
    assert payload["total_anomalies"] == 1


def test_v5_read_verdict_json_rejects_missing_contract_key(tmp_path):
    payload = _valid_payload()
    payload.pop("report_path")
    path = _write_json(tmp_path / "missing_key.json", payload)

    data, _, present, valid = _read(path)

    assert data is None
    assert present is True
    assert valid is False


def test_v6_read_verdict_json_rejects_unknown_verdict_value(tmp_path):
    path = _write_json(tmp_path / "bad_verdict.json", _valid_payload(verdict="greenish"))

    data, _, present, valid = _read(path)

    assert data is None
    assert present is True
    assert valid is False
