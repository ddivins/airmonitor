#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
GRAFANA_HOME="${GRAFANA_HOME:-/usr/share/grafana}"
GRAFANA_SERVICE="${GRAFANA_SERVICE:-grafana-server}"
GRAFANA_SYSTEMD_DROPIN_DIR="${GRAFANA_SYSTEMD_DROPIN_DIR:-/etc/systemd/system/${GRAFANA_SERVICE}.service.d}"
DASHBOARD_DIR="${DASHBOARD_DIR:-/var/lib/grafana/dashboards/airmonitor}"
DATASOURCE_SRC="${DATASOURCE_SRC:-grafana/provisioning/datasources/airmonitor-sqlite.yaml}"
DASHBOARD_PROVIDER_SRC="${DASHBOARD_PROVIDER_SRC:-grafana/provisioning/dashboards/airmonitor.yaml}"
DASHBOARD_SRC="${DASHBOARD_SRC:-grafana/dashboards/airmonitor-live.json}"
PRINT_WINDOW_DASHBOARD_SRC="${PRINT_WINDOW_DASHBOARD_SRC:-grafana/dashboards/airmonitor-print-window.json}"
COMPARE_PRINTS_DASHBOARD_SRC="${COMPARE_PRINTS_DASHBOARD_SRC:-grafana/dashboards/airmonitor-compare-prints.json}"
DASHBOARD_GENERATOR="${DASHBOARD_GENERATOR:-tools/generate-grafana-dashboard.py}"
BRAND_ASSET="${BRAND_ASSET:-grafana/assets/airmonitor-brand-300.png}"
DB_DIR="${DB_DIR:-/var/lib/airmonitor}"
DB_FILE="${DB_FILE:-/var/lib/airmonitor/airmonitor.sqlite3}"
DATA_GROUP="${DATA_GROUP:-airmonitor-data}"
GRAFANA_DOMAIN="${GRAFANA_DOMAIN:-localhost}"
GRAFANA_ROOT_URL="${GRAFANA_ROOT_URL:-http://localhost:3000/}"
GRAFANA_ANONYMOUS_ORG_NAME="${GRAFANA_ANONYMOUS_ORG_NAME:-AirMonitor}"
GRAFANA_DB="${GRAFANA_DB:-/var/lib/grafana/grafana.db}"
FRESH_AIRMONITOR_GRAFANA="${FRESH_AIRMONITOR_GRAFANA:-1}"
GRAFANA_SMTP_ENABLED="${GRAFANA_SMTP_ENABLED:-false}"
GRAFANA_SMTP_HOST="${GRAFANA_SMTP_HOST:-}"
GRAFANA_SMTP_USER="${GRAFANA_SMTP_USER:-}"
GRAFANA_SMTP_PASSWORD="${GRAFANA_SMTP_PASSWORD:-}"
GRAFANA_SMTP_FROM_ADDRESS="${GRAFANA_SMTP_FROM_ADDRESS:-}"
GRAFANA_SMTP_FROM_NAME="${GRAFANA_SMTP_FROM_NAME:-AirMonitor}"
GRAFANA_SMTP_ENV_FILE="${GRAFANA_SMTP_ENV_FILE:-/etc/airmonitor/grafana-smtp.env}"

log() {
  printf '\n==> %s\n' "$*"
}

fail() {
  printf '\nERROR: %s\n' "$*" >&2
  exit 1
}

log "Validating inputs"
if command -v grafana >/dev/null; then
  GRAFANA_CLI=(grafana cli)
elif [[ -x /usr/sbin/grafana ]]; then
  GRAFANA_CLI=(/usr/sbin/grafana cli)
elif command -v grafana-cli >/dev/null; then
  GRAFANA_CLI=(grafana-cli)
elif [[ -x /usr/sbin/grafana-cli ]]; then
  GRAFANA_CLI=(/usr/sbin/grafana-cli)
else
  fail "Grafana CLI not found; install Grafana first"
