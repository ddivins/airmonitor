# Database backup and restore

## Automatic daily backups

`airmonitor-backup.timer` runs `airmonitor backup` once a day (with a random
delay of up to 10 minutes to avoid every appliance backing up at exactly
midnight). It uses SQLite's online backup API, which is WAL-safe and takes a
consistent snapshot without stopping any service, then gzip-compresses it to:

```text
/var/lib/airmonitor/backups/airmonitor-<UTC timestamp>.sqlite3.gz
```

## Retention policy

By default the last **14** backups are kept; older ones are deleted
automatically after each successful backup. At roughly one backup a day,
that's about two weeks of history. Override per run with `--retention`:

```bash
sudo -u automation /opt/airmonitor/venv/bin/airmonitor backup --retention 30
```

There is currently no separate long-term/offsite archival — backups live
only on the appliance's own disk. For anything you don't want to lose if the
SD card fails, copy backup files off the device yourself (e.g. `scp` or
`rsync` from `/var/lib/airmonitor/backups/`).

## Manual backup

```bash
sudo -u automation /opt/airmonitor/venv/bin/airmonitor backup
```

Prints the created path, its size, and any backups pruned by retention.

## Backup Now and Download backup bundle (status page)

Signed-in Grafana administrators see two buttons on the status page's
Appliance panel:

- **Backup now** starts `create_backup()` as a background job and returns
  immediately; the browser polls `/api/backup/status` (every ~1.5s) and
  updates in place until it's done. This runs in-process as the
  `automation` user the status service already runs as -- no elevated
  privilege needed for this one.
- **Download backup bundle** downloads a `.zip` containing everything a
  from-scratch restore onto new hardware needs: `/etc/airmonitor/`
  (install.conf and every `.env` secret), the Cloudflare DNS-01 credential
  at `/root/.secrets/cloudflare.ini`, the current Let's Encrypt certificates
  themselves (`/etc/letsencrypt/`, symlink structure preserved via `cp -a`
  and `zip -y` so certbot's own renewal bookkeeping keeps working after a
  restore), Grafana's own database, the most recent AirMonitor database
  backup on disk, and a `RESTORE.md` with the exact restore steps. Including
  the certs (only ~150KB) means `install.sh`'s `certificate_exists()` check
  finds them already in place and skips reissuing entirely -- faster
  restore, and one less dependency (Cloudflare's API, DNS propagation) on
  the critical path. If they've expired by the time of an actual restore,
  just delete `/etc/letsencrypt/` before running the installer and it
  issues fresh ones the normal way.

Backup Now and Download bundle are deliberately decoupled: downloading does
**not** take a fresh backup first, it only bundles whatever the latest one
already is (the daily timer's, or a prior Backup Now click). The page says
so next to the button, pointing at the "Last backup" age shown above it --
click Backup Now first if you want the bundle to include the latest data.

This split exists because `create_backup()` uses SQLite's online backup API
against a live, actively-written database -- measured at ~31s in production
under normal sensor write load and only getting slower (worse than
linearly, in fact, since a longer copy window gives concurrent writers more
chances to force retries) as the database grows. An earlier version of this
feature took a fresh backup as part of every download, which combined with
the zip step to occasionally exceed nginx's `proxy_read_timeout` and return
a 504 to the browser -- the backup had actually completed by then, just too
late for anyone to see the result. Running it as a background job the
browser polls for, rather than a single blocking HTTP request, is the only
approach that stays correct no matter how large the database eventually
gets; bundling stays decoupled from it entirely, and stays cheap on its own
regardless of database size since `tools/airmonitor-backup-bundle` stores
(rather than re-compresses) the already-gzipped backup file inside the zip.

Every file the bundle exposes needs root to read, so downloading goes
through a dedicated, narrowly-scoped root helper
(`tools/airmonitor-backup-bundle`, installed to
`/usr/local/sbin/airmonitor-backup-bundle`, granted to the `automation`
user only via `config/sudoers/airmonitor-backup-bundle`) that assembles the
zip and streams it straight to stdout -- nothing sensitive is ever written
to a predictable path on disk.

All three endpoints (`/api/backup/run`, `/api/backup/status`,
`/api/backup/download`) require a Grafana administrator session.
`/api/backup/run` and `/api/backup/download` additionally require a
matching `Origin` header (when the browser sends one -- Safari omits it on
same-origin GET, so it's only validated when present) plus a custom
`X-AirMonitor-Action` header, the same CSRF defense the service/filter
control endpoints already use. The custom header specifically rules out a
plain link or `<img>` tag triggering either action cross-site, since only
same-origin JS (`fetch`) can set it -- important here because the download
response body is close to "every credential the appliance holds" rather
than ordinary status data. `/api/backup/status` skips that extra check
since it's a plain read with no side effects and nothing sensitive in the
response, matching the existing `/api/services/status` precedent.

The downloaded bundle is exactly as sensitive as the files inside it.
Delete it once you no longer need it.

## Restoring a backup

Stop the services that write to the database first, so the restore isn't
immediately overwritten by a live write:

```bash
sudo systemctl stop airmonitor.target airmonitor-status.service airmonitor-export.service
```

Then restore (requires `--yes`, since this overwrites the live database
file):

```bash
sudo -u automation /opt/airmonitor/venv/bin/airmonitor restore \
  /var/lib/airmonitor/backups/airmonitor-20260101T000000Z.sqlite3.gz \
  --yes
```

Restoring:

1. Verifies the backup's integrity (`PRAGMA integrity_check`) before touching anything.
2. Copies the *current* live database aside to `airmonitor.sqlite3.pre-restore.<timestamp>` if one exists, so a mistaken restore is itself recoverable.
3. Overwrites the live database with the backup contents and clears any stale `-wal`/`-shm` side files.

Restart services afterward:

```bash
sudo systemctl start airmonitor.target airmonitor-status.service airmonitor-export.service
```

## Verifying a backup without restoring it

```python
from airmonitor.backup import verify_backup
print(verify_backup("/var/lib/airmonitor/backups/airmonitor-20260101T000000Z.sqlite3.gz"))
```

Prints `ok` for a healthy backup, or the specific SQLite integrity problem otherwise.
