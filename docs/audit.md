# Audit engine

## Purpose

The audit engine verifies the structural integrity of extracted Home Assistant versions.

It is designed to detect inconsistencies without modifying the archived version.

---

## Scope

The audit engine may check:

- missing entity references;
- unresolved YAML includes;
- missing files;
- broken dashboard references;
- invalid configuration fragments;
- stale or inconsistent runtime references.

---

## Non-goals

The audit engine does not:

- repair configurations automatically;
- modify archived versions;
- replace Home Assistant native validation;
- require Home Assistant to be running.

---

## Output contract

The audit engine produces machine-readable verdicts.

A typical verdict includes:

- audit status;
- audit timestamp;
- audited version;
- anomaly count;
- anomaly categories;
- optional human-readable report path.

---

## Design rule

Audit is observational.

Any corrective action must happen outside the audit engine.