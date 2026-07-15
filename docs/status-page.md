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

## Authentication and administration

Grafana is the single identity source for both hostnames. Nginx scopes Grafana's session
cookie to `.airmonitor.example.com`; the landing service validates that opaque cookie
against Grafana's loopback `/api/user` endpoint and never reads Grafana's user database or
stores passwords itself. Logged-out visitors retain full read-only appliance status.

Grafana server administrators receive service controls for the five AirMonitor collection
and automation services. Every control request requires the shared authenticated session,
an exact same-origin check, a custom CSRF header, and a fixed service/action allowlist. The
unprivileged status process can invoke only the root-owned
`/usr/local/sbin/airmonitor-service-control` helper through its dedicated sudoers rule.
Grafana, nginx, Mosquitto, and the status service cannot be controlled through this API.

## Password reset email

The landing page links to Grafana's password-reset workflow. Configure SMTP while running
the Grafana installer; the password is stored only in a root/Grafana-readable environment
file:

```bash
GRAFANA_SMTP_ENABLED=true \
GRAFANA_SMTP_HOST='smtp.example.com:587' \
GRAFANA_SMTP_USER='airmonitor@example.com' \
GRAFANA_SMTP_PASSWORD='app-password' \
GRAFANA_SMTP_FROM_ADDRESS='airmonitor@example.com' \
bash tools/install-grafana.sh
```
