#!/bin/sh

set -eu

BASE_DIR="${HSA_BASE_DIR:-/opt/ha-state-archive}"

LOG_DIR="$BASE_DIR/logs/pipeline"
mkdir -p "$LOG_DIR"

TS="$(date '+%Y-%m-%d_%H-%M-%S')"
LOG_FILE="$LOG_DIR/pipeline_$TS.log"

exec >> "$LOG_FILE" 2>&1

echo "[`date '+%F %T'`] === PIPELINE START ==="

export HASSIO_PASSWORD="${HASSIO_PASSWORD:-}"

EXTRACT_RC=0

python3 "$BASE_DIR/src/ha_state_archive/ingestion/extract.py" \
  --latest-only \
  || EXTRACT_RC=$?

echo "[`date '+%F %T'`] Extraction RC=$EXTRACT_RC"

if [ "$EXTRACT_RC" -ne 0 ]; then
  echo "[`date '+%F %T'`] Pipeline abort: extraction failed"
  exit "$EXTRACT_RC"
fi

AUDIT_RC=0

python3 "$BASE_DIR/src/ha_state_archive/audit/audit_engine.py" \
  || AUDIT_RC=$?

echo "[`date '+%F %T'`] Audit RC=$AUDIT_RC"

PUBLISH_RC=0

python3 "$BASE_DIR/src/ha_state_archive/mqtt/publish_audit_mqtt.py" \
  --audit-rc "$AUDIT_RC" \
  || PUBLISH_RC=$?

echo "[`date '+%F %T'`] Publish RC=$PUBLISH_RC"

if [ "$PUBLISH_RC" -ne 0 ]; then
  echo "[`date '+%F %T'`] WARNING: MQTT publication failed"
fi

case "$AUDIT_RC" in
  0)
    echo "[`date '+%F %T'`] Audit verdict: OK"
    ;;
  30)
    echo "[`date '+%F %T'`] Pipeline alert: actionable anomaly detected"
    echo "[`date '+%F %T'`] === PIPELINE END ==="
    exit 30
    ;;
  *)
    echo "[`date '+%F %T'`] Pipeline abort: unexpected audit exit code ($AUDIT_RC)"
    echo "[`date '+%F %T'`] === PIPELINE END ==="
    exit 31
    ;;
esac

echo "[`date '+%F %T'`] === PIPELINE END ==="

exit 0