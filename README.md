# ha-state-archive

> A structured archival system for Home Assistant focused on automated auditing, state versioning and configuration integrity.

---

## Overview

`ha-state-archive` is a NAS-oriented archival and audit pipeline for Home Assistant.

Unlike traditional backup approaches, the project treats Home Assistant configurations and runtime states as long-term technical assets requiring:

- immutable versioning;
- structural integrity checks;
- release-oriented diffs;
- controlled retention policies;
- machine-readable audit verdicts.

The project is designed for advanced Home Assistant environments where backups, auditing and retention are handled outside Home Assistant itself.

---

## Core principles

- Immutable extracted versions
- Automated structural auditing
- Quarantine-before-purge retention
- Separation between runtime and governance
- Machine-readable supervision outputs
- NAS-side processing and archival

---

## Project status

Early public extraction from a production-grade private infrastructure.

The repository is currently being cleaned, generalized and documented before broader public release.

---

## License

GPL-3.0