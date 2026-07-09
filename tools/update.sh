#!/usr/bin/env bash
set -euo pipefail

SERVICE="airmonitor.service"
APP_DIR="/opt/airmonitor"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$REPO_DIR"
echo "Updating repository: $REPO_DIR"
git pull --ff-only

echo "Installing package into $APP_DIR/venv"
sudo "$APP_DIR/venv/bin/pip" install --upgrade .

echo "Ensuring database directory exists"
sudo install -d -o automation -g automation -m 0755 /var/lib/airmonitor

echo "Installing systemd unit"
sudo install -o root -g root -m 0644 systemd/airmonitor.service /etc/systemd/system/$SERVICE
sudo systemctl daemon-reload

echo "Restarting $SERVICE"
sudo systemctl restart "$SERVICE"
systemctl --no-pager --full status "$SERVICE"
