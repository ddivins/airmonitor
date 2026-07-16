#!/usr/bin/env bash
set -euo pipefail

SERVICE_LIST="${SERVICE_LIST:-airmonitor.target airmonitor-printer-mqtt.service airmonitor-voc.service airmonitor-sps30.service airmonitor-bento.service airmonitor-levoit.service airmonitor-status.service airmonitor-export.service}"
APP_DIR="${APP_DIR:-/opt/airmonitor}"
ENV_FILE="${ENV_FILE:-/etc/airmonitor/sgx-voc.env}"
REQUIRED_ENV_FILES="${REQUIRED_ENV_FILES:-/etc/airmonitor/sgx-voc.env /etc/airmonitor/sps30.env /etc/airmonitor/printer-mqtt.env /etc/airmonitor/bento.env /etc/airmonitor/levoit.env}"
POLICY_SRC="${POLICY_SRC:-config/filament-policy.yaml}"
POLICY_DST="${POLICY_DST:-/etc/airmonitor/filament-policy.yaml}"
HARDWARE_SRC="${HARDWARE_SRC:-config/hardware.yaml.example}"
HARDWARE_DST="${HARDWARE_DST:-/etc/airmonitor/hardware.yaml}"
UNIT_DIR="${UNIT_DIR:-systemd}"
DATA_DIR="${DATA_DIR:-/var/lib/airmonitor}"
STATE_DIR="${STATE_DIR:-$DATA_DIR/update-state}"
SERVICE_USER="${SERVICE_USER:-automation}"
SERVICE_GROUP="${SERVICE_GROUP:-automation}"
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
INSTALL_GRAFANA="${INSTALL_GRAFANA:-auto}"
PIP_BIN="$APP_DIR/venv/bin/pip"
DOCTOR_BIN="$APP_DIR/venv/bin/airmonitor-doctor"

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

trap 'rc=$?; if [[ $rc -ne 0 ]]; then printf "\nUpdate failed with exit code %s\n" "$rc" >&2; printf "Rollback with: cd %s && bash tools/rollback.sh\n" "$REPO_DIR" >&2; fi' EXIT

log "Validating environment"
command -v git >/dev/null || fail "git is not installed"
command -v systemctl >/dev/null || fail "systemctl is not available"
[[ -d "$REPO_DIR/.git" ]] || fail "not a Git repository: $REPO_DIR"
[[ -f "$REPO_DIR/pyproject.toml" ]] || fail "missing pyproject.toml in $REPO_DIR"
[[ -f "$REPO_DIR/$POLICY_SRC" ]] || fail "missing filament policy: $REPO_DIR/$POLICY_SRC"
[[ -f "$REPO_DIR/$HARDWARE_SRC" ]] || fail "missing hardware registry template: $REPO_DIR/$HARDWARE_SRC"
[[ -x "$PIP_BIN" ]] || fail "missing virtualenv pip: $PIP_BIN"
for env_file in $REQUIRED_ENV_FILES; do
  [[ -f "$env_file" ]] || fail "missing env file: $env_file"
done
id "$SERVICE_USER" >/dev/null 2>&1 || fail "missing service user: $SERVICE_USER"
for service in $SERVICE_LIST; do
  [[ -f "$REPO_DIR/$UNIT_DIR/$service" ]] || fail "missing systemd unit: $REPO_DIR/$UNIT_DIR/$service"
done

cd "$REPO_DIR"

PREVIOUS_COMMIT="$(git rev-parse HEAD)"
PREVIOUS_VERSION="$($APP_DIR/venv/bin/python -c 'import importlib.metadata; print(importlib.metadata.version("airmonitor"))' 2>/dev/null || echo unknown)"
UPDATE_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

log "Recording rollback state"
sudo install -d -o root -g root -m 0755 "$STATE_DIR"
printf '%s\n' "$PREVIOUS_COMMIT" | sudo tee "$STATE_DIR/previous-commit" >/dev/null
printf '%s\n' "$PREVIOUS_VERSION" | sudo tee "$STATE_DIR/previous-version" >/dev/null
printf '%s\n' "$UPDATE_TIME" | sudo tee "$STATE_DIR/last-update-started" >/dev/null

log "Updating repository: $REPO_DIR"
git pull --ff-only
NEW_COMMIT="$(git rev-parse HEAD)"
printf '%s\n' "$NEW_COMMIT" | sudo tee "$STATE_DIR/target-commit" >/dev/null

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

log "Ensuring hardware registry exists"
sudo install -d -o root -g root -m 0755 "$(dirname "$HARDWARE_DST")"
if [[ ! -f "$HARDWARE_DST" ]]; then
  sudo install -o root -g root -m 0644 "$HARDWARE_SRC" "$HARDWARE_DST"
  echo "Installed initial hardware registry: $HARDWARE_DST"
else
  echo "Preserving existing hardware registry: $HARDWARE_DST"
fi

log "Installing systemd units"
for service in $SERVICE_LIST; do
  sudo install -o root -g root -m 0644 "$UNIT_DIR/$service" "/etc/systemd/system/$service"
done
sudo systemctl daemon-reload
sudo systemctl enable airmonitor.target >/dev/null

if command -v nginx >/dev/null || [[ -x /usr/sbin/nginx ]]; then
  log "Installing AirMonitor status page routing"
  bash tools/install-status-page.sh
fi

if [[ "$INSTALL_GRAFANA" == "1" ]] || { [[ "$INSTALL_GRAFANA" == "auto" ]] && command -v grafana >/dev/null && systemctl list-unit-files grafana-server.service >/dev/null 2>&1; }; then
  log "Installing Grafana datasource and dashboards"
  bash tools/install-grafana.sh
fi

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

if [[ -x "$DOCTOR_BIN" ]]; then
  log "Running AirMonitor health check"
  sudo "$DOCTOR_BIN"
fi

printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" | sudo tee "$STATE_DIR/last-update-succeeded" >/dev/null
printf '%s\n' "$NEW_COMMIT" | sudo tee "$STATE_DIR/installed-commit" >/dev/null

log "Update complete"
printf 'Previous commit: %s\n' "$PREVIOUS_COMMIT"
printf 'Installed commit: %s\n' "$NEW_COMMIT"
printf 'Rollback command: cd %s && bash tools/rollback.sh\n' "$REPO_DIR"
