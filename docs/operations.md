# AirMonitor operations

## Health check

After install or update, run:

```bash
/opt/airmonitor/venv/bin/airmonitor-doctor
```

The command returns JSON and exits nonzero only for required failures. Optional integrations that are absent or stopped are reported as warnings.

Checks include:

- installed Python and AirMonitor versions
- SQLite integrity, schema version, and writability
- serial-device presence and access
- expected environment files without displaying secrets
- MQTT and Grafana TCP reachability
- expected systemd service states

For a development checkout:

```bash
. .venv/bin/activate
airmonitor-doctor --database /tmp/airmonitor-test.sqlite3 --no-systemd
```

## Update verification

Run these after pulling and installing a new build:

```bash
cd ~/airmonitor
git status --short
git log -1 --oneline

sudo /opt/airmonitor/venv/bin/pip install .
sudo systemctl daemon-reload
sudo systemctl restart \
  airmonitor-printer-mqtt.service \
  airmonitor.service \
  airmonitor-bento.service \
  airmonitor-levoit.service

/opt/airmonitor/venv/bin/airmonitor-doctor
systemctl --no-pager --full status \
  airmonitor-printer-mqtt.service \
  airmonitor.service \
  airmonitor-bento.service \
  airmonitor-levoit.service
```

## Stale-state rule

Printer or external-device state must include a timestamp and pass a configured freshness threshold before automation treats it as authoritative.

A stale `IDLE` state must not silently become a confident filter-off request. The shared freshness helper resolves stale input to `unknown` by default. A controller may choose a more conservative fallback, but it must record the reason.

## Filter decision record

Each filter control record should retain:

- manual mode
- automation request
- actual state
- effective state
- reason
- last update time

Manual `on` or `off` overrides automation until the filter is returned to `auto`.

## Branch and release workflow

Development branches should be merged through a pull request after CI passes. The installed appliance should normally track `main`, not an `agent/*` branch.
