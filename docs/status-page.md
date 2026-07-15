# AirMonitor Status Page

The appliance landing page is served at `https://airmonitor.example.com/` by
`airmonitor-status.service`. It reads only normalized state produced by AirMonitor
services. It never opens serial ports, resolves sensor hardware, subscribes to printer
MQTT, or calls filter integrations.

The status service reads:

- latest SGX, SPS30, printer, and filter state from SQLite in read-only mode
- a fixed allowlist of systemd service states
- disk usage, database size, host uptime, and Linux thermal-zone temperature

Nginx serves the landing page at `airmonitor.example.com` and proxies Grafana on the
separate `grafana.airmonitor.example.com` virtual host. This keeps Grafana sessions,
login redirects, and its `/` route independent from the appliance page. Old Grafana paths
on the appliance hostname redirect to the matching path on the Grafana hostname.

Install or refresh routing with:

```bash
bash tools/install-status-page.sh
```

The page refreshes every ten seconds. Sensor freshness is derived from persisted sample
timestamps. It is degraded after 90 seconds without a sample and offline when both sensor
streams are older than five minutes.
