#!/usr/bin/env bash
set -euo pipefail

# Sets up Grafana's "Export as image" / panel-screenshot rendering via a
# remote grafana-image-renderer service running in Docker.
#
# Why Docker, and why not the grafana-cli plugin: the official
# grafana-image-renderer *plugin* bundle (installed via `grafana cli plugins
# install grafana-image-renderer`) only ships prebuilt binaries for
# linux-amd64/darwin/windows -- there is no arm64 build, so it cannot run
# directly inside Grafana on a Raspberry Pi. The renderer's *standalone
# service* image, by contrast, is published for linux/arm64 on Docker Hub,
# so running it as a separate HTTP service that Grafana calls out to
# (grafana.ini's [rendering] server_url) is the only way to get working
# image export on this hardware.

RENDERER_CONTAINER="${RENDERER_CONTAINER:-grafana-image-renderer}"
RENDERER_IMAGE="${RENDERER_IMAGE:-grafana/grafana-image-renderer:latest}"
RENDERER_PORT="${RENDERER_PORT:-8091}"
RENDERER_TOKEN_FILE="${RENDERER_TOKEN_FILE:-/etc/airmonitor/grafana-renderer.env}"
GRAFANA_SERVICE="${GRAFANA_SERVICE:-grafana-server}"
GRAFANA_SYSTEMD_DROPIN_DIR="${GRAFANA_SYSTEMD_DROPIN_DIR:-/etc/systemd/system/${GRAFANA_SERVICE}.service.d}"
GRAFANA_CALLBACK_URL="${GRAFANA_CALLBACK_URL:-http://localhost:3000/}"

log() {
  printf '\n==> %s\n' "$*"
}

fail() {
  printf '\nERROR: %s\n' "$*" >&2
  exit 1
}

command -v systemctl >/dev/null || fail "systemctl not found"

log "Installing Docker (for the Grafana remote image-rendering service)"
if ! command -v docker >/dev/null; then
  sudo apt-get update
  sudo apt-get install -y docker.io
fi
sudo systemctl enable --now docker >/dev/null

log "Generating (or reusing) the renderer auth token"
sudo install -d -o root -g root -m 0755 "$(dirname "$RENDERER_TOKEN_FILE")"
if [[ ! -f "$RENDERER_TOKEN_FILE" ]]; then
  token="$(openssl rand -hex 32)"
  printf 'GF_RENDERING_RENDERER_TOKEN=%s\n' "$token" | sudo tee "$RENDERER_TOKEN_FILE" >/dev/null
fi
# Owned root:grafana like the SMTP secret in install-grafana.sh -- root can
# always read it (needed below to pass the same value to the container),
# and Grafana's own EnvironmentFile= read only ever needs group access.
sudo chown root:grafana "$RENDERER_TOKEN_FILE"
sudo chmod 0640 "$RENDERER_TOKEN_FILE"
RENDERER_TOKEN="$(sudo grep '^GF_RENDERING_RENDERER_TOKEN=' "$RENDERER_TOKEN_FILE" | cut -d= -f2-)"
[[ -n "$RENDERER_TOKEN" ]] || fail "could not read renderer token from $RENDERER_TOKEN_FILE"

log "Pulling $RENDERER_IMAGE"
sudo docker pull "$RENDERER_IMAGE"

log "Starting the grafana-image-renderer container"
sudo docker rm -f "$RENDERER_CONTAINER" >/dev/null 2>&1 || true
# --network host: Grafana calls the renderer at localhost, and the renderer
# calls Grafana back at localhost (GRAFANA_CALLBACK_URL) -- both need to
# resolve to this host's real network namespace, not an isolated bridge one.
sudo docker run -d --name "$RENDERER_CONTAINER" --restart unless-stopped --network host \
  -e "SERVER_ADDR=:${RENDERER_PORT}" \
  -e "AUTH_TOKEN=${RENDERER_TOKEN}" \
  "$RENDERER_IMAGE"

log "Configuring Grafana to use the remote renderer"
sudo install -d -o root -g root -m 0755 "$GRAFANA_SYSTEMD_DROPIN_DIR"
sudo tee "$GRAFANA_SYSTEMD_DROPIN_DIR/airmonitor-renderer.conf" >/dev/null <<EOF
[Service]
EnvironmentFile=-$RENDERER_TOKEN_FILE
Environment="GF_RENDERING_SERVER_URL=http://localhost:${RENDERER_PORT}/render"
Environment="GF_RENDERING_CALLBACK_URL=${GRAFANA_CALLBACK_URL}"
EOF

log "Restarting Grafana"
sudo systemctl daemon-reload
sudo systemctl restart "$GRAFANA_SERVICE"
sleep 3
systemctl --no-pager --full status "$GRAFANA_SERVICE" | head -5

log "Verifying the renderer is reachable"
sleep 1
if curl -sf "http://127.0.0.1:${RENDERER_PORT}/healthz" >/dev/null; then
  echo "grafana-image-renderer is up on port ${RENDERER_PORT}"
else
  fail "grafana-image-renderer did not respond on port ${RENDERER_PORT} -- check: sudo docker logs $RENDERER_CONTAINER"
fi