fi
command -v systemctl >/dev/null || fail "systemctl not found"
command -v python3 >/dev/null || fail "python3 is required"
[[ -d "$REPO_DIR/.git" ]] || fail "not a Git repository: $REPO_DIR"
[[ -f "$REPO_DIR/$DATASOURCE_SRC" ]] || fail "missing $DATASOURCE_SRC"
[[ -f "$REPO_DIR/$DASHBOARD_PROVIDER_SRC" ]] || fail "missing $DASHBOARD_PROVIDER_SRC"
[[ -f "$REPO_DIR/$PRINT_WINDOW_DASHBOARD_SRC" ]] || fail "missing $PRINT_WINDOW_DASHBOARD_SRC"
[[ -f "$REPO_DIR/$COMPARE_PRINTS_DASHBOARD_SRC" ]] || fail "missing $COMPARE_PRINTS_DASHBOARD_SRC"
[[ -f "$REPO_DIR/$DASHBOARD_GENERATOR" ]] || fail "missing dashboard generator: $REPO_DIR/$DASHBOARD_GENERATOR"
[[ -f "$REPO_DIR/$BRAND_ASSET" ]] || fail "missing brand asset: $REPO_DIR/$BRAND_ASSET"

cd "$REPO_DIR"

log "Installing SQLite datasource plugin"
sudo "${GRAFANA_CLI[@]}" --homepath "$GRAFANA_HOME" plugins install frser-sqlite-datasource || true

log "Configuring Grafana server defaults"
sudo install -d -o root -g grafana -m 0750 /etc/grafana/grafana.ini.d
sudo tee /etc/grafana/grafana.ini.d/airmonitor.ini >/dev/null <<EOF
[server]
http_addr = 127.0.0.1
http_port = 3000
domain = $GRAFANA_DOMAIN
root_url = $GRAFANA_ROOT_URL
serve_from_sub_path = true

[users]
default_theme = light
viewers_can_edit = false
home_page = /

[auth]
disable_login_form = false

[security]
cookie_secure = true
cookie_samesite = lax

[auth.anonymous]
enabled = true
org_name = $GRAFANA_ANONYMOUS_ORG_NAME
org_role = Viewer
hide_version = true

EOF

sudo chown root:grafana /etc/grafana/grafana.ini.d/airmonitor.ini
sudo chmod 0640 /etc/grafana/grafana.ini.d/airmonitor.ini

if [[ "$GRAFANA_SMTP_ENABLED" == "true" ]]; then
  [[ -n "$GRAFANA_SMTP_HOST" && -n "$GRAFANA_SMTP_USER" && -n "$GRAFANA_SMTP_PASSWORD" && -n "$GRAFANA_SMTP_FROM_ADDRESS" ]] || fail "SMTP is enabled but required settings are missing"
  [[ "$GRAFANA_SMTP_PASSWORD" != *$'\n'* ]] || fail "SMTP password cannot contain a newline"
  smtp_password="${GRAFANA_SMTP_PASSWORD//\\/\\\\}"
  smtp_password="${smtp_password//\"/\\\"}"
  # /etc/airmonitor is shared by services running as automation. Keep the
  # directory traversable; the SMTP secret itself remains root:grafana 0640.
  sudo install -d -o root -g root -m 0755 "$(dirname "$GRAFANA_SMTP_ENV_FILE")"
  {
    printf 'GF_SMTP_ENABLED=true\n'
    printf 'GF_SMTP_HOST=%s\n' "$GRAFANA_SMTP_HOST"
    printf 'GF_SMTP_USER=%s\n' "$GRAFANA_SMTP_USER"
    printf 'GF_SMTP_PASSWORD="%s"\n' "$smtp_password"
    printf 'GF_SMTP_FROM_ADDRESS=%s\n' "$GRAFANA_SMTP_FROM_ADDRESS"
    printf 'GF_SMTP_FROM_NAME=%s\n' "$GRAFANA_SMTP_FROM_NAME"
  } | sudo tee "$GRAFANA_SMTP_ENV_FILE" >/dev/null
  sudo chown root:grafana "$GRAFANA_SMTP_ENV_FILE"
  sudo chmod 0640 "$GRAFANA_SMTP_ENV_FILE"
fi

