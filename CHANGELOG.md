# Changelog

All notable changes to this project will be documented in this file.

---

## [0.1.0] — 2026-05-13

First public release of `ha-state-archive`.

### Added

#### Ingestion

- `src/ha_state_archive/ingestion/extract.py` — Home Assistant encrypted backup ingestion pipeline.
  - Decrypts and extracts relevant configuration and state files using `hassio-tar`.
  - Produces immutable versioned directories under a configurable `versions/` root.
  - Atomic extraction via staging directory and atomic rename.
  - SHA256-based state file prevents redundant reprocessing.
  - Tolerates older backup structures with partial patrimony coverage.
  - Supports `--latest-only`, `--limit`, `--since-date`, `--force`, `--dry-run`, `--stop-on-error`.
  - `HASSIO_PASSWORD` required but never logged.

#### Audit engine

- `src/ha_state_archive/audit/audit_engine.py` — Structural integrity audit for extracted Home Assistant versions.
  - Cross-checks YAML declarations against `core.entity_registry`.
  - Detects: `declared_not_in_registry`, `registry_not_declared`, `declared_duplicate`, `registry_duplicate`, `broken_reference`, `non_canonical_entity_id_case`.
  - Separates actionable anomalies (P0–P3) from architectural observations (`runtime_yaml_observation`).
  - Severity model: P0 for critical platforms and automation/script references, P1 for standard mismatches, P2 for non-critical cases.
  - Produces a bounded Markdown report and an optional compact verdict JSON (`--verdict-json`).
  - Exit codes: `0` (OK), `30` (anomalies detected), `2` (internal error).

- `src/ha_state_archive/audit/include_resolver.py` — Recursive `!include` graph resolver.
  - Supports all HA include tags: `!include`, `!include_dir_list`, `!include_dir_named`, `!include_dir_merge_list`, `!include_dir_merge_named`.
  - Cycle detection. Missing file warnings without hard failure.

- `src/ha_state_archive/audit/declaration_extractor.py` — YAML declaration extractor.
  - High-confidence extraction for: `input_boolean`, `input_text`, `input_number`, `input_datetime`, `input_select`, `counter`, `timer`, `utility_meter`, `group`, `manual_alarm_panel`, `history_stats`, `zone`.
  - Partial extraction for: `template`.
  - Authority classification: `registry_authority` vs `runtime_yaml_authority`.
  - Local HA-compatible slugify implementation with inline test cases.

- `src/ha_state_archive/audit/registry_reader.py` — `core.entity_registry` reader.
  - Local-platform filtering. External config entry exclusion.

- `src/ha_state_archive/audit/reference_extractor.py` — Static entity reference extractor.
  - Structured key extraction (`entity_id`, `entity`, `entities`).
  - Jinja2 simple function extraction (`states`, `is_state`, `state_attr`, `has_value`, `is_state_attr`).
  - Dynamic reference detection (`<dynamic>`, `<prefix:...>`, `<expand_or_area>`).

#### Diff engine

- `src/ha_state_archive/diff/release_diff.py` — Release-to-release Markdown diff generator.
  - Semantic release anchor detection via version tag pattern (`vN`, `vN.M`).
  - SHA256 snapshot integrity for idempotent generation.
  - Volatile file exclusion (`.storage/`, databases, logs, caches).
  - Bounded output: `MAX_LINES_PER_FILE = 500`, `MAX_DETAILED_FILES = 100`, `MAX_OUTPUT_SIZE_BYTES = 1 MB`.
  - Persistent release state and index generation.
  - Supports `--dry-run`, `--force`, `--couple`.

#### Retention engine

- `src/ha_state_archive/retention/retention_manager.py` — Archive retention classifier and quarantine manager.
  - Asymmetric retention: protected releases, critical artifacts, automatic backups, temporal candidates.
  - Quarantine-before-purge: no direct deletion.
  - Dry-run by default. `--apply` required for moves.
  - Decisions: `KEEP_MAJOR`, `KEEP_CRITICAL`, `KEEP_AUTOMATIC_RECENT`, `QUARANTINE_AUTOMATIC_OLD`, `KEEP_RECENT`, `KEEP_DAILY`, `KEEP_WEEKLY`, `CANDIDATE_DELETE`.

- `src/ha_state_archive/retention/quarantine_purger.py` — Delayed quarantine purge engine.
  - Strict path validation: target must be strictly under quarantine root.
  - Double confirmation: `allow_purge: true` (policy) + `--apply` (CLI).
  - Date-keyed quarantine directories (`YYYY-MM-DD`). Non-conforming directories are preserved.
  - Decisions: `PURGE_QUARANTINE_EXPIRED`, `KEEP_QUARANTINE_RECENT`, `KEEP_QUARANTINE_UNDATED`, `KEEP_QUARANTINE_INVALID`, `PURGE_ERROR`.

#### MQTT supervision

- `src/ha_state_archive/mqtt/publish_audit_mqtt.py` — Compact audit verdict publisher.
  - Publishes the verdict JSON produced by the audit engine to a configurable MQTT topic.
  - Payload contract v1.0.0: `contract_version`, `engine_version`, `published_at`, `audited_version`, `verdict`, `total_anomalies`.
  - Verdict values: `ok`, `degraded`, `critical`, `error`, `unknown`.
  - MQTT credentials via environment variables or strict env file.
  - Optional `--strict-freshness` mode (5-minute verdict freshness window).
  - Exit codes: `0` (published), `1` (connection or publication failure), `2` (configuration error).

#### Pipeline scripts

- `scripts/run_pipeline.sh` — Full ingestion → audit → MQTT publication pipeline.
  - Configured entirely via `HSA_*` environment variables.
  - Pre-flight checks for all required variables.
  - Propagates audit exit code `30` as pipeline exit code.

- `scripts/watch_new_backup.sh` — Watcher for new backup stabilization.
  - Double `du -s` measurement with configurable stabilization delay.
  - PID-based lockfile. Version tracking via last-processed state file.

#### Configuration

- `config/retention_policy.example.yaml` — Annotated retention policy template.
- `examples/retention_policy.example.yaml` — Retention policy example.
- `examples/quarantine_purger_policy.example.yaml` — Purge policy example.
- `examples/mqtt_payload.example.json` — MQTT verdict payload example.

#### Documentation

- `docs/architecture.md` — High-level pipeline architecture and design philosophy.
- `docs/invariants.md` — Normative architectural invariants (I-1 through I-17).
- `docs/audit.md` — Audit engine reference.
- `docs/diff.md` — Diff engine reference.
- `docs/retention.md` — Retention engine reference.
- `docs/purge.md` — Quarantine purge engine reference.
- `docs/mqtt.md` — MQTT supervision contract.
- `docs/synology_dsm.md` — Synology DSM integration guide.
