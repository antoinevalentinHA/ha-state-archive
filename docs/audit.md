# Audit engine

## Purpose

The audit engine verifies the structural integrity of extracted Home Assistant versions.

It is designed to detect inconsistencies without modifying archived data.

---

## Core principles

### Observational only

The audit engine never repairs or modifies Home Assistant files.

It only reads, classifies and reports.

---

### Reproducible

The audit operates exclusively on extracted files.

It does not require a running Home Assistant instance and does not depend on external APIs.

---

### Actionable by design

The engine intentionally separates:

- **actionable anomalies**: issues that may require user action;
- **architectural observations**: noteworthy situations that should be reported but do not count as anomalies.

This distinction reduces false positives while preserving observability.

---

## Authority model

Home Assistant entities do not all share the same source of truth.

The audit engine distinguishes two authority classes:

| Authority | Meaning |
|---|---|
| `registry_authority` | Entity is expected to appear in `.storage/core.entity_registry` |
| `runtime_yaml_authority` | Entity may be valid at runtime while being absent from the registry |

This distinction prevents false positives.

Some YAML-defined platforms are expected to function without generating registry entries.

Those cases are reported as architectural observations instead of actionable anomalies.

Platforms currently classified as `runtime_yaml_authority`:

`group`, `utility_meter`, `statistics`, `history_stats`, `manual_alarm_panel`, `zone`.

---

## Extracted declarations

The declaration extractor identifies YAML-declared entities.

It classifies declarations by confidence level:

| Confidence | Meaning |
|---|---|
| `high` | Entity ID can be reconstructed reliably |
| `partial` | Structure is detected, but entity ID cannot be reconstructed safely |

High-confidence declarations are cross-checked against the registry.

Partial-confidence declarations are recorded for traceability but excluded from registry cross-checks.

---

## Reference extraction

The reference extractor detects entity references from:

- structured YAML keys;
- simple Jinja calls;
- dynamic Jinja patterns.

Reference types include:

| Reference type | Meaning |
|---|---|
| `structured` | Entity reference found in structured YAML |
| `jinja_simple` | Static entity reference found in a Jinja call |
| `jinja_dynamic` | Dynamic or partially resolvable Jinja reference |

Dynamic references are tracked separately and are not treated as broken static references.

---

## Actionable anomalies

The audit engine currently reports the following anomaly classes:

| Type | Meaning |
|---|---|
| `declared_not_in_registry` | High-confidence YAML declaration missing from registry |
| `registry_not_declared` | Registry entity without matching YAML declaration |
| `declared_duplicate` | Same entity declared multiple times in YAML |
| `registry_duplicate` | Duplicate entity ID detected in registry |
| `broken_reference` | Static reference to an entity absent from registry and declarations |
| `non_canonical_entity_id_case` | Reference likely resolves but does not match canonical entity ID form |

Broken reference severity depends on execution context.

Examples:

- automation and script contexts are considered higher risk;
- template contexts are considered medium risk;
- passive or contextual references may be downgraded.

---

## Architectural observations

Architectural observations are reported separately from anomalies.

They do not increment `total_anomalies`.

The primary observation type is:

| Type | Meaning |
|---|---|
| `runtime_yaml_observation` | YAML declaration belongs to a runtime YAML authority platform and is not expected in registry |

---

## Severity model

| Severity | Meaning |
|---|---|
| `P0` | Critical structural issue likely to break automation or governance |
| `P1` | Important integrity issue requiring review |
| `P2` | Low-risk or contextual issue |
| `P3` | Informational issue |

---

## Output artifacts

### Markdown report

A bounded human-readable report produced at the path provided via `--report`.

Contains:

- system metadata (engine version, execution date, target path);
- global statistics;
- severity summary;
- anomaly type summary;
- per-anomaly details with evidence and notes;
- architectural observations.

### Verdict JSON

An optional compact machine-readable verdict file produced at the path provided via `--verdict-json`.

Used by the MQTT publication layer. See `docs/mqtt.md` for the payload contract.

Verdict values:

| Verdict | Condition |
|---|---|
| `ok` | Zero actionable anomalies |
| `critical` | At least one P0 anomaly |
| `degraded` | Anomalies present, none at P0 |

The verdict JSON includes:

- `contract_version`
- `engine_version`
- `published_at`
- `audited_version` (derived from the `--ha-root` directory name)
- `verdict`
- `total_anomalies`
- `anomaly_categories`
- `report_path`

---

## Exit codes

| Exit code | Meaning |
|---:|---|
| `0` | Audit completed successfully with no actionable anomalies |
| `30` | Audit completed with actionable anomalies detected |
| `1` | Input validation or configuration error |
| `2` | Internal engine error |

---

## CLI usage

```sh
python3 src/ha_state_archive/audit/audit_engine.py \
  --ha-root /path/to/versions/2026-01-15_09-00_HomeAssistant \
  --config  /path/to/config/audit_config.yaml \
  --report  /path/to/reports/audit_2026-01-15.md
```

With verdict JSON for MQTT publication:

```sh
python3 src/ha_state_archive/audit/audit_engine.py \
  --ha-root      /path/to/versions/2026-01-15_09-00_HomeAssistant \
  --config       /path/to/config/audit_config.yaml \
  --report       /path/to/reports/audit_2026-01-15.md \
  --verdict-json /path/to/verdicts/latest.verdict.json
```

---

## Non-goals

The audit engine does not:

- repair Home Assistant configurations;
- modify archived versions;
- replace Home Assistant native validation;
- fully resolve runtime-only dynamic templates;
- require Home Assistant to be running.
