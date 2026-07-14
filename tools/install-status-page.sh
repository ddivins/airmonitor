#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
NGINX_SRC="${NGINX_SRC:-nginx/airmonitor.conf}"
NGINX_DST="${NGINX_DST:-/etc/nginx/sites-available/airmonitor}"
OFFLINE_SRC="${OFFLINE_SRC:-web/offline.html}"
OFFLINE_DIR="${OFFLINE_DIR:-/var/www/airmonitor}"

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

sudo install -d -o root -g root -m 0755 "$(dirname "$NGINX_DST")" "$OFFLINE_DIR"
sudo install -o root -g root -m 0644 "$REPO_DIR/$NGINX_SRC" "$NGINX_DST"
sudo install -o root -g root -m 0644 "$REPO_DIR/$OFFLINE_SRC" "$OFFLINE_DIR/airmonitor-offline.html"
sudo ln -sfn "$NGINX_DST" /etc/nginx/sites-enabled/airmonitor
sudo "$NGINX_BIN" -t
sudo systemctl reload nginx
