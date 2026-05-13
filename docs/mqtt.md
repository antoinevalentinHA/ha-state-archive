# MQTT supervision

## Purpose

`ha-state-archive` can publish audit and pipeline state to MQTT for external supervision.

This allows Home Assistant, or any other monitoring system, to observe archive integrity without owning the archival process.

---

## Default topic

```text
ha_state_archive/audit/state
```

---

## Payload contract

Example payload:

```json
{
  "contract_version": "1.0.0",
  "engine_version": "0.1.0",
  "published_at": "2026-01-01T00:00:00Z",
  "audited_version": "2026-01-01_00-00_HomeAssistant",
  "verdict": "ok",
  "total_anomalies": 0
}
```

---

## Verdict values

| Verdict | Meaning |
|---|---|
| `ok` | Audit completed successfully with no blocking anomaly |
| `degraded` | Audit completed with non-critical anomalies |
| `critical` | Audit completed with critical anomalies |
| `error` | Audit execution failed |
| `unknown` | No reliable verdict is available |

---

## Design rule

MQTT is a projection layer only.

It must not contain:
- audit logic;
- retention logic;
- archival decisions.