# Quarantine purge engine

## Purpose

The purge engine is the final stage of the archive lifecycle.

It permanently deletes quarantine folders that have exceeded their mandatory grace period.

---

## Safety mechanisms

Permanent deletion is a high-risk operation. The engine implements multiple protection layers:

1. **Mandatory grace period**  
   Only directories matching `YYYY-MM-DD` are considered, and only when older than `quarantine_min_age_days`.

2. **Double confirmation**  
   Deletion only occurs when both conditions are true:
   - the policy contains `allow_purge: true`;
   - the CLI flag `--apply` is provided.

3. **Strict path validation**  
   Every deletion target must be strictly located under the quarantine root.

4. **Root protection**  
   The quarantine root itself is never deleted.

5. **Dry-run by default**  
   Without `--apply`, the engine only simulates the purge and writes a report.

---

## Decisions

| Decision | Meaning |
|---|---|
| `PURGE_QUARANTINE_EXPIRED` | Directory is older than threshold and eligible for deletion |
| `KEEP_QUARANTINE_RECENT` | Directory is still within the grace period |
| `KEEP_QUARANTINE_UNDATED` | Directory name does not match `YYYY-MM-DD` |
| `KEEP_QUARANTINE_INVALID` | Item is not a directory |
| `PURGE_ERROR` | An error occurred during deletion |

---

## Policy configuration

Example:

```yaml
# Minimum number of days an archive must stay in quarantine before being purged
quarantine_min_age_days: 30

# Master switch for permanent deletion
allow_purge: false
```

---

## Audit trail

Every execution produces a Markdown report containing:

- execution mode;
- policy values;
- planned deletions;
- completed deletions;
- errors;
- per-folder decisions.

This ensures traceability of the destruction phase.