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

Every AirMonitor dashboard (`airmonitor-live`, `airmonitor-print-window`,
`airmonitor-compare-prints`) opens with a full-width logo banner as its first panel,
matching the clickable-logo header the status_static pages already use -- clicking the
logo returns to the status page from any dashboard, the same navigation available
everywhere else. `airmonitor-print-window.json` and `airmonitor-compare-prints.json` are
static committed files rather than python-generated, so their banners (and their own
`AirMonitor Status` links) carry an `__AIRMONITOR_STATUS_URL__` placeholder that
`tools/install-grafana.sh` substitutes with the same absolute-or-`/` logic at install time.

### Comparing prints

`airmonitor-compare-prints` picks up where `airmonitor-print-window`'s single-print view
leaves off: four independent print-select variables (`print_a`..`print_d`, each the same
query as `print-window`'s own `print_id`) feed a summary table (one row per slot: filament,
duration, peak VOC, peak PM2.5, ...) plus VOC/PM2.5/temperature charts overlaying all four.
Grafana's variable bar has no native "add another" control, so there's no dedicated button
for this -- Print A and B are the two you're expected to fill in, and C/D simply start
blank; every query already skips a blank slot cleanly (an empty `CAST('' AS INTEGER)` just
matches no print), so leaving them unset reads as "comparing two" and filling one in is
exactly the same action as picking A or B. Each print-select query's own result must stay
exactly two columns (`__text`, `__value`) -- a query variable returning more fields breaks
Grafana's variable parsing outright ("Received more than two (N) fields"), which in turn
corrupts the actual selected print id downstream. An attempt to add an explicit "None" choice
by unioning in extra sort/ordering columns hit exactly this and was reverted; a shorter,
truncated label was tried separately and also reverted (saved width, but made prints harder
to tell apart at a glance). Grafana still wraps the pickers onto multiple rows if the browser
is too narrow, since dashboard JSON has no way to force a fixed layout for the variable bar
the way panels have `gridPos`.

A fifth variable, `window_minutes` (15/30/60/90/120, default 30), controls how much time
before/after each print's own start/end is included -- widen it to see a longer post-print
recovery tail, or narrow it to focus tightly on the print itself. Every query builds its
`datetime()` modifier dynamically (`'-' || $window_minutes || ' minutes'`) instead of a
hardcoded `'-30 minutes'`, relying on SQLite's implicit numeric-to-text coercion in `||`.
`airmonitor-print-window.json` got the same variable, applied to all five panels that use a
pre/post window there (three charts plus two summary tables) -- its VOC panel title also
interpolates `${window_minutes}` directly rather than hardcoding "30".

Each overlay chart's `time_bucket` rounds to whole minutes, not the original one decimal
place (6-second precision). Sensors sample roughly every 10 seconds, so 6-second buckets were
barely coarser than raw sample spacing -- a multi-hour print rendered thousands of points into
a chart a few hundred pixels wide, which showed up live as a moire/banding pattern on the
area-filled line (a ~5 hour print with ~1,755 raw VOC samples was the case that surfaced it).
Whole-minute buckets cut that by roughly 6x. The existing outer
`MAX(CASE WHEN slot = ... THEN value END)` pivot already collapses multiple raw samples
sharing a bucket correctly on its own, so widening the bucket was sufficient by itself --
no separate aggregation layer was needed. `duration_min` (the summary table's print-length
column) is a different, unrelated computation and keeps its own decimal precision.

The three overlay charts also mark where each print actually started and stopped, so the
pre/post buffer around it is visually distinguishable from the print itself. Elapsed-time
alignment means every compared print's own start is always at elapsed minute 0 -- one shared
"Print start" line covers all of them -- but each print's own end differs (different
durations), so that's one column per slot (`Print A end` .. `Print D end`), each a synthetic
row injected into the same `UNION ALL` at that print's own duration in minutes. Grafana's
native annotations don't apply to this panel: they anchor to a real time axis, and this one
is deliberately elapsed minutes, not epoch time (the same reason `timeColumns` stays empty --
see the regression test above). Instead each marker column is a spike (value `1` at exactly
one elapsed-minute position, `NULL` everywhere else) rendered as a thin bar on its own hidden
0-1 axis via a field override (`custom.axisPlacement: hidden`, `min`/`max` forced to 0/1) --
a full-height vertical line regardless of the real VOC/PM/temperature series' own Y-scale,
without needing Grafana's time-based annotation system at all.

The charts can't just plot real timestamps -- two prints being compared happened at
different wall-clock times, so their curves would never overlap. Each chart's query instead
computes `(sampled_at - print's own started_at)` in minutes per print, `UNION ALL`s the four
slots together, and pivots into up to four named columns via
`MAX(CASE WHEN slot = 'a' THEN value END) AS "${print_a:text}"` (one column per slot,
aliased to the selected print's own label). This reuses two mechanisms already proven
elsewhere in this codebase rather than anything exotic: "one query column = one series" (the
same mechanism the `airmonitor-live` temperature/humidity/chamber panel already relies on),
and Grafana's `${var:text}` interpolation for a human-readable series name. The `trend` panel
type (not `timeseries`) is what allows a non-wall-clock numeric axis at all.

`sps30_samples` has no `print_id` column -- the SPS30 logger never associates samples with a
print -- so its PM2.5 queries correlate by time-range overlap against the print's own
`started_at`/`ended_at` instead, the same convention `airmonitor-print-window`'s own PM panel
already uses.

Grafana's own built-in pages -- `/grafana/dashboards`, `/grafana/explore`, the login
screen, and so on -- can't take a custom dashboard panel, so they don't get the banner
from a dashboard JSON file. Instead, `nginx/airmonitor.conf.template`'s `/grafana/` and
`/grafana/login` locations use `sub_filter` to inject the same clickable logo (and a
small dedicated stylesheet, `grafana-banner.css`) directly into Grafana's served HTML,
immediately before `<div id="reactRoot"></div>` -- Grafana's own SPA mount point, which
its React app only ever manages the inside of. A sibling injected right before it
survives every client-side route change with no per-page work, so the banner appears on
every Grafana page without needing one dashboard JSON edit per page. This relies on
Grafana's HTML shell keeping a `</head>` tag and that `reactRoot` id -- reasonably stable
structural anchors, but not a documented/versioned Grafana contract, so a future Grafana
upgrade could in principle stop matching (the banner would simply stop appearing, not
break anything else). `proxy_set_header Accept-Encoding "";` is required on both
locations so `sub_filter` sees Grafana's plain HTML rather than gzip-compressed bytes it
can't pattern-match against -- the same fix the `/grafana/login` JSON rewrite already
needed. `grafana-banner.css` is deliberately its own file, not appended to `style.css`:
that file's bare `body`/`*` selectors would repaint Grafana's own background and text
color if loaded on a Grafana page.

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
