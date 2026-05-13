# Architectural invariants

## Purpose

This document defines the architectural invariants enforced by `ha-state-archive`.

These invariants are intended to guarantee:

- deterministic behavior;
- archival integrity;
- operational traceability;
- controlled retention;
- audit reproducibility.

The invariants are considered normative.

---

# I-1 — Immutable extracted versions

Once extracted and stabilized, a version must never be modified in-place.

Any transformation, audit or report generation must operate without altering the archived version.

---

# I-2 — Zero-knowledge watcher

The watcher layer must never require access to backup decryption secrets.

Observation and stabilization responsibilities are intentionally separated from ingestion responsibilities.

---

# I-3 — Stabilized version detection

A version may only be considered processable after its size and structure remain unchanged for a configurable stabilization delay.

---

# I-4 — Audit non-interference

The audit engine must never modify the audited version.

Its role is strictly observational.

---

# I-5 — Quarantine before purge

No archived version may be deleted directly.

All deletions must pass through a traceable quarantine phase.

---

# I-6 — Runtime/data separation

Generated runtime data must remain outside version-controlled source directories.

This includes:

- extracted versions;
- generated reports;
- caches;
- logs;
- temporary files.

---

# I-7 — Machine-readable supervision

Audit verdicts must be exportable through stable machine-readable formats.

Examples include:

- JSON verdicts;
- MQTT payloads;
- structured digests.

---

# I-8 — Deterministic retention

Retention policies must produce deterministic outcomes for identical inputs.

---

# I-9 — Explicit failure visibility

Errors and anomalies must remain observable and traceable.

Silent failure patterns are forbidden.

---

# I-10 — Infrastructure-side processing

Archival, audit and retention responsibilities must execute outside Home Assistant runtime whenever possible.