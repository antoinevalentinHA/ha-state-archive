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
        ¦
        ?
Extraction task
        ¦
        ?
Watcher stabilization
        ¦
        ?
Audit / Diff generation
        ¦
        ?
Retention management
        ¦
        ?
MQTT publication
```

---

## Recommended DSM tasks

| Task | Purpose | Frequency |
|---|---|---|
| Extraction | Extract Home Assistant backups | Periodic |
| Watcher | Detect stabilized versions | Every few minutes |
| Audit | Generate integrity verdicts | Periodic |
| Retention | Manage quarantine and purge | Daily |
| MQTT publication | Publish supervision state | After audit |

---

## Design assumptions

The implementation assumes:

- POSIX-compatible shell support;
- scheduled task execution;
- persistent storage availability;
- local filesystem access;
- Python 3.11 or newer.

---

## Security model

The architecture intentionally separates:

- backup decryption;
- version observation;
- retention;
- supervision publication.

This minimizes secret exposure across the pipeline.

---

## Operational philosophy

The NAS is considered the long-term memory layer of the Home Assistant system.

Home Assistant produces states and backups.

`ha-state-archive` preserves, validates and supervises them externally.