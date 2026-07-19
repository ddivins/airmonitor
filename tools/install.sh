#!/usr/bin/env bash
set -euo pipefail
umask 077

MODE=core
NON_INTERACTIVE=false
MIGRATE_FROM=""
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
APP_DIR="${APP_DIR:-/opt/airmonitor}"
CONFIG_DIR="${CONFIG_DIR:-/etc/airmonitor}"
DATA_DIR="${DATA_DIR:-/var/lib/airmonitor}"
SERVICE_USER="${SERVICE_USER:-automation}"
SERVICE_GROUP="${SERVICE_GROUP:-automation}"
AIRMONITOR_DOMAIN="airmonitor.example.com"
GRAFANA_DOMAIN="grafana.airmonitor.example.com"
EXPECTED_CP2105_SERIAL="${EXPECTED_CP2105_SERIAL:-00B9A86D}"
CERTBOT_CREDENTIALS="${AIRMONITOR_CERTBOT_CLOUDFLARE_CREDENTIALS:-}"
CERTBOT_EMAIL="${AIRMONITOR_CERT_EMAIL:-}"
MIGRATION_STAGE=""
MIGRATION_SOURCE_STOPPED=false

usage() {
  cat <<'EOF'
Usage: bash tools/install.sh [OPTIONS]

Fresh-host installer for Debian/Raspberry Pi OS.

Options:
  --core                    Install AirMonitor, Mosquitto, and sensor services (default)
  --full                    Also install Grafana, nginx, Certbot, and Cloudflare DNS support
  --migrate-from USER@HOST  Import AirMonitor config/data and Grafana DB from an old appliance
  --non-interactive         Never open an editor or prompt; report unfinished configuration
  -h, --help                Show this help

Optional environment for unattended certificate issuance in --full mode:
  AIRMONITOR_CERTBOT_CLOUDFLARE_CREDENTIALS=/root/.secrets/cloudflare.ini
  AIRMONITOR_CERT_EMAIL=admin@example.com
EOF
}

log() {
  printf '\n==> %s\n' "$*"
}

warn() {
  printf 'WARNING: %s\n' "$*" >&2
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --core) MODE=core ;;
    --full) MODE=full ;;
    --migrate-from)
      [[ $# -ge 2 ]] || fail "--migrate-from requires USER@HOST"
      MIGRATE_FROM="$2"
      shift
      ;;
    --non-interactive) NON_INTERACTIVE=true ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown option: $1" ;;
  esac
  shift
done

cleanup() {
  if [[ "$MIGRATION_SOURCE_STOPPED" == "true" && -n "$MIGRATE_FROM" ]]; then
    ssh "$MIGRATE_FROM" "sudo systemctl start airmonitor.target grafana-server 2>/dev/null || true" || true
  fi
  if [[ -n "$MIGRATION_STAGE" && -d "$MIGRATION_STAGE" ]]; then
    rm -rf "$MIGRATION_STAGE"
  fi
}
trap cleanup EXIT

[[ $EUID -ne 0 ]] || fail "run as the normal administrative user, not root"
command -v sudo >/dev/null || fail "sudo is required"
[[ -d "$REPO_DIR/.git" ]] || fail "not a Git repository: $REPO_DIR"
[[ -f "$REPO_DIR/tools/update.sh" ]] || fail "missing tools/update.sh"

if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  case "${ID:-} ${ID_LIKE:-}" in
    *debian*) ;;
    *) fail "supported hosts are Raspberry Pi OS, Debian, or Debian-derived systems" ;;
  esac
else
  fail "cannot identify the operating system"
fi

case "$(uname -m)" in
  aarch64|armv7l) ;;
  *) warn "$(uname -m) is supported for testing but is not the normal Raspberry Pi target" ;;
esac

log "Acquiring administrative access"
sudo -v

install_packages() {
  local packages=(
    ca-certificates curl git python3 python3-pip python3-venv sqlite3
    mosquitto mosquitto-clients udev
  )
  if [[ "$MODE" == "full" ]]; then
    packages+=(apt-transport-https certbot gnupg nginx python3-certbot-dns-cloudflare wget)
  fi
  log "Installing host packages"
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages[@]}"
  sudo systemctl enable --now mosquitto >/dev/null
}

