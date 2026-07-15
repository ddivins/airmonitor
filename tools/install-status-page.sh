#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
NGINX_SRC="${NGINX_SRC:-nginx/airmonitor.conf}"
NGINX_DST="${NGINX_DST:-/etc/nginx/sites-available/airmonitor}"
OFFLINE_SRC="${OFFLINE_SRC:-web/offline.html}"
OFFLINE_DIR="${OFFLINE_DIR:-/var/www/airmonitor}"
CONTROL_HELPER_SRC="${CONTROL_HELPER_SRC:-tools/airmonitor-service-control}"
CONTROL_HELPER_DST="${CONTROL_HELPER_DST:-/usr/local/sbin/airmonitor-service-control}"
SUDOERS_SRC="${SUDOERS_SRC:-config/sudoers/airmonitor-status-control}"
SUDOERS_DST="${SUDOERS_DST:-/etc/sudoers.d/airmonitor-status-control}"

if command -v nginx >/dev/null; then
  NGINX_BIN="$(command -v nginx)"
elif [[ -x /usr/sbin/nginx ]]; then
  NGINX_BIN=/usr/sbin/nginx
else
  echo "ERROR: nginx is required" >&2
  exit 1
fi
[[ -f "$REPO_DIR/$NGINX_SRC" ]] || { echo "ERROR: missing $NGINX_SRC" >&2; exit 1; }
[[ -f "$REPO_DIR/$OFFLINE_SRC" ]] || { echo "ERROR: missing $OFFLINE_SRC" >&2; exit 1; }
[[ -f "$REPO_DIR/$CONTROL_HELPER_SRC" ]] || { echo "ERROR: missing $CONTROL_HELPER_SRC" >&2; exit 1; }
[[ -f "$REPO_DIR/$SUDOERS_SRC" ]] || { echo "ERROR: missing $SUDOERS_SRC" >&2; exit 1; }

sudo visudo -cf "$REPO_DIR/$SUDOERS_SRC"
sudo install -o root -g root -m 0755 "$REPO_DIR/$CONTROL_HELPER_SRC" "$CONTROL_HELPER_DST"
sudo install -o root -g root -m 0440 "$REPO_DIR/$SUDOERS_SRC" "$SUDOERS_DST"

sudo install -d -o root -g root -m 0755 "$(dirname "$NGINX_DST")" "$OFFLINE_DIR"
sudo install -o root -g root -m 0644 "$REPO_DIR/$NGINX_SRC" "$NGINX_DST"
sudo install -o root -g root -m 0644 "$REPO_DIR/$OFFLINE_SRC" "$OFFLINE_DIR/airmonitor-offline.html"
sudo ln -sfn "$NGINX_DST" /etc/nginx/sites-enabled/airmonitor
sudo "$NGINX_BIN" -t
sudo systemctl reload nginx
