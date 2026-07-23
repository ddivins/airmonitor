# AirMonitor Status Page

The appliance landing page is served at `https://<DOMAIN>/` by `airmonitor-status.service`,
where `DOMAIN` is the value configured during installation (see
[Fresh Host Installation](install.md)). It reads only normalized state produced by AirMonitor
services. It never opens serial ports, resolves sensor hardware, subscribes to printer
MQTT, or calls filter integrations.

The status service reads:

- latest SGX, SPS30, printer, and filter state from SQLite in read-only mode
- a fixed allowlist of systemd service states
- disk usage, database size, host uptime, and Linux thermal-zone temperature

Nginx serves the landing page at `DOMAIN` and proxies Grafana beneath `/grafana/` on that
same hostname. Set `LEGACY_GRAFANA_REDIRECT=true` in `/etc/airmonitor/install.conf` to also
route a historical `grafana.DOMAIN` host into the corresponding unified-app path.

Install or refresh routing with:

```bash
DOMAIN=airmonitor.example.com bash tools/install-status-page.sh
```

`tools/install.sh` and `tools/update.sh` pass `DOMAIN` (and `LEGACY_GRAFANA_REDIRECT`)
automatically from `/etc/airmonitor/install.conf`; running the script directly requires
setting `DOMAIN` yourself.

The page refreshes every ten seconds. Sensor freshness is derived from persisted sample
timestamps. It is degraded after 90 seconds without a sample and offline when both sensor
streams are older than five minutes.

## Alerts page

`https://<DOMAIN>/alerts` shows currently open and recently resolved entries from the
`alert_events` table populated by `airmonitor-alerts` (see `docs/alerting.md`). It's the only
web UI view of alert state — previously the only way to see an active alert was the CLI or raw
SQL. Like the main landing page, it's read-only, unauthenticated, and refreshes automatically
(every 15 seconds).

Adding a new page here requires two things, not just new files: a route in
`StatusHandler.do_GET`/`STATIC_FILENAMES` (`src/airmonitor/status_web.py`), and an explicit
`location` block in `nginx/airmonitor.conf.template`. The template's trailing catch-all
(`location / { return 301 /grafana$request_uri; }`) means an unmatched path silently redirects
to Grafana instead of 404ing, which makes a missing nginx route easy to overlook.

## Backup and update visibility

The "Appliance" panel on the landing page also shows:

- **Last backup / Backups kept** — reads `airmonitor.backup.list_backups()` directly (no
  network, no subprocess), so a silently-broken `airmonitor-backup.timer` is visible without
  running `airmonitor-doctor`. A backup older than 36 hours (1.5x the daily schedule, so a
  single delayed `RandomizedDelaySec` run doesn't false-flag) is shown in amber.
- **Update** — compares the commit `tools/update.sh` last recorded as installed
  (`/var/lib/airmonitor/update-state/installed-commit`) against upstream's current tip via an
  anonymous `git ls-remote` over HTTPS. This deliberately avoids a real `git fetch`: it needs
  neither write access to the checkout's `.git` (a fetch does) nor stored credentials for a
  public repo, so it can run as the unprivileged status-service user rather than needing the
  checkout-owner permissions that `airmonitor update` requires (see `cli.resolve_repo_dir`).
  The result is cached in-process for an hour (`AIRMONITOR_UPDATE_CHECK_TTL_SECONDS`) so the
  network call doesn't happen on every page load.

Both read from `/var/lib/airmonitor/backups` and `/var/lib/airmonitor/update-state` by default;
override with `AIRMONITOR_BACKUP_DIR` / `AIRMONITOR_UPDATE_STATE_DIR` in
`/etc/airmonitor/airmonitor.env` if needed. Neither is required for day-to-day operation — both
degrade to an informational "unknown" state rather than breaking the rest of the page.

**Known current limitation:** the `github.com/ddivins/airmonitor` repo is private as of this
writing, and anonymous `git ls-remote` genuinely cannot read a private repo — so until the repo
is made public, the "Update" indicator will always show `could not reach upstream repository`.
This isn't a bug in the check; it's expected until the repo's visibility changes. Confirmed by
testing `git ls-remote` with credential helpers disabled, and by GitHub's API returning `404`
(not `403`) for an unauthenticated request to the repo, both of which are private-repo behavior.

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

The print-export service is also shown in service status and exposes a restart-only
administrator control. It remains isolated from the status process so report generation
cannot block landing-page refreshes.

Grafana and the appliance landing page now share one origin. The provisioned dashboards
include an `AirMonitor Status` link back to the appliance root. Because Grafana runs
sub-pathed (`serve_from_sub_path = true`), that link -- and the dashboards' logo banner
described below -- must be a fully-qualified `https://<domain>/` URL rather than a
root-relative `/`: Grafana rewrites relative dashboard links to be relative to its own
`/grafana/` sub-path, which otherwise lands you back on Grafana instead of the status
page. `generate-grafana-dashboard.py`'s `status_page_url()` builds that absolute URL
from `GRAFANA_DOMAIN` (threaded to it by `tools/update.sh`'s `install-grafana.sh` call),
falling back to `/` only when no real domain is configured (local generation,
`--validate-db`).

Every AirMonitor dashboard (`airmonitor-live`, `airmonitor-print-window`) opens with a
full-width logo banner as its first panel, matching the clickable-logo header the
status_static pages already use -- clicking the logo returns to the status page from
any dashboard, the same navigation available everywhere else. `airmonitor-print-window.json`
is a static committed file rather than python-generated, so its banner (and its own
`AirMonitor Status` link) carry an `__AIRMONITOR_STATUS_URL__` placeholder that
`tools/install-grafana.sh` substitutes with the same absolute-or-`/` logic at install time.

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