ensure_service_account() {
  log "Ensuring service account exists"
  if ! getent group "$SERVICE_GROUP" >/dev/null; then
    sudo addgroup --system "$SERVICE_GROUP"
  fi
  if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    sudo useradd --system --gid "$SERVICE_GROUP" --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
  fi
  sudo usermod -aG dialout "$SERVICE_USER"
}

ensure_virtualenv() {
  log "Ensuring application virtual environment exists"
  sudo install -d -o root -g root -m 0755 "$APP_DIR"
  if [[ ! -x "$APP_DIR/venv/bin/python" ]]; then
    sudo python3 -m venv "$APP_DIR/venv"
  fi
  sudo "$APP_DIR/venv/bin/python" -m pip install --upgrade pip
  "$APP_DIR/venv/bin/python" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' \
    || fail "AirMonitor requires Python 3.11 or newer"
}

backup_existing() {
  local path="$1"
  if sudo test -e "$path"; then
    sudo cp -a "$path" "$path.bak.$(date +%Y%m%d-%H%M%S)"
  fi
}

migrate_from_old_host() {
  [[ -n "$MIGRATE_FROM" ]] || return 0
  command -v ssh >/dev/null || fail "ssh is required for --migrate-from"
  log "Importing appliance state from $MIGRATE_FROM"
  MIGRATION_STAGE="$(mktemp -d)"
  local archive="$MIGRATION_STAGE/airmonitor-migration.tar"
  warn "the source AirMonitor and Grafana services will pause briefly for a consistent database copy"
  ssh "$MIGRATE_FROM" "sudo systemctl stop airmonitor.target grafana-server 2>/dev/null || true"
  MIGRATION_SOURCE_STOPPED=true
  if ! ssh "$MIGRATE_FROM" \
    "sudo tar -C / -cf - --ignore-failed-read etc/airmonitor var/lib/airmonitor/airmonitor.sqlite3 var/lib/grafana/grafana.db" \
    >"$archive"; then
    ssh "$MIGRATE_FROM" "sudo systemctl start airmonitor.target grafana-server 2>/dev/null || true" || true
    MIGRATION_SOURCE_STOPPED=false
    fail "migration archive failed; source services were restarted"
  fi
  ssh "$MIGRATE_FROM" "sudo systemctl start airmonitor.target grafana-server 2>/dev/null || true"
  MIGRATION_SOURCE_STOPPED=false
  tar -C "$MIGRATION_STAGE" -xf "$archive"

  sudo install -d -o root -g root -m 0755 "$CONFIG_DIR"
  if [[ -d "$MIGRATION_STAGE/etc/airmonitor" ]]; then
    while IFS= read -r -d '' source; do
      local name destination mode
      name="$(basename "$source")"
      destination="$CONFIG_DIR/$name"
      mode=0600
      [[ "$name" == "hardware.yaml" || "$name" == "filament-policy.yaml" ]] && mode=0644
      backup_existing "$destination"
      sudo install -o root -g root -m "$mode" "$source" "$destination"
    done < <(find "$MIGRATION_STAGE/etc/airmonitor" -maxdepth 1 -type f -print0)
  fi

  if [[ -f "$MIGRATION_STAGE/var/lib/airmonitor/airmonitor.sqlite3" ]]; then
    sudo install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0755 "$DATA_DIR"
    backup_existing "$DATA_DIR/airmonitor.sqlite3"
    sudo install -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0640 \
      "$MIGRATION_STAGE/var/lib/airmonitor/airmonitor.sqlite3" "$DATA_DIR/airmonitor.sqlite3"
  fi

  if [[ "$MODE" == "full" && -f "$MIGRATION_STAGE/var/lib/grafana/grafana.db" ]]; then
    sudo install -d -o grafana -g grafana -m 0750 /var/lib/grafana
    backup_existing /var/lib/grafana/grafana.db
    sudo install -o grafana -g grafana -m 0640 \
      "$MIGRATION_STAGE/var/lib/grafana/grafana.db" /var/lib/grafana/grafana.db
  fi
}

