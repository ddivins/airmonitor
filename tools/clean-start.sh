#!/usr/bin/env bash
set -euo pipefail

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${BACKUP_DIR:-/root/airmonitor-backup}"
LEGACY_OPT="${LEGACY_OPT:-/opt/airmonitor-old}"
LEGACY_HOME="${LEGACY_HOME:-$HOME/legacy-airmonitor}"

log() {
  printf '\n==> %s\n' "$*"
}

log "Backing up local AirMonitor files"
sudo mkdir -p "$BACKUP_DIR"
sudo cp -a /etc/airmonitor.env "$BACKUP_DIR/" 2>/dev/null || true
sudo cp -a /etc/bambu-bento.env "$BACKUP_DIR/" 2>/dev/null || true
sudo cp -a /etc/levoit-filter.env "$BACKUP_DIR/" 2>/dev/null || true
sudo cp -a /var/lib/airmonitor "$BACKUP_DIR/" 2>/dev/null || true

log "Stopping old services"
sudo systemctl stop airmonitor.service bambu-bento.service levoit-filter.service printer-mqtt-service.service 2>/dev/null || true
sudo systemctl disable airmonitor.service bambu-bento.service levoit-filter.service printer-mqtt-service.service 2>/dev/null || true

log "Removing old systemd units"
sudo rm -f /etc/systemd/system/airmonitor.service
sudo rm -f /etc/systemd/system/bambu-bento.service
sudo rm -f /etc/systemd/system/levoit-filter.service
sudo rm -f /etc/systemd/system/printer-mqtt-service.service
sudo systemctl daemon-reload
sudo systemctl reset-failed

log "Moving old /opt installs aside"
sudo mkdir -p "$LEGACY_OPT"
sudo mv /opt/airmonitor "$LEGACY_OPT/airmonitor.$STAMP" 2>/dev/null || true
sudo mv /opt/bambu-bento "$LEGACY_OPT/bambu-bento.$STAMP" 2>/dev/null || true
sudo mv /opt/levoit-filter "$LEGACY_OPT/levoit-filter.$STAMP" 2>/dev/null || true
sudo mv /opt/printer-mqtt-service "$LEGACY_OPT/printer-mqtt-service.$STAMP" 2>/dev/null || true

log "Moving old checkout directories aside"
mkdir -p "$LEGACY_HOME"
mv "$HOME/airmonitor" "$LEGACY_HOME/airmonitor.$STAMP" 2>/dev/null || true
mv "$HOME/bento-box" "$LEGACY_HOME/bento-box.$STAMP" 2>/dev/null || true
mv "$HOME/levoit-filter" "$LEGACY_HOME/levoit-filter.$STAMP" 2>/dev/null || true
mv "$HOME/printer-mqtt-service" "$LEGACY_HOME/printer-mqtt-service.$STAMP" 2>/dev/null || true

log "Clean start prepared"
echo "Backups: $BACKUP_DIR"
echo "Legacy /opt: $LEGACY_OPT"
echo "Legacy home: $LEGACY_HOME"
