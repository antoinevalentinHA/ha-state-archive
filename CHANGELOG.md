# Changelog

All notable changes to this project will be documented in this file.

---

## [0.2.0] — 2026-05-14

Pipeline integrity release.

Closes all blocking issues identified in the v0.1.0 audit: the ingestion
module was absent, the audit-to-MQTT verdict path was broken, and the
orchestration script was missing required arguments throughout.

### Added

#### Ingestion

- `src/ha_state_archive/ingestion/extract.py` — Home Assistant encrypted backup ingestion module.
  - Decrypts and extracts relevant configuration and state files using `hassio-tar`.
  - Produces immutable versioned directories under a configurable `versions/` root.
  - Atomic extraction via staging directory and atomic rename.
  - SHA256-based state file prevents redundant reprocessing.
  - Tolerates older backup structures with partial patrimony coverage.
  - Supports `--latest-only`, `--limit`, `--since-date`, `--force`, `--dry-run`, `--stop-on-error`.
  - `HASSIO_PASSWORD` required but never logged.
  - All paths configurable via CLI arguments or `HSA_*` environment variables.
  - No hardcoded paths. No side effects on the backup source directory.

- `src/ha_state_archive/ingestion/__init__.py` — Package declaration.

### Changed

#### Audit engine

- `src/ha_state_archive/audit/audit_engine.py` — Added `--verdict-json` output.
  - New optional argument `--verdict-json`: writes a compact machine-readable verdict JSON file alongside the existing Markdown report.
  - Verdict schema: `contract_version`, `engine_version`, `published_at`, `audited_version`, `verdict`, `total_anomalies`, `anomaly_categories`, `report_path`.
  - Verdict values derived from anomaly severity: `ok` (zero anomalies), `critical` (P0 present), `degraded` (P1 or lower present).
  - `audited_version` set to the `ha_root` directory name, consistent with the ingestion layer naming convention.
  - Atomic write via `.tmp` + replace.
  - `report_path` backfilled into the verdict JSON after the Markdown report is written.
  - Existing behaviour unchanged when `--verdict-json` is not provided.

#### Retention engine

- `src/ha_state_archive/retention/retention_manager.py` — Hardened `extract_logical_name()`.
  - Expected directory name format (`YYYY-MM-DD_HH-MM_<label>_<id>`) is now documented in the function.
  - Non-conforming names now emit an explicit warning on stderr instead of silently falling back to the full name.
  - Classification behaviour for conforming names is unchanged.

#### Pipeline scripts

- `scripts/run_pipeline.sh` — Complete rewrite of argument wiring.
  - All three modules now receive their required arguments.
  - `extract.py` receives `--backup-dir`, `--versions-dir`, `--temp-dir`, `--state`, `--hassio-tar`.
  - `audit_engine.py` receives `--ha-root` (resolved from the latest extracted version), `--config`, `--report`, `--verdict-json`.
  - `publish_audit_mqtt.py` receives `--verdict-json`, `--audit-rc`, optional `--mqtt-env`, `--strict-freshness`.
  - Pre-flight checks for all required `HSA_*` variables with explicit error messages.
  - `HSA_MQTT_ENV` optional: MQTT credentials fall back to environment variables when not set.
  - Required variables: `HSA_BACKUP_DIR`, `HSA_AUDIT_CONFIG`, `HSA_HASSIO_TAR`.

#### Configuration

- `config/retention_policy.example.yaml` — Filled with fully annotated content.
  - All policy keys documented with purpose, expected values, and default rationale.
  - Includes notes on the versioned directory naming convention used by `extract_logical_name()`.

### Fixed

- Pipeline end-to-end execution was entirely broken in v0.1.0:
  - `extract.py` was absent; `run_pipeline.sh` referenced a non-existent module.
  - `audit_engine.py` was called without required arguments; every run failed immediately with an argparse error.
  - `publish_audit_mqtt.py` expected a verdict JSON that no component produced.
- `CHANGELOG.md` was empty in v0.1.0.
- `config/retention_policy.example.yaml` was empty in v0.1.0.

---

## [0.1.0] — 2026-05-13

First public release of `ha-state-archive`.

### Added

#### Audit engine

- `src/ha_state_archive/audit/audit_engine.py` — Structural integrity audit for extracted Home Assistant versions.
  - Cross-checks YAML declarations against `core.entity_registry`.
  - Detects: `declared_not_in_registry`, `registry_not_declared`, `declared_duplicate`, `registry_duplicate`, `broken_reference`, `non_canonical_entity_id_case`.
  - Separates actionable anomalies (P0–P3) from architectural observations (`runtime_yaml_observation`).
  - Severity model: P0 for critical platforms and automation/script references, P1 for standard mismatches, P2 for non-critical cases.
  - Produces a bounded Markdown report.
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
- `scripts/watch_new_backup.sh` — Watcher for new backup stabilization.
  - Double `du -s` measurement with configurable stabilization delay.
  - PID-based lockfile. Version tracking via last-processed state file.

#### Configuration

- `config/retention_policy.example.yaml` — Retention policy template.
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
