# Architectural invariants

## Purpose

This document defines the architectural invariants enforced by `ha-state-archive`.

These invariants guarantee:

- deterministic behavior;
- archival integrity;
- operational traceability;
- controlled retention;
- audit reproducibility.

The invariants are considered normative for the project architecture.

---

## Core data invariants

### I-1 — Immutable extracted versions

Once extracted and stabilized, a version must never be modified in-place.

Any transformation, audit or report generation must operate without altering the archived version.

---

### I-2 — Zero-knowledge watcher

The watcher layer must never require access to backup decryption secrets.

Observation and stabilization responsibilities are intentionally separated from ingestion responsibilities.

---

### I-3 — Stabilized version detection

A version is only processable after its size and structure remain unchanged for a configurable stabilization delay.

This prevents processing partial or corrupted transfers.

---

## Audit and logic invariants

### I-4 — Audit non-interference

The audit engine must never modify the audited version.

Its role is strictly observational.

---

### I-7 — Machine-readable supervision

Audit verdicts must be exportable through stable machine-readable formats.

Examples include:

- JSON verdicts;
- MQTT payloads;
- structured digests.

---

### I-9 — Explicit failure visibility

Silent failure patterns are forbidden.

Errors and anomalies must remain observable and traceable.

---

### I-11 — Audit reproducibility

The audit logic must rely solely on the files present within the extracted version and the defined schemas.

It must not depend on external API calls or a running Home Assistant instance.

---

## Retention and safety invariants

### I-5 — Quarantine before purge

No archived version may be deleted directly from the archive root.

All deletions must pass through a traceable quarantine phase.

---

### I-14 — Asymmetric retention priority

Retention policies must prioritize protected and critical artifacts over routine runtime backups.

---

### I-15 — Mandatory isolation

The retention manager is intentionally limited to quarantine operations and must not perform permanent deletion.

---

### I-16 — Delayed irreversible purge

The purge engine is a separate administrative component.

It only operates on the quarantine zone and requires a double confirmation mechanism:

- policy-level authorization;
- CLI-level `--apply` confirmation.

---

### I-17 — Execution boundary

The purge engine is strictly forbidden from scanning or modifying the archive root directory.

Its scope is restricted to the quarantine hierarchy.

---

## Infrastructure and noise control

### I-6 — Runtime/data separation

Generated runtime data must remain outside version-controlled source directories.

This includes:

- extracted versions;
- generated reports;
- caches;
- logs;
- temporary files.

---

### I-8 — Deterministic retention

Retention policies must produce deterministic outcomes for identical inputs and policy states.

---

### I-10 — Infrastructure-side processing

Archival, audit and retention responsibilities are designed to execute outside Home Assistant runtime whenever possible.

---

### I-12 — Bounded outputs

Report generation must enforce strict size limits to remain readable and safe to open on constrained infrastructure environments.

Large or noisy changes must be summarized or excluded from detailed outputs.

---

### I-13 — Noise reduction

Differential analysis must exclude volatile runtime files to focus on configuration and logic changes.

Examples include:

- databases;
- logs;
- caches;
- temporary runtime artifacts.