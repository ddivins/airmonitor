#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
GRAFANA_URL="${GRAFANA_URL:-http://127.0.0.1:3000}"
DASHBOARD_GENERATOR="${DASHBOARD_GENERATOR:-tools/generate-grafana-dashboard.py}"
DASHBOARD_UID="${DASHBOARD_UID:-airmonitor-live}"
DASHBOARD_FOLDER="${DASHBOARD_FOLDER:-AirMonitor}"
DASHBOARD_FOLDER_UID="${DASHBOARD_FOLDER_UID:-airmonitor}"
DS_NAME="${DS_NAME:-AirMonitor SQLite}"
DS_UID="${DS_UID:-airmonitor-sqlite}"
DS_TYPE="${DS_TYPE:-frser-sqlite-datasource}"
DS_PATH="${DS_PATH:-/var/lib/airmonitor/airmonitor.sqlite3}"

log() {
  printf '\n==> %s\n' "$*"
}

fail() {
  printf '\nERROR: %s\n' "$*" >&2
  exit 1
}

command -v curl >/dev/null || fail "curl is required"
command -v python3 >/dev/null || fail "python3 is required"
[[ -f "$REPO_DIR/$DASHBOARD_GENERATOR" ]] || fail "missing dashboard generator: $REPO_DIR/$DASHBOARD_GENERATOR"

if [[ -z "${GRAFANA_USER:-}" ]]; then
  read -rp "Grafana username [admin]: " GRAFANA_USER
  GRAFANA_USER="${GRAFANA_USER:-admin}"
fi
if [[ -z "${GRAFANA_PASSWORD:-}" ]]; then
  read -rsp "Grafana password: " GRAFANA_PASSWORD
  echo
fi
AUTH="$GRAFANA_USER:$GRAFANA_PASSWORD"

api() {
  local method="$1"
  local path="$2"
  local data_file="${3:-}"
  if [[ -n "$data_file" ]]; then
    curl -fsS -u "$AUTH" -H 'Content-Type: application/json' -X "$method" --data-binary "@$data_file" "$GRAFANA_URL$path"
  else
    curl -fsS -u "$AUTH" -H 'Content-Type: application/json' -X "$method" "$GRAFANA_URL$path"
  fi
}

log "Checking Grafana API"
api GET /api/health >/dev/null

log "Creating/updating datasource: $DS_NAME"
tmp_ds="$(mktemp)"
python3 - "$tmp_ds" "$DS_NAME" "$DS_UID" "$DS_TYPE" "$DS_PATH" <<'PY'
import json, sys
out, name, uid, typ, path = sys.argv[1:]
payload = {
    "name": name,
    "uid": uid,
    "type": typ,
    "access": "proxy",
    "isDefault": True,
    "jsonData": {"path": path},
}
open(out, "w").write(json.dumps(payload))
PY
if api GET "/api/datasources/uid/$DS_UID" >/dev/null 2>&1; then
  api PUT "/api/datasources/uid/$DS_UID" "$tmp_ds" >/dev/null
else
  api POST /api/datasources "$tmp_ds" >/dev/null
fi
rm -f "$tmp_ds"

log "Ensuring dashboard folder: $DASHBOARD_FOLDER"
tmp_folder="$(mktemp)"
python3 - "$tmp_folder" "$DASHBOARD_FOLDER_UID" "$DASHBOARD_FOLDER" <<'PY'
import json, sys
out, uid, title = sys.argv[1:]
open(out, "w").write(json.dumps({"uid": uid, "title": title}))
PY
api POST /api/folders "$tmp_folder" >/dev/null 2>&1 || true
rm -f "$tmp_folder"

log "Generating dashboard"
tmp_generated="$(mktemp)"
python3 "$REPO_DIR/$DASHBOARD_GENERATOR" "$tmp_generated"

log "Importing dashboard via API: $DASHBOARD_UID"
tmp_dash="$(mktemp)"
python3 - "$tmp_generated" "$tmp_dash" "$DASHBOARD_FOLDER_UID" <<'PY'
import json, sys
src, out, folder_uid = sys.argv[1:]
dash = json.load(open(src))
dash["id"] = None
payload = {
    "dashboard": dash,
    "folderUid": folder_uid,
    "overwrite": True,
    "message": "Provisioned by AirMonitor",
}
open(out, "w").write(json.dumps(payload))
PY
api POST /api/dashboards/db "$tmp_dash" >/dev/null
rm -f "$tmp_dash" "$tmp_generated"

log "Done"
echo "$GRAFANA_URL/d/$DASHBOARD_UID/airmonitor-live"
