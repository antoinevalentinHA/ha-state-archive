# MQTT supervision

## Purpose

`ha-state-archive` can publish audit and pipeline state to MQTT for external supervision.

This allows Home Assistant, or any other monitoring system, to observe archive integrity without owning the archival process.

MQTT is a projection layer only.

It does not:
- run the audit;
- decide the audit verdict;
- publish detailed anomalies;
- publish Markdown reports;
- modify archived versions.

---

## Default topic

```text
ha_state_archive/audit/state
```

---

## Publisher module

```text
src/ha_state_archive/mqtt/publish_audit_mqtt.py
```

---

## Payload contract

Example payload:

```json
{
  "contract_version": "1.0.0",
  "engine_version": "1.1.1",
  "published_at": "2026-01-01T00:00:00Z",
  "audited_version": "2026-01-01_00-00_HomeAssistant",
  "verdict": "ok",
  "total_anomalies": 0,
  "anomaly_categories": [],
  "report_path": "/path/to/reports/audit_2026-01-01_00-00-00.md"
}
```

---

## Required fields

| Field | Type | Meaning |
|---|---|---|
| `contract_version` | string | Payload contract version |
| `engine_version` | string or null | Audit engine version |
| `published_at` | string | UTC ISO 8601 timestamp |
| `audited_version` | string or null | Archived version audited |
| `verdict` | string | Compact audit verdict |
| `total_anomalies` | integer or null | Number of detected anomalies |
| `anomaly_categories` | array or null | Anomaly types detected (empty array when verdict is `ok`) |
| `report_path` | string or null | Absolute path to the generated Markdown report |

---

## Verdict values

| Verdict | Meaning |
|---|---|
| `ok` | Audit completed successfully with no anomaly |
| `degraded` | Audit completed with non-critical anomalies |
| `critical` | Audit completed with critical anomalies |
| `error` | Audit execution or verdict publication failed |
| `unknown` | No reliable verdict is available |

---

## MQTT configuration

Credentials must not be stored in the repository.

The publisher can read MQTT configuration from environment variables:

```text
MQTT_HOST
MQTT_PORT
MQTT_USERNAME
MQTT_PASSWORD
```

Or from an external env file:

```text
MQTT_HOST="127.0.0.1"
MQTT_PORT="1883"
MQTT_USERNAME="user"
MQTT_PASSWORD="password"
```

The env file parser is intentionally strict:
- uppercase keys only;
- quoted values only;
- unknown lines are ignored;
- missing required keys make the publisher fail with exit code `2`.

---

## CLI usage

Example using environment variables:

```sh
python -m ha_state_archive.mqtt.publish_audit_mqtt \
  --verdict-json /path/to/latest.verdict.json \
  --audit-rc 0
```

Example using an external MQTT env file:

```sh
python -m ha_state_archive.mqtt.publish_audit_mqtt \
  --verdict-json /path/to/latest.verdict.json \
  --audit-rc 0 \
  --mqtt-env /path/to/mqtt.env
```

Example with strict freshness:

```sh
python -m ha_state_archive.mqtt.publish_audit_mqtt \
  --verdict-json /path/to/latest.verdict.json \
  --audit-rc 0 \
  --mqtt-env /path/to/mqtt.env \
  --strict-freshness
```

Example with a custom topic:

```sh
python -m ha_state_archive.mqtt.publish_audit_mqtt \
  --verdict-json /path/to/latest.verdict.json \
  --audit-rc 0 \
  --topic custom/archive/audit/state
```

---

## MQTT properties

| Property | Default |
|---|---|
| Topic | `ha_state_archive/audit/state` |
| Retain | `true` |
| QoS | `1` |

QoS can be changed with:

```sh
--qos 0
```

Accepted values are `0`, `1`, and `2`.

---

## Strict freshness

By default, the publisher accepts and republishes the latest available verdict JSON.

With:

```sh
--strict-freshness
```

the verdict JSON must be newer than 5 minutes.

This mode is intended for immediate pipeline execution, where the audit has just produced the verdict file.

---

## Error payload

If no usable verdict can be produced, the publisher emits an error payload.

Example:

```json
{
  "contract_version": "1.0.0",
  "engine_version": null,
  "published_at": "2026-01-01T00:00:00Z",
  "audited_version": null,
  "verdict": "error",
  "total_anomalies": null,
  "error_reason": "verdict_json_missing",
  "error_detail": ""
}
```

---

## Error reasons

| Reason | Meaning |
|---|---|
| `verdict_json_missing` | Verdict JSON file is missing |
| `verdict_json_malformed` | Verdict JSON is invalid or incomplete |
| `verdict_json_stale` | Verdict JSON is too old in strict freshness mode |
| `audit_engine_unexpected_exit_code` | Audit command returned an unexpected exit code |

---

## Exit codes

| Exit code | Meaning |
|---:|---|
| `0` | MQTT publication completed |
| `1` | MQTT connection or publication failed |
| `2` | MQTT configuration is invalid or missing |

---

## Design rule

MQTT is a projection layer only.

It must not contain:
- audit logic;
- retention logic;
- archival decisions;
- detailed anomaly lists;
- Markdown report content;
- notification logic;
- remediation logic.

Detailed audit reports remain local artifacts.
