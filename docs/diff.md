# Diff engine

## Purpose

The diff engine provides human-readable and statistical analysis of changes between two immutable Home Assistant versions.

It is designed to support change management, release review and long-term configuration auditing.

---

## Output artifacts

For every analyzed release couple, the engine produces two Markdown files:

1. **Detailed diff**  
   A line-by-line unified diff of text-based changes.

2. **Digest**  
   A statistical summary including changed files, top domains, top extensions, limits and exclusions.

---

## Core principles

### Bounded output

Reports must remain readable and safe to open on NAS infrastructure or GitHub.

Current limits:

- max Markdown size: 1 MB;
- max detailed files: 100;
- max lines per file: 500.

### Noise reduction

Volatile runtime data is excluded from human-readable diffs.

Default exclusions include:

- `.storage/`;
- `__pycache__/`;
- `*.log`;
- `*.db`;
- `*.db-shm`;
- `*.db-wal`.

Excluded files are still reported in the digest.

### Snapshot integrity

Exclusion only applies to diff readability.

Snapshot hashes are still computed from the full archived version, including files excluded from the human-readable diff.

### Idempotence

The engine stores processed release couples in a persistent JSON state file.

A diff is skipped when:

- the couple is already known;
- both snapshot hashes are unchanged;
- output artifacts already exist;
- `--force` is not used.

---

## Release anchors

Release anchors are detected from version directory names containing semantic tags such as:

```text
v1
v1.1
v2
```

Ambiguous anchors are rejected.

Descending comparisons are forbidden.

---

## Limitations

Renames are not interpreted in the current version.

A renamed file appears as:

```text
deleted file + added file
```

Binary file changes are detected by hash but their content is not diffed.