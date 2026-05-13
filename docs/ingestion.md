# Ingestion

## Purpose

The ingestion module decrypts and extracts Home Assistant encrypted backups into
immutable versioned directories ready for audit and diff processing.

It is the entry point of the `ha-state-archive` pipeline.

---

## Core principles

### Source directory is never modified

The backup source directory is treated as read-only.
No file is created, renamed or deleted within it.

### Atomic extraction

Each version is extracted into a temporary staging directory first.
The target directory is only committed via atomic rename on success.
A failed extraction leaves no partial version on disk.

### Idempotent processing

Each backup is identified by its SHA256 hash.
A state file tracks processed backups.
A backup is skipped if it has already been processed successfully
and its hash has not changed, unless `--force` is provided.

### Decryption key never logged

`HASSIO_PASSWORD` is read from the environment and passed directly
to `hassio-tar`. It is never printed, stored or included in any report.

### Partial extraction support

Older backup structures may not include all expected paths.
Missing paths are tolerated and logged.
An extraction is only rejected if `configuration.yaml` is absent.

---

## Prerequisites

- `HASSIO_PASSWORD` must be set in the environment before running.
- `hassio-tar` must be present and executable at the path provided
  via `--hassio-tar` or `HSA_HASSIO_TAR`.

```sh
read -ersp 'Backup password: ' HASSIO_PASSWORD && export HASSIO_PASSWORD
```

---

## Extracted paths

The following paths are extracted from each backup when present:

```text
configuration.yaml
recorder.yaml
utility_meter.yaml
.storage/core.entity_registry
00_documentation/
01_customize/
02_groups/
03_input_numbers/
04_input_texts/
05_input_booleans/
06_input_selects/
07_input_datetimes/
08_timers/
09_counters/
10_scripts/
11_automations/
12_template_sensors/
13_sensor_platforms/
14_mqtt_sensors/
15_mqtt_binary_sensors/
16_template_alarm_panels/
17_zones/
18_lovelace/
19_button_card_templates/
```

Only `core.entity_registry` is extracted from `.storage/`.
Other `.storage/` files are excluded as they may contain credentials,
tokens or authentication data.

---

## Version directory naming

Each extracted version is stored as a directory named:

```text
YYYY-MM-DD_HH-MM_<label>_<id>
```

Where:

- `YYYY-MM-DD_HH-MM` is the backup timestamp, derived from the backup
  metadata, filename pattern, or file modification time (in that order);
- `<label>` is derived from the backup display name;
- `<id>` is the backup identifier or a short hash from the filename.

This naming convention is shared with the retention engine.

---

## State file

The state file is a JSON document tracking all processed backups:

```json
{
  "2026-01-15_HomeAssistant.tar": {
    "sha256": "abc123...",
    "version_dir": "2026-01-15_09-00_Home_Assistant_abc123",
    "processed_at": "2026-01-15T09:05:00",
    "status": "ok",
    "extracted_paths": ["..."],
    "missing_paths": [],
    "error": ""
  }
}
```

Status values:

| Status | Meaning |
|---|---|
| `ok` | All expected paths were extracted |
| `partial` | Some paths were absent but extraction succeeded |
| `failed` | Extraction failed; error is recorded |

---

## CLI usage

```sh
python3 src/ha_state_archive/ingestion/extract.py \
  --backup-dir   /path/to/backups   \
  --versions-dir /path/to/versions  \
  --temp-dir     /path/to/temp      \
  --state        /path/to/state/processed_backups.json \
  --hassio-tar   /path/to/hassio-tar \
  --latest-only
```

---

## CLI arguments

| Argument | Required | Description |
|---|---|---|
| `--backup-dir` | Yes | Directory containing Home Assistant `.tar` backup files |
| `--versions-dir` | Yes | Output directory for extracted version directories |
| `--temp-dir` | Yes | Temporary directory for atomic extraction staging |
| `--state` | Yes | Path to the JSON state file |
| `--hassio-tar` | Yes | Path to the `hassio-tar` binary |
| `--latest-only` | No | Process only the most recent backup |
| `--limit N` | No | Process at most N most recent backups |
| `--since-date DATE` | No | Skip backups older than DATE (`YYYY-MM-DD` or `YYYY-MM-DD_HH-MM`) |
| `--force` | No | Re-extract even if already processed |
| `--dry-run` | No | List candidates without extracting |
| `--stop-on-error` | No | Stop on first failure instead of logging and continuing |

`--hassio-tar` can also be set via the `HSA_HASSIO_TAR` environment variable.

---

## Environment variables

| Variable | Description |
|---|---|
| `HASSIO_PASSWORD` | Backup decryption password. Required. Never logged. |
| `HSA_HASSIO_TAR` | Path to the `hassio-tar` binary. Used when `--hassio-tar` is not provided. |

---

## Exit codes

| Exit code | Meaning |
|---:|---|
| `0` | Completed successfully |
| `1` | Fatal error (missing prerequisite, extraction failure with `--stop-on-error`) |
