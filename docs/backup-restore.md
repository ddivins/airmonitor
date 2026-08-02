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

- **Backup now** triggers the same `airmonitor backup` logic immediately
  (in-process, as the `automation` user the status service already runs as
  -- no elevated privilege needed for this one).
- **Download backup bundle** takes a fresh backup, then downloads a `.zip`
  containing everything a from-scratch restore onto new hardware needs:
  `/etc/airmonitor/` (install.conf and every `.env` secret), the Cloudflare
  DNS-01 credential at `/root/.secrets/cloudflare.ini`, Grafana's own
  database, the fresh AirMonitor database backup, and a `RESTORE.md` with
  the exact restore steps. Every one of those files needs root to read, so
  this goes through a dedicated, narrowly-scoped root helper
  (`tools/airmonitor-backup-bundle`, installed to
  `/usr/local/sbin/airmonitor-backup-bundle`, granted to the `automation`
  user only via `config/sudoers/airmonitor-backup-bundle`) that assembles
  the zip and streams it straight to stdout -- nothing sensitive is ever
  written to a predictable path on disk.

Both endpoints (`/api/backup/run`, `/api/backup/download`) require a Grafana
administrator session *and* a matching `Origin` header plus a custom
`X-AirMonitor-Action` header, the same CSRF defense the service/filter
control endpoints already use. The custom header specifically rules out a
plain link or `<img>` tag triggering the download cross-site, since only
same-origin JS (`fetch`) can set it -- important here because the response
body is close to "every credential the appliance holds" rather than
ordinary status data.

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
