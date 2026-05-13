#!/bin/bash

set -u

BASE_DIR="${HSA_BASE_DIR:-/opt/ha-state-archive}"
VERSIONS_DIR="${HSA_VERSIONS_DIR:-$BASE_DIR/versions}"
RUNTIME_DIR="${HSA_RUNTIME_DIR:-$BASE_DIR/runtime}"
PIPELINE_SCRIPT="${HSA_PIPELINE_SCRIPT:-$BASE_DIR/scripts/run_pipeline.sh}"
STABILIZATION_DELAY="${HSA_STABILIZATION_DELAY:-60}"

LOCK_FILE="$RUNTIME_DIR/watch_new_backup.lock"
LAST_FILE="$RUNTIME_DIR/last_processed_version.txt"
LOG_FILE="$RUNTIME_DIR/watch_new_backup.log"

mkdir -p "$RUNTIME_DIR"

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "$LOG_FILE"
}

fail() {
  log "ERROR: $*"
  exit 1
}

if [ -f "$LOCK_FILE" ]; then
  OLD_PID="$(cat "$LOCK_FILE" 2>/dev/null || true)"

  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    log "Watcher already running (PID=$OLD_PID)"
    exit 0
  fi

  log "Orphan lockfile detected"
  rm -f "$LOCK_FILE"
fi

trap 'rm -f "$LOCK_FILE"' EXIT

echo $$ > "$LOCK_FILE"

LATEST_VERSION="$(
  find "$VERSIONS_DIR" \
    -mindepth 1 \
    -maxdepth 1 \
    -type d \
    ! -name '_quarantine' \
    -printf '%f\n' \
  | sort \
  | tail -1
)"

[ -n "$LATEST_VERSION" ] || fail "No version detected"

log "Latest version detected: $LATEST_VERSION"

LAST_PROCESSED=""

if [ -f "$LAST_FILE" ]; then
  LAST_PROCESSED="$(cat "$LAST_FILE")"
fi

if [ "$LATEST_VERSION" = "$LAST_PROCESSED" ]; then
  log "No new version"
  exit 0
fi

VERSION_PATH="$VERSIONS_DIR/$LATEST_VERSION"

SIZE_1="$(du -s "$VERSION_PATH" | awk '{print $1}')"

sleep "$STABILIZATION_DELAY"

SIZE_2="$(du -s "$VERSION_PATH" | awk '{print $1}')"

if [ "$SIZE_1" != "$SIZE_2" ]; then
  log "Version still unstable — size changed"
  exit 0
fi

log "Stable version confirmed"
log "Starting pipeline"

"$PIPELINE_SCRIPT"
PIPELINE_RC=$?

log "Pipeline finished with exit code $PIPELINE_RC"

case "$PIPELINE_RC" in
  0|30)
    echo "$LATEST_VERSION" > "$LAST_FILE"
    log "Version marked as processed"
    ;;
  *)
    fail "Pipeline failed ($PIPELINE_RC)"
    ;;
esac

exit 0