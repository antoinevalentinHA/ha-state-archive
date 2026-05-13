# Synology DSM integration

## Purpose

`ha-state-archive` is primarily designed to run on external infrastructure such as Synology NAS systems.

The NAS acts as:

- archival infrastructure;
- audit execution environment;
- retention authority;
- supervision relay.

Home Assistant itself is intentionally kept outside archival responsibilities whenever possible.

---

## Execution model

The system is designed around scheduled DSM tasks.

Typical execution flow:

```text
Home Assistant backup
        |
        v
Extraction (extract.py)
        |
        v
Watcher stabilization (watch_new_backup.sh)
        |
        v
Audit (audit_engine.py)
        |
        v
MQTT publication (publish_audit_mqtt.py)
        |
        v
Retention management (retention_manager.py)
        |
        v
Quarantine purge (quarantine_purger.py)
```

---

## Recommended DSM tasks

| Task | Script | Purpose | Frequency |
|---|---|---|---|
| Extraction | `scripts/run_pipeline.sh` | Extract, audit and publish in sequence | Periodic |
| Watcher | `scripts/watch_new_backup.sh` | Detect and stabilize new versions | Every few minutes |
| Retention | `retention_manager.py` | Classify and quarantine artifacts | Daily |
| Purge | `quarantine_purger.py` | Permanently delete expired quarantine folders | Weekly |

---

## Environment variables

All pipeline configuration is passed via `HSA_*` environment variables.

Set them in the DSM task environment or in a sourced shell file before execution.

| Variable | Required | Description |
|---|---|---|
| `HSA_BASE_DIR` | No | Base installation directory. Default: `/opt/ha-state-archive` |
| `HSA_BACKUP_DIR` | Yes | Directory containing Home Assistant `.tar` backup files |
| `HSA_VERSIONS_DIR` | No | Extracted version directory. Default: `$HSA_BASE_DIR/versions` |
| `HSA_TEMP_DIR` | No | Temporary staging directory. Default: `$HSA_BASE_DIR/temp` |
| `HSA_STATE_FILE` | No | Ingestion state JSON file. Default: `$HSA_BASE_DIR/state/processed_backups.json` |
| `HSA_AUDIT_CONFIG` | Yes | Path to the audit configuration YAML file |
| `HSA_REPORTS_DIR` | No | Audit Markdown report directory. Default: `$HSA_BASE_DIR/reports` |
| `HSA_VERDICT_DIR` | No | Audit verdict JSON directory. Default: `$HSA_BASE_DIR/verdicts` |
| `HSA_HASSIO_TAR` | Yes | Path to the `hassio-tar` binary |
| `HSA_MQTT_ENV` | No | Path to the MQTT credentials env file. Falls back to environment variables if not set |
| `HASSIO_PASSWORD` | Yes | Home Assistant backup decryption password. Never logged. |

---

## Installation layout

Recommended directory layout on the NAS:

```text
/opt/ha-state-archive/
├── src/                         # ha-state-archive source
├── scripts/
│   ├── run_pipeline.sh
│   └── watch_new_backup.sh
├── config/
│   └── retention_policy.yaml
├── versions/                    # extracted immutable versions
├── temp/                        # temporary extraction staging
├── state/
│   └── processed_backups.json
├── reports/                     # audit Markdown reports
├── verdicts/                    # audit verdict JSON files
├── releases/                    # diff engine output
└── logs/
    └── pipeline/
```

---

## Design assumptions

The implementation assumes:

- POSIX-compatible shell support;
- scheduled task execution via DSM Task Scheduler;
- persistent storage availability;
- local filesystem access;
- Python 3.11 or newer;
- `hassio-tar` available and executable.

---

## Security model

The architecture intentionally separates:

- backup decryption (`extract.py` + `hassio-tar`);
- version observation and audit (`audit_engine.py`);
- retention decisions (`retention_manager.py`);
- supervision publication (`publish_audit_mqtt.py`).

`HASSIO_PASSWORD` is only required during the extraction step.
It is never written to disk, never included in reports or logs,
and never passed to any component other than `hassio-tar`.

Only `core.entity_registry` is extracted from `.storage/`.
All other `.storage/` files remain in the encrypted backup and are never extracted.

---

## Operational philosophy

The NAS is considered the long-term memory layer of the Home Assistant system.

Home Assistant produces states and backups.

`ha-state-archive` preserves, validates and supervises them externally.
