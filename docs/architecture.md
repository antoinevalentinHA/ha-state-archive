# Architecture

## Purpose

`ha-state-archive` is designed to archive, audit and supervise Home Assistant states and backups from an external infrastructure layer.

The system is intentionally NAS-oriented and treats Home Assistant instances as long-lived technical systems whose configurations and runtime states must remain observable, versioned and auditable over time.

---

## Architectural philosophy

The project follows five core principles:

1. Immutable extracted versions
2. Strict separation of responsibilities
3. NAS-side processing
4. Machine-readable observability
5. Quarantine-before-purge retention

The architecture is designed to minimize coupling between Home Assistant runtime operations and archival/audit responsibilities.

---

## High-level pipeline

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

## Main domains

| Domain | Responsibility |
|---|---|
| `ingestion` | Backup extraction and normalization |
| `watcher` | Stabilization and version detection |
| `audit` | Structural integrity verification |
| `diff` | Release and chronological diffs |
| `retention` | Quarantine and purge policies |
| `mqtt` | Home Assistant supervision projection |
| `reports` | Markdown and digest generation |

---

## Runtime boundaries

The repository only contains:

- source code;
- templates;
- schemas;
- examples;
- documentation.

The following elements are intentionally excluded from version control:

- extracted versions;
- quarantine data;
- generated reports;
- secrets;
- Home Assistant runtime artifacts;
- MQTT credentials;
- production exports.

---

## Safety model

The architecture intentionally separates:

- retention from purge;
- observation from destruction;
- immutable archives from generated reports;
- runtime systems from archival infrastructure.

Destructive operations always require explicit confirmation layers.

---

## Design assumptions

The current implementation assumes:

- a Linux NAS environment;
- scheduled execution through Synology DSM tasks or equivalent schedulers;
- Home Assistant backups generated externally;
- MQTT availability for optional supervision projection.

The project is intentionally infrastructure-centric rather than Home Assistant-addon-centric.