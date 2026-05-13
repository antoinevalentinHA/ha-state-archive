# ha-state-archive

> Structured archival, audit and governance tooling for Home Assistant.

---

## Overview

`ha-state-archive` is a governance-oriented archival pipeline for Home Assistant environments.

The project treats Home Assistant configurations and runtime states as long-term technical assets requiring:

- immutable versioning;
- structural integrity auditing;
- release-oriented diffs;
- controlled retention workflows;
- machine-readable supervision outputs.

Unlike traditional backup systems, the project focuses on reproducibility, observability and infrastructure-side governance.

---

## Architecture

```text
Home Assistant Backup
        |
        v
 Ingestion Layer
        |
        v
Stabilization Watcher
        |
        v
 Immutable Versions
        |
        +-------> Audit Engine
        |              |
        |              +-------> Markdown reports
        |              +-------> MQTT verdicts
        |
        +-------> Diff Engine
        |
        +-------> Retention Engine
                       |
                       v
                 Quarantine
                       |
                       v
                     Purge
```

---

## Main capabilities

### Ingestion

Decrypts and extracts encrypted Home Assistant backups into immutable versioned directories.

Features include:

- `hassio-tar` decryption support;
- atomic extraction with staging directory;
- SHA256-based state tracking;
- partial extraction support for older backup structures;
- dry-run mode.

Documentation:

- `docs/ingestion.md`

---

### Audit engine

Analyzes extracted Home Assistant versions and detects structural inconsistencies without modifying archived data.

Features include:

- declaration extraction;
- include graph resolution;
- registry authority analysis;
- static and dynamic reference extraction;
- actionable anomaly classification;
- architectural observations;
- severity-based reporting;
- machine-readable verdict JSON for MQTT publication.

Documentation:

- `docs/audit.md`

---

### Release diff engine

Generates bounded Markdown diffs and statistical digests between immutable release anchors.

Features include:

- SHA256 snapshot integrity;
- exclusion-aware diffs;
- bounded outputs;
- idempotent generation;
- release indexing.

Documentation:

- `docs/diff.md`

---

### Retention engine

Classifies archived artifacts according to deterministic retention policies.

Features include:

- dry-run by default;
- quarantine-first workflow;
- protected release preservation;
- traceable retention decisions;
- asymmetric retention priority.

Documentation:

- `docs/retention.md`

---

### Quarantine purge engine

Safely destroys expired quarantine artifacts after a configurable grace period.

Features include:

- strict path validation;
- quarantine-only scope;
- delayed irreversible purge;
- mandatory double confirmation;
- full deletion traceability.

Documentation:

- `docs/purge.md`

---

### MQTT supervision

Publishes compact audit verdicts to MQTT for external supervision.

Features include:

- stable payload contract;
- strict freshness validation;
- error payload on any failure;
- credentials via environment variables or env file.

Documentation:

- `docs/mqtt.md`

---

## Core principles

- Immutable extracted versions
- Observational-only auditing
- Quarantine-before-purge retention
- Runtime/governance separation
- Machine-readable supervision
- Infrastructure-side processing
- Deterministic retention logic
- Bounded human-readable outputs

---

## Available modules

| Module | Status | Purpose |
|---|---|---|
| Ingestion | Available | Decrypt and extract Home Assistant backups into versioned directories |
| Audit engine | Available | Detect structural inconsistencies in extracted Home Assistant versions |
| Diff engine | Available | Generate bounded Markdown diffs and digests |
| Retention manager | Available | Classify archived artifacts and isolate eligible versions |
| Quarantine purger | Available | Permanently delete expired quarantine folders safely |
| MQTT supervision | Available | Publish audit verdicts to MQTT |

---

## Pipeline orchestration

The full pipeline is orchestrated by `scripts/run_pipeline.sh`.

Configuration is passed entirely via `HSA_*` environment variables.

Required variables:

| Variable | Description |
|---|---|
| `HSA_BACKUP_DIR` | Directory containing Home Assistant `.tar` backup files |
| `HSA_AUDIT_CONFIG` | Path to the audit configuration YAML file |
| `HSA_HASSIO_TAR` | Path to the `hassio-tar` binary |
| `HASSIO_PASSWORD` | Backup decryption password |

See `docs/synology_dsm.md` for the full variable reference and deployment guide.

---

## Documentation

- [Ingestion](docs/ingestion.md)
- [Architecture](docs/architecture.md)
- [Architectural invariants](docs/invariants.md)
- [Audit engine](docs/audit.md)
- [Diff engine](docs/diff.md)
- [Retention engine](docs/retention.md)
- [Quarantine purge engine](docs/purge.md)
- [MQTT supervision](docs/mqtt.md)
- [Synology DSM integration](docs/synology_dsm.md)

---

## Project status

The repository is an ongoing public extraction of a production-grade Home Assistant governance infrastructure.

The codebase is progressively being generalized and documented for broader public use while preserving deterministic infrastructure-side behavior.

---

## License

GPL-3.0