install_config_templates() {
  log "Installing missing configuration templates"
  sudo install -d -o root -g root -m 0755 "$CONFIG_DIR"
  local name source destination mode
  for name in sgx-voc sps30 printer-mqtt bento levoit; do
    source="$REPO_DIR/config/env/$name.env.example"
    destination="$CONFIG_DIR/$name.env"
    mode=0600
    if ! sudo test -e "$destination"; then
      sudo install -o root -g root -m "$mode" "$source" "$destination"
      echo "Created $destination"
    else
      echo "Preserving $destination"
    fi
  done
}

validate_cp2105() {
  log "Checking CP2105 hardware identity"
  local found=() device serial
  shopt -s nullglob
  for device in /dev/ttyUSB*; do
    serial="$(udevadm info -q property -n "$device" 2>/dev/null | sed -n 's/^ID_SERIAL_SHORT=//p' | head -1)"
    [[ -n "$serial" ]] && found+=("$serial")
  done
  shopt -u nullglob
  if [[ ${#found[@]} -eq 0 ]]; then
    warn "no USB serial adapter is connected; hardware aliases cannot yet be verified"
    return 0
  fi
  for serial in "${found[@]}"; do
    [[ "$serial" == "$EXPECTED_CP2105_SERIAL" ]] && return 0
  done
  fail "connected USB serial adapter does not match expected CP2105 serial $EXPECTED_CP2105_SERIAL; update config/udev/99-airmonitor-serial.rules intentionally before installing"
}

install_grafana_package() {
  [[ "$MODE" == "full" ]] || return 0
  if command -v grafana >/dev/null || [[ -x /usr/sbin/grafana ]]; then
    return 0
  fi
  log "Installing Grafana OSS from the official APT repository"
  sudo install -d -o root -g root -m 0755 /etc/apt/keyrings
  sudo wget -q -O /etc/apt/keyrings/grafana.asc https://apt.grafana.com/gpg-full.key
  sudo chmod 0644 /etc/apt/keyrings/grafana.asc
  echo "deb [signed-by=/etc/apt/keyrings/grafana.asc] https://apt.grafana.com stable main" \
    | sudo tee /etc/apt/sources.list.d/grafana.list >/dev/null
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y grafana
  sudo systemctl enable grafana-server >/dev/null
}

certificate_exists() {
  local domain="$1"
  sudo test -s "/etc/letsencrypt/live/$domain/fullchain.pem" \
    && sudo test -s "/etc/letsencrypt/live/$domain/privkey.pem"
}

obtain_certificates_if_configured() {
  [[ "$MODE" == "full" ]] || return 0
  if certificate_exists "$AIRMONITOR_DOMAIN" && certificate_exists "$GRAFANA_DOMAIN"; then
    return 0
  fi
  if [[ -z "$CERTBOT_CREDENTIALS" || -z "$CERTBOT_EMAIL" ]]; then
    warn "TLS certificates are missing; nginx routing will remain disabled"
    warn "set AIRMONITOR_CERTBOT_CLOUDFLARE_CREDENTIALS and AIRMONITOR_CERT_EMAIL, then rerun --full"
    return 0
  fi
  sudo test -s "$CERTBOT_CREDENTIALS" || fail "Cloudflare credentials file does not exist: $CERTBOT_CREDENTIALS"
  local permissions
  permissions="$(sudo stat -c '%a' "$CERTBOT_CREDENTIALS")"
  [[ "$permissions" == "600" ]] || fail "Cloudflare credentials must have mode 600: $CERTBOT_CREDENTIALS"
  local domain
  for domain in "$AIRMONITOR_DOMAIN" "$GRAFANA_DOMAIN"; do
    if ! certificate_exists "$domain"; then
      log "Obtaining certificate for $domain"
      sudo certbot certonly --non-interactive --agree-tos --email "$CERTBOT_EMAIL" \
        --dns-cloudflare --dns-cloudflare-credentials "$CERTBOT_CREDENTIALS" \
        --dns-cloudflare-propagation-seconds 30 -d "$domain"
    fi
  done
}

configuration_incomplete() {
  sudo grep -Eq '^(PRINTER_HOST=192\.168\.3\.x|PRINTER_SERIAL=YOUR_|PRINTER_ACCESS_CODE=YOUR_)' \
    "$CONFIG_DIR/printer-mqtt.env"
}

offer_configuration_edit() {
  if ! configuration_incomplete; then
    return 0
  fi
  warn "Bambu printer configuration still contains template values"
  if [[ "$NON_INTERACTIVE" == "false" && -t 0 ]]; then
    read -r -p "Edit printer-mqtt.env now? [y/N] " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
      sudo "${EDITOR:-nano}" "$CONFIG_DIR/printer-mqtt.env"
    fi
  fi
}

run_update() {
  log "Installing AirMonitor application and services"
  local grafana=0
  [[ "$MODE" == "full" ]] && grafana=1
  INSTALL_STATUS_PAGE=0 INSTALL_GRAFANA="$grafana" RUN_DOCTOR=0 bash "$REPO_DIR/tools/update.sh"
}

enable_public_routing_if_ready() {
  [[ "$MODE" == "full" ]] || return 0
  if certificate_exists "$AIRMONITOR_DOMAIN" && certificate_exists "$GRAFANA_DOMAIN"; then
    log "Installing nginx public routing"
    bash "$REPO_DIR/tools/install-status-page.sh"
  else
    warn "public HTTPS was not enabled because one or both certificates are missing"
  fi
}

final_report() {
  local doctor_status=0
  if [[ -x "$APP_DIR/venv/bin/airmonitor-doctor" ]]; then
    log "Running post-install health diagnostics"
    sudo "$APP_DIR/venv/bin/airmonitor-doctor" || doctor_status=$?
  fi
  log "Installation summary"
  echo "Mode: $MODE"
  echo "Repository: $REPO_DIR"
  echo "Application: $APP_DIR"
  echo "Configuration: $CONFIG_DIR"
  echo "Database: $DATA_DIR/airmonitor.sqlite3"
  if configuration_incomplete; then
    echo "ACTION REQUIRED: configure $CONFIG_DIR/printer-mqtt.env"
  fi
  if sudo grep -Eq '^OUTLET_HOST=192\.0\.2\.20$' "$CONFIG_DIR/bento.env"; then
    echo "ACTION REQUIRED: configure $CONFIG_DIR/bento.env"
  fi
  if sudo grep -Eq '^(VESYNC_USERNAME=|VESYNC_PASSWORD=|LEVOIT_DEVICE_NAME=)$' "$CONFIG_DIR/levoit.env"; then
    echo "ACTION REQUIRED: configure $CONFIG_DIR/levoit.env"
  fi
  if [[ "$MODE" == "full" ]] && ! certificate_exists "$AIRMONITOR_DOMAIN"; then
    echo "ACTION REQUIRED: obtain the $AIRMONITOR_DOMAIN certificate and rerun --full"
  fi
  if [[ "$MODE" == "full" ]] && ! certificate_exists "$GRAFANA_DOMAIN"; then
    echo "ACTION REQUIRED: obtain the $GRAFANA_DOMAIN certificate and rerun --full"
  fi
  if [[ "$MODE" == "full" ]]; then
    echo "ACTION REQUIRED: change Grafana's initial admin password and configure SMTP for web password reset"
  fi
  echo "Check health: sudo $APP_DIR/venv/bin/airmonitor-doctor"
  echo "Check services: systemctl --no-pager --full status airmonitor.target"
  if [[ $doctor_status -ne 0 ]]; then
    echo "ACTION REQUIRED: airmonitor-doctor reported incomplete or unhealthy configuration (exit $doctor_status)"
  fi
}

install_packages
ensure_service_account
install_grafana_package
ensure_virtualenv
migrate_from_old_host
install_config_templates
validate_cp2105
offer_configuration_edit
run_update
obtain_certificates_if_configured
enable_public_routing_if_ready
final_report
