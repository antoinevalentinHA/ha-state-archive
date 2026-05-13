# ha-state-archive

> A structured archival system for Home Assistant focused on automated auditing, state versioning and configuration integrity.

---

## Overview

`ha-state-archive` is an archival and audit pipeline for Home Assistant environments.

Unlike traditional backup approaches, the project treats Home Assistant configurations and runtime states as long-term technical assets requiring:

- immutable versioning;
- structural integrity checks;
- release-oriented diffs;
- controlled retention policies;
- machine-readable audit verdicts.

The project is designed for advanced Home Assistant environments where backups, auditing and retention are handled outside Home Assistant itself.

---

## Current modules

### Release diff engine

Generates:

- detailed Markdown diffs;
- statistical digests;
- release indexes;
- bounded and exclusion-aware reports.

Features:

- immutable release anchors;
- idempotent processing;
- SHA256 snapshot integrity;
- exclusion filters for volatile runtime data;
- bounded output safeguards.

Documentation:

- `docs/diff.md`

---

### Retention engine

Classifies archived artifacts according to asymmetric retention policies.

Features:

- dry-run by default;
- protected major releases;
- critical artifact preservation;
- quarantine-first workflow;
- traceable Markdown reports.

Documentation:

- `docs/retention.md`

---

### Quarantine purge engine

Safely deletes quarantined artifacts after a configurable grace period.

Features:

- strict quarantine root validation;
- mandatory double-confirmation;
- delayed destruction model;
- dated quarantine targeting;
- full purge traceability.

Documentation:

- `docs/purge.md`

---

## Core principles

- Immutable extracted versions
- Automated structural auditing
- Quarantine-before-purge retention
- Separation between runtime and governance
- Machine-readable supervision outputs
- Externalized archival workflows

---

## Project status

Early public extraction from a production-grade private infrastructure.

The repository is currently being generalized, cleaned and documented before broader public release.

---

## License

GPL-3.0