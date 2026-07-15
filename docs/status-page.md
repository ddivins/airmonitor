# AirMonitor Status Page

The appliance landing page is served at `https://airmonitor.example.com/` by
`airmonitor-status.service`. It reads only normalized state produced by AirMonitor
services. It never opens serial ports, resolves sensor hardware, subscribes to printer
MQTT, or calls filter integrations.

The status service reads:

- latest SGX, SPS30, printer, and filter state from SQLite in read-only mode
- a fixed allowlist of systemd service states
- disk usage, database size, host uptime, and Linux thermal-zone temperature

Nginx serves the landing page at `airmonitor.example.com` and proxies Grafana beneath
`/grafana/` on that same hostname. The historical `grafana.airmonitor.example.com`
host redirects old bookmarks into the corresponding unified-app path.

Install or refresh routing with:

```bash
bash tools/install-status-page.sh
```

The page refreshes every ten seconds. Sensor freshness is derived from persisted sample
timestamps. It is degraded after 90 seconds without a sample and offline when both sensor
streams are older than five minutes.

## Authentication and administration

Grafana is the single identity source. Nginx makes its `/grafana/` session cookie available
at the appliance root; the landing service validates that opaque cookie
against Grafana's loopback `/api/user` endpoint and never reads Grafana's user database or
stores passwords itself. Logged-out visitors retain full read-only appliance status.

Grafana server administrators receive lifecycle controls for `airmonitor.target` and
individual controls for the AirMonitor collection and automation services. Every control
request requires the shared authenticated session,
an exact same-origin check, a custom CSRF header, and a fixed service/action allowlist. The
unprivileged status process can invoke only the root-owned
`/usr/local/sbin/airmonitor-service-control` helper through its dedicated sudoers rule.
Nginx and the status service cannot be controlled through this API.
Each service card also exposes the same full, unpaginated text returned by
`systemctl status --no-pager --full`; action results open that status output immediately.

The application target is listed first, followed by the view-only status-page service so
the UI cannot disable itself. Stopping `airmonitor.target` stops its sensor and automation
members but leaves the status page available to start them again. Grafana and Mosquitto expose restart-only controls; stop, enable, and disable are
rejected independently by both the HTTP policy and the privileged helper.

Grafana and the appliance landing page now share one origin. The provisioned dashboards
include an `AirMonitor Status` link back to the appliance root.

## Password reset email

The landing page links to Grafana's password-reset workflow. Configure SMTP while running
the Grafana installer; the password is stored only in a root/Grafana-readable environment
file. The shared `/etc/airmonitor` directory remains `root:root` mode `0755` so collection
services can read their own configuration, while `grafana-smtp.env` is `root:grafana`
mode `0640`:

```bash
GRAFANA_SMTP_ENABLED=true \
GRAFANA_SMTP_HOST='smtp.example.com:587' \
GRAFANA_SMTP_USER='airmonitor@example.com' \
GRAFANA_SMTP_PASSWORD='app-password' \
GRAFANA_SMTP_FROM_ADDRESS='airmonitor@example.com' \
bash tools/install-grafana.sh
```
