#!/bin/sh

set -eu

# ---------------------------------------------------------------------------
# ha-state-archive — main pipeline
#
# Runs the full ingestion → audit → MQTT publication sequence.
#
# Required environment variables:
#
#   HSA_BASE_DIR          Base directory of the ha-state-archive installation.
#                         Default: /opt/ha-state-archive
#
#   HSA_BACKUP_DIR        Directory containing Home Assistant .tar backup files.
#
#   HSA_VERSIONS_DIR      Directory where extracted immutable versions are stored.
#                         Default: $HSA_BASE_DIR/versions
#
#   HSA_TEMP_DIR          Temporary directory for atomic extractions.
#                         Default: $HSA_BASE_DIR/temp
#
#   HSA_STATE_FILE        Path to the ingestion state JSON file.
#                         Default: $HSA_BASE_DIR/state/processed_backups.json
#
#   HSA_AUDIT_CONFIG      Path to the audit configuration YAML file.
#
#   HSA_REPORTS_DIR       Directory where audit Markdown reports are written.
#                         Default: $HSA_BASE_DIR/reports
#
#   HSA_VERDICT_DIR       Directory where audit verdict JSON files are written.
#                         Default: $HSA_BASE_DIR/verdicts
#
#   HSA_HASSIO_TAR        Path to the hassio-tar binary used to decrypt backups.
#
#   HSA_MQTT_ENV          Path to the MQTT credentials env file.
#                         Optional. If not set, MQTT publication reads from
#                         environment variables directly.
#
#   HASSIO_PASSWORD       Home Assistant backup decryption password.
#                         Must be set before running this script.
# ---------------------------------------------------------------------------

BASE_DIR="${HSA_BASE_DIR:-/opt/ha-state-archive}"

BACKUP_DIR="${HSA_BACKUP_DIR:-}"
VERSIONS_DIR="${HSA_VERSIONS_DIR:-$BASE_DIR/versions}"
TEMP_DIR="${HSA_TEMP_DIR:-$BASE_DIR/temp}"
STATE_FILE="${HSA_STATE_FILE:-$BASE_DIR/state/processed_backups.json}"
AUDIT_CONFIG="${HSA_AUDIT_CONFIG:-}"
REPORTS_DIR="${HSA_REPORTS_DIR:-$BASE_DIR/reports}"
VERDICT_DIR="${HSA_VERDICT_DIR:-$BASE_DIR/verdicts}"
HASSIO_TAR="${HSA_HASSIO_TAR:-}"
MQTT_ENV="${HSA_MQTT_ENV:-}"

LOG_DIR="$BASE_DIR/logs/pipeline"
mkdir -p "$LOG_DIR"

TS="$(date '+%Y-%m-%d_%H-%M-%S')"
LOG_FILE="$LOG_DIR/pipeline_$TS.log"

exec >> "$LOG_FILE" 2>&1

log() {
  echo "[$(date '+%F %T')] $*"
}

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

if [ -z "$BACKUP_DIR" ]; then
  log "ERROR: HSA_BACKUP_DIR is not set"
  exit 1
fi

if [ -z "$AUDIT_CONFIG" ]; then
  log "ERROR: HSA_AUDIT_CONFIG is not set"
  exit 1
fi

if [ -z "$HASSIO_TAR" ]; then
  log "ERROR: HSA_HASSIO_TAR is not set"
  exit 1
fi

mkdir -p "$VERSIONS_DIR" "$TEMP_DIR" "$REPORTS_DIR" "$VERDICT_DIR" \
         "$(dirname "$STATE_FILE")"

# ---------------------------------------------------------------------------
# Derived paths
# ---------------------------------------------------------------------------

REPORT_PATH="$REPORTS_DIR/audit_$TS.md"
VERDICT_PATH="$VERDICT_DIR/latest.verdict.json"

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

log "=== PIPELINE START ==="

# --- Ingestion --------------------------------------------------------------

EXTRACT_RC=0

python3 "$BASE_DIR/src/ha_state_archive/ingestion/extract.py" \
  --backup-dir   "$BACKUP_DIR"   \
  --versions-dir "$VERSIONS_DIR" \
  --temp-dir     "$TEMP_DIR"     \
  --state        "$STATE_FILE"   \
  --hassio-tar   "$HASSIO_TAR"   \
  --latest-only  \
  || EXTRACT_RC=$?

log "Extraction RC=$EXTRACT_RC"

if [ "$EXTRACT_RC" -ne 0 ]; then
  log "Pipeline abort: extraction failed"
  log "=== PIPELINE END ==="
  exit "$EXTRACT_RC"
fi

# Resolve the latest extracted version directory for the audit.
LATEST_VERSION="$(
  find "$VERSIONS_DIR" \
    -mindepth 1 -maxdepth 1 \
    -type d \
    ! -name '_quarantine' \
    -printf '%f\n' \
  | sort \
  | tail -1
)"

if [ -z "$LATEST_VERSION" ]; then
  log "Pipeline abort: no version found after extraction"
  log "=== PIPELINE END ==="
  exit 1
fi

HA_ROOT="$VERSIONS_DIR/$LATEST_VERSION"
log "Auditing version: $LATEST_VERSION"

# --- Audit ------------------------------------------------------------------

AUDIT_RC=0

python3 "$BASE_DIR/src/ha_state_archive/audit/audit_engine.py" \
  --ha-root      "$HA_ROOT"      \
  --config       "$AUDIT_CONFIG" \
  --report       "$REPORT_PATH"  \
  --verdict-json "$VERDICT_PATH" \
  || AUDIT_RC=$?

log "Audit RC=$AUDIT_RC"

# --- MQTT publication -------------------------------------------------------

PUBLISH_RC=0

if [ -n "$MQTT_ENV" ]; then
  python3 "$BASE_DIR/src/ha_state_archive/mqtt/publish_audit_mqtt.py" \
    --verdict-json    "$VERDICT_PATH" \
    --audit-rc        "$AUDIT_RC"     \
    --mqtt-env        "$MQTT_ENV"     \
    --strict-freshness \
    || PUBLISH_RC=$?
else
  python3 "$BASE_DIR/src/ha_state_archive/mqtt/publish_audit_mqtt.py" \
    --verdict-json    "$VERDICT_PATH" \
    --audit-rc        "$AUDIT_RC"     \
    --strict-freshness \
    || PUBLISH_RC=$?
fi

log "Publish RC=$PUBLISH_RC"

if [ "$PUBLISH_RC" -ne 0 ]; then
  log "WARNING: MQTT publication failed"
fi

# --- Final verdict ----------------------------------------------------------

case "$AUDIT_RC" in
  0)
    log "Audit verdict: OK"
    ;;
  30)
    log "Pipeline alert: actionable anomaly detected"
    log "=== PIPELINE END ==="
    exit 30
    ;;
  *)
    log "Pipeline abort: unexpected audit exit code ($AUDIT_RC)"
    log "=== PIPELINE END ==="
    exit 31
    ;;
esac

log "=== PIPELINE END ==="

exit 0
