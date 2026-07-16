#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/airmonitor}"
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
STATE_DIR="${STATE_DIR:-/var/lib/airmonitor/update-state}"
SERVICE_LIST="${SERVICE_LIST:-airmonitor.target airmonitor-printer-mqtt.service airmonitor-voc.service airmonitor-sps30.service airmonitor-bento.service airmonitor-levoit.service airmonitor-status.service airmonitor-export.service}"
PIP_BIN="$APP_DIR/venv/bin/pip"
DOCTOR_BIN="$APP_DIR/venv/bin/airmonitor-doctor"
TARGET_COMMIT="${1:-}"

log() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

[[ -d "$REPO_DIR/.git" ]] || fail "not a Git repository: $REPO_DIR"
[[ -x "$PIP_BIN" ]] || fail "missing virtualenv pip: $PIP_BIN"

if [[ -z "$TARGET_COMMIT" ]]; then
  [[ -f "$STATE_DIR/previous-commit" ]] || fail "no saved previous commit; pass a commit SHA explicitly"
  TARGET_COMMIT="$(<"$STATE_DIR/previous-commit")"
fi

git -C "$REPO_DIR" cat-file -e "$TARGET_COMMIT^{commit}" 2>/dev/null || fail "unknown commit: $TARGET_COMMIT"

WORKTREE="$(mktemp -d /tmp/airmonitor-rollback.XXXXXX)"
cleanup() {
  git -C "$REPO_DIR" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
  rm -rf "$WORKTREE"
}
trap cleanup EXIT

log "Preparing rollback worktree at $TARGET_COMMIT"
git -C "$REPO_DIR" worktree add --detach "$WORKTREE" "$TARGET_COMMIT"

log "Installing AirMonitor from rollback commit"
sudo "$PIP_BIN" install --upgrade "$WORKTREE"

log "Restoring systemd units from rollback commit"
RESTORE_SERVICES=""
for service in $SERVICE_LIST; do
  if [[ -f "$WORKTREE/systemd/$service" ]]; then
    sudo install -o root -g root -m 0644 "$WORKTREE/systemd/$service" "/etc/systemd/system/$service"
    RESTORE_SERVICES="$RESTORE_SERVICES $service"
  else
    # A rollback may predate a newly introduced optional service. Stop and
    # remove that unit instead of making the older commit impossible to restore.
    sudo systemctl stop "$service" 2>/dev/null || true
    sudo rm -f "/etc/systemd/system/$service"
  fi
done
sudo systemctl daemon-reload

log "Restarting services"
for service in $RESTORE_SERVICES; do
  sudo systemctl restart "$service"
done

sleep 2
for service in $RESTORE_SERVICES; do
  systemctl is-active --quiet "$service" || fail "$service failed after rollback"
done

if [[ -x "$DOCTOR_BIN" ]]; then
  log "Running AirMonitor health check"
  sudo "$DOCTOR_BIN"
fi

log "Rollback installation complete"
printf 'Installed commit: %s\n' "$TARGET_COMMIT"
printf 'Repository checkout was not changed.\n'
