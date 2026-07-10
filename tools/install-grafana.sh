#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
GRAFANA_HOME="${GRAFANA_HOME:-/usr/share/grafana}"
GRAFANA_SERVICE="${GRAFANA_SERVICE:-grafana-server}"
DASHBOARD_DIR="${DASHBOARD_DIR:-/var/lib/grafana/dashboards/airmonitor}"
DATASOURCE_SRC="${DATASOURCE_SRC:-grafana/provisioning/datasources/airmonitor-sqlite.yaml}"
DASHBOARD_PROVIDER_SRC="${DASHBOARD_PROVIDER_SRC:-grafana/provisioning/dashboards/airmonitor.yaml}"
DASHBOARD_SRC="${DASHBOARD_SRC:-grafana/dashboards/airmonitor-live.json}"
DASHBOARD_GENERATOR="${DASHBOARD_GENERATOR:-tools/generate-grafana-dashboard.py}"
DB_DIR="${DB_DIR:-/var/lib/airmonitor}"
DB_FILE="${DB_FILE:-/var/lib/airmonitor/airmonitor.sqlite3}"
DATA_GROUP="${DATA_GROUP:-airmonitor-data}"
GRAFANA_DOMAIN="${GRAFANA_DOMAIN:-airmonitor.example.com}"
GRAFANA_ROOT_URL="${GRAFANA_ROOT_URL:-https://airmonitor.example.com/}"
GRAFANA_DB="${GRAFANA_DB:-/var/lib/grafana/grafana.db}"
FRESH_AIRMONITOR_GRAFANA="${FRESH_AIRMONITOR_GRAFANA:-1}"

log() {
  printf '\n==> %s\n' "$*"
}

fail() {
  printf '\nERROR: %s\n' "$*" >&2
  exit 1
}

log "Validating inputs"
command -v grafana >/dev/null || fail "grafana command not found; install Grafana first"
command -v systemctl >/dev/null || fail "systemctl not found"
command -v python3 >/dev/null || fail "python3 is required"
[[ -d "$REPO_DIR/.git" ]] || fail "not a Git repository: $REPO_DIR"
[[ -f "$REPO_DIR/$DATASOURCE_SRC" ]] || fail "missing $DATASOURCE_SRC"
[[ -f "$REPO_DIR/$DASHBOARD_PROVIDER_SRC" ]] || fail "missing $DASHBOARD_PROVIDER_SRC"
[[ -f "$REPO_DIR/$DASHBOARD_GENERATOR" ]] || fail "missing dashboard generator: $REPO_DIR/$DASHBOARD_GENERATOR"

cd "$REPO_DIR"

log "Installing SQLite datasource plugin"
sudo grafana cli --homepath "$GRAFANA_HOME" plugins install frser-sqlite-datasource || true

log "Configuring Grafana server defaults"
sudo install -d -o root -g grafana -m 0750 /etc/grafana/grafana.ini.d
sudo tee /etc/grafana/grafana.ini.d/airmonitor.ini >/dev/null <<EOF
[server]
http_addr = 127.0.0.1
http_port = 3000
domain = $GRAFANA_DOMAIN
root_url = $GRAFANA_ROOT_URL

[users]
default_theme = light
EOF

if [[ -f "$DB_FILE" ]]; then
  log "Validating dashboard SQL against $DB_FILE"
  python3 "$DASHBOARD_GENERATOR" --validate-db "$DB_FILE"
fi

log "Generating dashboard artifact"
python3 "$DASHBOARD_GENERATOR" "$DASHBOARD_SRC"

log "Installing datasource provisioning"
if [[ "$FRESH_AIRMONITOR_GRAFANA" == "1" ]]; then
  sudo rm -f /etc/grafana/provisioning/datasources/airmonitor*.yaml
fi
sudo install -o root -g grafana -m 0640 "$DATASOURCE_SRC" /etc/grafana/provisioning/datasources/airmonitor-sqlite.yaml

log "Installing dashboard provisioning files"
if [[ "$FRESH_AIRMONITOR_GRAFANA" == "1" ]]; then
  sudo rm -f /etc/grafana/provisioning/dashboards/airmonitor*.yaml
  sudo rm -rf "$DASHBOARD_DIR"
fi
sudo install -o root -g grafana -m 0640 "$DASHBOARD_PROVIDER_SRC" /etc/grafana/provisioning/dashboards/airmonitor.yaml
sudo install -d -o grafana -g grafana -m 0755 "$DASHBOARD_DIR"
sudo install -o grafana -g grafana -m 0644 "$DASHBOARD_SRC" "$DASHBOARD_DIR/airmonitor-live.json"

log "Configuring AirMonitor DB permissions"
sudo groupadd --system "$DATA_GROUP" 2>/dev/null || true
sudo usermod -aG "$DATA_GROUP" grafana
sudo usermod -aG "$DATA_GROUP" automation 2>/dev/null || true
if id "${SUDO_USER:-}" >/dev/null 2>&1; then
  sudo usermod -aG "$DATA_GROUP" "$SUDO_USER" || true
fi
if [[ -d "$DB_DIR" ]]; then
  sudo chgrp "$DATA_GROUP" "$DB_DIR"
  sudo chmod 750 "$DB_DIR"
  sudo chmod g+s "$DB_DIR"
fi
if [[ -f "$DB_FILE" ]]; then
  sudo chgrp "$DATA_GROUP" "$DB_FILE"
  sudo chmod 640 "$DB_FILE"
fi

if [[ "$FRESH_AIRMONITOR_GRAFANA" == "1" && -f "$GRAFANA_DB" ]]; then
  log "Backing up Grafana DB before provisioning refresh"
  sudo install -d -o grafana -g grafana -m 0750 /var/lib/grafana/backups
  sudo cp -a "$GRAFANA_DB" "/var/lib/grafana/backups/grafana.db.airmonitor.$(date +%Y%m%d-%H%M%S)"
fi

log "Restarting Grafana"
sudo systemctl restart "$GRAFANA_SERVICE"
sleep 3
systemctl --no-pager --full status "$GRAFANA_SERVICE"

log "Provisioned dashboard"
echo "${GRAFANA_ROOT_URL%/}/d/airmonitor-live/airmonitor-live"

echo
printf 'If your user was just added to %s, log out/in or run: newgrp %s\n' "$DATA_GROUP" "$DATA_GROUP"