log "Configuring Grafana systemd environment overrides"
sudo install -d -o root -g root -m 0755 "$GRAFANA_SYSTEMD_DROPIN_DIR"
sudo tee "$GRAFANA_SYSTEMD_DROPIN_DIR/airmonitor.conf" >/dev/null <<EOF
[Service]
EnvironmentFile=-$GRAFANA_SMTP_ENV_FILE
Environment="GF_SERVER_HTTP_ADDR=127.0.0.1"
Environment="GF_SERVER_HTTP_PORT=3000"
Environment="GF_SERVER_DOMAIN=$GRAFANA_DOMAIN"
Environment="GF_SERVER_ROOT_URL=$GRAFANA_ROOT_URL"
Environment="GF_SERVER_SERVE_FROM_SUB_PATH=true"
Environment="GF_USERS_DEFAULT_THEME=light"
Environment="GF_USERS_VIEWERS_CAN_EDIT=false"
Environment="GF_USERS_HOME_PAGE=/"
Environment="GF_AUTH_DISABLE_LOGIN_FORM=false"
Environment="GF_SECURITY_COOKIE_SECURE=true"
Environment="GF_SECURITY_COOKIE_SAMESITE=lax"
Environment="GF_AUTH_ANONYMOUS_ENABLED=true"
Environment="GF_AUTH_ANONYMOUS_ORG_NAME=$GRAFANA_ANONYMOUS_ORG_NAME"
Environment="GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer"
Environment="GF_AUTH_ANONYMOUS_HIDE_VERSION=true"
EOF

log "Installing AirMonitor brand asset"
sudo install -o root -g grafana -m 0644 "$BRAND_ASSET" "$GRAFANA_HOME/public/img/airmonitor-brand-300.png"

if [[ -f "$DB_FILE" ]]; then
  log "Validating dashboard SQL against $DB_FILE"
  python3 "$DASHBOARD_GENERATOR" --validate-db "$DB_FILE"
fi

log "Generating dashboard artifact"
GRAFANA_DOMAIN="$GRAFANA_DOMAIN" python3 "$DASHBOARD_GENERATOR" "$DASHBOARD_SRC"

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
# airmonitor-print-window.json is a static, committed file (not python-generated
# like airmonitor-live.json), so its own "AirMonitor Status" link is filled in
# here from a placeholder rather than via status_page_url() in the generator.
if [[ -n "$GRAFANA_DOMAIN" && "$GRAFANA_DOMAIN" != "localhost" ]]; then
  STATUS_PAGE_URL="https://$GRAFANA_DOMAIN/"
else
  STATUS_PAGE_URL="/"
fi
tmp_print_window="$(mktemp)"
sed "s#__AIRMONITOR_STATUS_URL__#$STATUS_PAGE_URL#" "$PRINT_WINDOW_DASHBOARD_SRC" > "$tmp_print_window"
sudo install -o grafana -g grafana -m 0644 "$tmp_print_window" "$DASHBOARD_DIR/airmonitor-print-window.json"
rm -f "$tmp_print_window"
# airmonitor-compare-prints.json is also a static, committed file -- same
# placeholder substitution as airmonitor-print-window.json above.
tmp_compare_prints="$(mktemp)"
sed "s#__AIRMONITOR_STATUS_URL__#$STATUS_PAGE_URL#" "$COMPARE_PRINTS_DASHBOARD_SRC" > "$tmp_compare_prints"
sudo install -o grafana -g grafana -m 0644 "$tmp_compare_prints" "$DASHBOARD_DIR/airmonitor-compare-prints.json"
rm -f "$tmp_compare_prints"

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

if [[ -f "$GRAFANA_DB" ]] && command -v sqlite3 >/dev/null; then
  log "Clearing the organization dashboard-home override"
  org_name_sql="${GRAFANA_ANONYMOUS_ORG_NAME//\'/\'\'}"
  sudo sqlite3 "$GRAFANA_DB" "UPDATE preferences SET home_dashboard_id = 0 WHERE org_id = (SELECT id FROM org WHERE name = '$org_name_sql') AND user_id = 0 AND COALESCE(team_id, 0) = 0;"
fi

log "Restarting Grafana"
sudo systemctl daemon-reload
sudo systemctl restart "$GRAFANA_SERVICE"
sleep 3
systemctl --no-pager --full status "$GRAFANA_SERVICE"

log "Provisioned dashboard"
echo "${GRAFANA_ROOT_URL%/}/d/airmonitor-live/airmonitor-live"

echo
printf 'If your user was just added to %s, log out/in or run: newgrp %s\n' "$DATA_GROUP" "$DATA_GROUP"
