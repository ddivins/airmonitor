#!/usr/bin/env bash
set -euo pipefail

SERVICE_LIST="${SERVICE_LIST:-airmonitor-printer-mqtt.service airmonitor.service airmonitor-bento.service airmonitor-levoit.service}"
APP_DIR="${APP_DIR:-/opt/airmonitor}"
ENV_FILE="${ENV_FILE:-/etc/airmonitor.env}"
POLICY_SRC="${POLICY_SRC:-config/filament-policy.yaml}"
POLICY_DST="${POLICY_DST:-/etc/airmonitor/filament-policy.yaml}"
UNIT_DIR="${UNIT_DIR:-systemd}"
DATA_DIR="${DATA_DIR:-/var/lib/airmonitor}"
SERVICE_USER="${SERVICE_USER:-automation}"
SERVICE_GROUP="${SERVICE_GROUP:-automation}"
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PIP_BIN="$APP_DIR/venv/bin/pip"

log() {
  printf '\n==> %s\n' "$*"
}

fail() {
  printf '\nERROR: %s\n' "$*" >&2
  exit 1
}

show_failure_logs() {
  local service="$1"
  printf '\n==> %s failed to start cleanly; recent journal follows\n' "$service" >&2
  sudo journalctl -u "$service" -n 60 --no-pager >&2 || true
}

trap 'rc=$?; if [[ $rc -ne 0 ]]; then printf "\nUpdate failed with exit code %s\n" "$rc" >&2; fi' EXIT

log "Validating environment"
command -v git >/dev/null || fail "git is not installed"
command -v systemctl >/dev/null || fail "systemctl is not available"
[[ -d "$REPO_DIR/.git" ]] || fail "not a Git repository: $REPO_DIR"
[[ -f "$REPO_DIR/pyproject.toml" ]] || fail "missing pyproject.toml in $REPO_DIR"
[[ -f "$REPO_DIR/$POLICY_SRC" ]] || fail "missing filament policy: $REPO_DIR/$POLICY_SRC"
[[ -x "$PIP_BIN" ]] || fail "missing virtualenv pip: $PIP_BIN"
[[ -f "$ENV_FILE" ]] || fail "missing env file: $ENV_FILE"
id "$SERVICE_USER" >/dev/null 2>&1 || fail "missing service user: $SERVICE_USER"
for service in $SERVICE_LIST; do
  [[ -f "$REPO_DIR/$UNIT_DIR/$service" ]] || fail "missing systemd unit: $REPO_DIR/$UNIT_DIR/$service"
done

cd "$REPO_DIR"

log "Updating repository: $REPO_DIR"
git pull --ff-only

log "Installing package into $APP_DIR/venv"
sudo "$PIP_BIN" install --upgrade .

log "Ensuring data directory exists"
sudo install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0755 "$DATA_DIR"

log "Installing filament policy"
sudo install -d -o root -g root -m 0755 "$(dirname "$POLICY_DST")"
if [[ ! -f "$POLICY_DST" ]]; then
  sudo install -o root -g root -m 0644 "$POLICY_SRC" "$POLICY_DST"
else
  sudo install -o root -g root -m 0644 "$POLICY_SRC" "$POLICY_DST.new"
  if ! cmp -s "$POLICY_DST" "$POLICY_DST.new"; then
    sudo mv "$POLICY_DST" "$POLICY_DST.bak.$(date +%Y%m%d-%H%M%S)"
    sudo mv "$POLICY_DST.new" "$POLICY_DST"
    echo "Updated $POLICY_DST and saved previous copy as .bak timestamp"
  else
    sudo rm "$POLICY_DST.new"
  fi
fi

log "Installing systemd units"
for service in $SERVICE_LIST; do
  sudo install -o root -g root -m 0644 "$UNIT_DIR/$service" "/etc/systemd/system/$service"
done
sudo systemctl daemon-reload

log "Restarting services"
for service in $SERVICE_LIST; do
  sudo systemctl restart "$service"
done

log "Waiting for service health"
sleep 2
for service in $SERVICE_LIST; do
  if ! systemctl is-active --quiet "$service"; then
    show_failure_logs "$service"
    exit 1
  fi
done

log "Service status"
systemctl --no-pager --full status $SERVICE_LIST

log "Recent journal"
for service in $SERVICE_LIST; do
  sudo journalctl -u "$service" -n 20 --no-pager
done
