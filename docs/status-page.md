# AirMonitor Status Page

The appliance landing page is served at `https://airmonitor.example.com/` by
`airmonitor-status.service`. It reads only normalized state produced by AirMonitor
services. It never opens serial ports, resolves sensor hardware, subscribes to printer
MQTT, or calls filter integrations.

The status service reads:

- latest SGX, SPS30, printer, and filter state from SQLite in read-only mode
- a fixed allowlist of systemd service states
- disk usage, database size, host uptime, and Linux thermal-zone temperature

Nginx sends only the exact `/` route, `/status-api`, and `/status-assets/` to the status
service. Existing Grafana paths continue to use Grafana, and the landing page links to the
light-theme kiosk dashboard. The `/grafana-signin` route clears the anonymous Grafana
session. Anonymous requests to `/` receive the appliance page, while requests carrying a
Grafana session cookie send Grafana's normal post-login `/` destination back to Grafana.
The stable `/status` route always serves the appliance page, including for signed-in users.

Install or refresh routing with:

```bash
bash tools/install-status-page.sh
```

The page refreshes every ten seconds. Sensor freshness is derived from persisted sample
timestamps. It is degraded after 90 seconds without a sample and offline when both sensor
streams are older than five minutes.
