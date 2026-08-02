#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DOMAIN="${DOMAIN:?DOMAIN must be set, e.g. DOMAIN=airmonitor.example.com bash tools/install-status-page.sh}"
LEGACY_GRAFANA_REDIRECT="${LEGACY_GRAFANA_REDIRECT:-false}"
NGINX_SRC="${NGINX_SRC:-nginx/airmonitor.conf.template}"
NGINX_DST="${NGINX_DST:-/etc/nginx/sites-available/airmonitor}"
LEGACY_NGINX_SRC="${LEGACY_NGINX_SRC:-nginx/airmonitor-legacy-grafana.conf.template}"
LEGACY_NGINX_DST="${LEGACY_NGINX_DST:-/etc/nginx/sites-available/airmonitor-legacy-grafana}"
OFFLINE_SRC="${OFFLINE_SRC:-web/offline.html}"
OFFLINE_DIR="${OFFLINE_DIR:-/var/www/airmonitor}"
CONTROL_HELPER_SRC="${CONTROL_HELPER_SRC:-tools/airmonitor-service-control}"
CONTROL_HELPER_DST="${CONTROL_HELPER_DST:-/usr/local/sbin/airmonitor-service-control}"
SUDOERS_SRC="${SUDOERS_SRC:-config/sudoers/airmonitor-status-control}"
SUDOERS_DST="${SUDOERS_DST:-/etc/sudoers.d/airmonitor-status-control}"
BUNDLE_HELPER_SRC="${BUNDLE_HELPER_SRC:-tools/airmonitor-backup-bundle}"
BUNDLE_HELPER_DST="${BUNDLE_HELPER_DST:-/usr/local/sbin/airmonitor-backup-bundle}"
BUNDLE_SUDOERS_SRC="${BUNDLE_SUDOERS_SRC:-config/sudoers/airmonitor-backup-bundle}"
BUNDLE_SUDOERS_DST="${BUNDLE_SUDOERS_DST:-/etc/sudoers.d/airmonitor-backup-bundle}"

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
[[ -f "$REPO_DIR/$BUNDLE_HELPER_SRC" ]] || { echo "ERROR: missing $BUNDLE_HELPER_SRC" >&2; exit 1; }
[[ -f "$REPO_DIR/$BUNDLE_SUDOERS_SRC" ]] || { echo "ERROR: missing $BUNDLE_SUDOERS_SRC" >&2; exit 1; }
command -v zip >/dev/null || { echo "ERROR: zip is required (should be installed by tools/install.sh)" >&2; exit 1; }

sudo visudo -cf "$REPO_DIR/$SUDOERS_SRC"
sudo install -o root -g root -m 0755 "$REPO_DIR/$CONTROL_HELPER_SRC" "$CONTROL_HELPER_DST"
sudo install -o root -g root -m 0440 "$REPO_DIR/$SUDOERS_SRC" "$SUDOERS_DST"

sudo visudo -cf "$REPO_DIR/$BUNDLE_SUDOERS_SRC"
sudo install -o root -g root -m 0755 "$REPO_DIR/$BUNDLE_HELPER_SRC" "$BUNDLE_HELPER_DST"
sudo install -o root -g root -m 0440 "$REPO_DIR/$BUNDLE_SUDOERS_SRC" "$BUNDLE_SUDOERS_DST"

sudo install -d -o root -g root -m 0755 "$(dirname "$NGINX_DST")" "$OFFLINE_DIR"

rendered="$(mktemp)"
trap 'rm -f "$rendered"' EXIT
sed "s/__DOMAIN__/$DOMAIN/g" "$REPO_DIR/$NGINX_SRC" > "$rendered"
sudo install -o root -g root -m 0644 "$rendered" "$NGINX_DST"
sudo ln -sfn "$NGINX_DST" /etc/nginx/sites-enabled/airmonitor

if [[ "$LEGACY_GRAFANA_REDIRECT" == "true" ]]; then
  [[ -f "$REPO_DIR/$LEGACY_NGINX_SRC" ]] || { echo "ERROR: missing $LEGACY_NGINX_SRC" >&2; exit 1; }
  sed "s/__DOMAIN__/$DOMAIN/g" "$REPO_DIR/$LEGACY_NGINX_SRC" > "$rendered"
  sudo install -o root -g root -m 0644 "$rendered" "$LEGACY_NGINX_DST"
  sudo ln -sfn "$LEGACY_NGINX_DST" "/etc/nginx/sites-enabled/airmonitor-legacy-grafana"
else
  sudo rm -f "$LEGACY_NGINX_DST" /etc/nginx/sites-enabled/airmonitor-legacy-grafana
fi

sudo install -o root -g root -m 0644 "$REPO_DIR/$OFFLINE_SRC" "$OFFLINE_DIR/airmonitor-offline.html"
sudo "$NGINX_BIN" -t
sudo systemctl reload nginx
