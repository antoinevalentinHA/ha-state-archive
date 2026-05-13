# Retention engine

## Purpose

The retention engine classifies archived artifacts and applies a controlled quarantine policy.

It is designed to keep long-term technical assets while limiting uncontrolled growth of runtime backups.

---

## Core principles

### Dry-run by default

The retention manager never moves files unless `--apply` is explicitly provided.

Without `--apply`, it only produces a Markdown report.

### Quarantine before purge

The retention manager does not delete files.

Eligible artifacts are moved to a quarantine directory first.

Actual deletion is handled by a separate purge process.

### Asymmetric retention

Not all artifacts have the same value.

The engine distinguishes:

- protected major releases;
- critical documentation or contract artifacts;
- automatic runtime backups;
- generic temporal candidates.

Protected and critical artifacts are preserved by policy.

---

## Decisions

| Decision | Meaning |
|---|---|
| `KEEP_MAJOR` | Protected release or major artifact kept indefinitely |
| `KEEP_CRITICAL` | Critical artifact kept indefinitely |
| `KEEP_AUTOMATIC_RECENT` | Recent automatic backup kept by count policy |
| `QUARANTINE_AUTOMATIC_OLD` | Old automatic backup eligible for quarantine |
| `KEEP_RECENT` | Artifact kept during the full-retention window |
| `KEEP_DAILY` | Artifact kept as daily representative |
| `KEEP_WEEKLY` | Artifact kept as weekly representative |
| `CANDIDATE_DELETE` | Artifact outside retention policy |

---

## Quarantine controls

Two policy flags define the quarantine blast radius:

```yaml
quarantine_only_automatic_backups: true
quarantine_candidate_delete: false
```

By default:

- old automatic backups may be quarantined;
- generic `CANDIDATE_DELETE` artifacts are reported but not moved.

To allow quarantine of generic candidates, explicitly set:

```yaml
quarantine_candidate_delete: true
```

---

## Reports

Each run produces a Markdown report containing:

- execution mode;
- quarantine policy flags;
- decision counts;
- planned moves;
- completed moves;
- move errors;
- per-artifact decisions and reasons.

---

## Safety model

The retention engine never deletes files directly.

Expected lifecycle:

```text
source archive
     ¦
     ?
retention classification
     ¦
     ?
quarantine
     ¦
     ?
delayed purge
```

This preserves traceability and limits accidental data loss.