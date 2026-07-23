# Recovery runbook

What to do when the appliance database is damaged or its configuration has
gone missing. For routine backup/restore and update/rollback, see
`docs/backup-restore.md` and `docs/update-rollback.md` — this runbook covers
the cases those don't: unplanned corruption and lost config.

## First: figure out what's actually wrong

```bash
sudo /opt/airmonitor/venv/bin/airmonitor-doctor
```

Read the `checks` array: `"status": "fail"` on a `required: true` check is
what you're chasing. The two scenarios below correspond to `database` /
`database_schema` failing, and `warn`s on the `/etc/airmonitor/*.env` path
checks, respectively. Also check the status page and:

```bash
sudo journalctl -u airmonitor.target -n 100 --no-pager
```

## Scenario: corrupted or damaged database

**Symptoms:** `airmonitor-doctor`'s `database` check reports
`"status": "fail"` with an integrity-check error, or a service repeatedly
crash-loops with `sqlite3.DatabaseError: database disk image is malformed`
in its journal.

### 1. Stop the services that write to it

```bash
sudo systemctl stop airmonitor.target airmonitor-status.service airmonitor-export.service airmonitor-alerts.service
```

### 2. Confirm the damage

```bash
sqlite3 /var/lib/airmonitor/airmonitor.sqlite3 "PRAGMA integrity_check;"
```

Anything other than a single line of `ok` confirms real corruption (not just
a doctor false alarm).

### 3. Preferred: restore from the most recent good backup

```bash
ls -t /var/lib/airmonitor/backups/*.sqlite3.gz | head -1
sudo -u automation /opt/airmonitor/venv/bin/airmonitor restore <that path> --yes
```

See `docs/backup-restore.md` for the full procedure. This is almost always
the right answer — `airmonitor-backup.timer` runs daily, so you're
typically looking at losing less than a day of samples, not a full rebuild.

### 4. No good backup exists: best-effort recovery

Verified against a deliberately corrupted test database while writing this
runbook: SQLite's own `.recover` command can usually salvage most rows, but
**not all** — rows whose on-disk page happened to be in the damaged region
are gone, and any single-row reference tables that were themselves in the
damaged region (e.g. `sensors`) can come back empty even though rows that
reference them (e.g. `sgx_voc_samples`) survive intact.

```bash
sqlite3 /var/lib/airmonitor/airmonitor.sqlite3 ".recover" > /tmp/recovered.sql
mv /var/lib/airmonitor/airmonitor.sqlite3 /var/lib/airmonitor/airmonitor.sqlite3.corrupt.bak
sqlite3 /var/lib/airmonitor/airmonitor.sqlite3 < /tmp/recovered.sql
sqlite3 /var/lib/airmonitor/airmonitor.sqlite3 "PRAGMA integrity_check;"
sudo chown automation:automation /var/lib/airmonitor/airmonitor.sqlite3
```

Keep `airmonitor.sqlite3.corrupt.bak` around rather than deleting it — someone
more determined could extract more from it later, and it costs only disk
space to keep.

If the `sensors` table lost rows, don't worry about re-adding them by hand:
both the SGX and SPS30 services call `upsert_sensor()` unconditionally on
every startup, so the next time they start they recreate their own sensor
identity row. Historic sample rows that reference a sensor_id are still
readable even before that happens; SQLite only enforces foreign keys on
writes, not on rows that already exist.

### 5. If nothing is recoverable

Move the corrupt file aside (don't delete it) and let the appliance start
fresh:

```bash
sudo mv /var/lib/airmonitor/airmonitor.sqlite3 /var/lib/airmonitor/airmonitor.sqlite3.corrupt.bak
```

Every service calls `init_db()` on startup, which creates a fresh schema if
none exists. This is full data loss for historical samples, but the
appliance resumes logging immediately.

### 6. Restart and verify

```bash
sudo systemctl start airmonitor.target airmonitor-status.service airmonitor-export.service airmonitor-alerts.service
sudo /opt/airmonitor/venv/bin/airmonitor-doctor
```

## Scenario: missing configuration

### Missing per-service env file

`/etc/airmonitor/{sgx-voc,sps30,printer-mqtt,bento,levoit}.env` are each
required — `tools/update.sh` refuses to run at all if one is missing
(`REQUIRED_ENV_FILES`), and the corresponding systemd unit fails to start
(`EnvironmentFile=` with no service running) if it's deleted after install.
`/etc/airmonitor/alerts.env` is the one exception: its unit uses
`EnvironmentFile=-` (the leading `-` makes it optional), so a missing
alerts.env just means the alerting service runs on its built-in defaults
rather than failing.

Recovery:

```bash
cd ~/airmonitor
bash tools/install.sh
```

`tools/install.sh` always runs `install_config_templates()`
unconditionally and only creates files that don't already exist — rerunning
it on an already-configured host is safe and won't touch or overwrite
anything still present. It recreates a **template**, though; you'll need to
re-enter any secrets (VeSync/Kasa credentials, printer access code) from
your own records. This project does not store those secrets anywhere
recoverable itself — back them up yourself (password manager, etc.) if you
want a faster path back.

If you'd rather not run the full installer, the equivalent single-file fix
is:

```bash
sudo install -o root -g root -m 0600 config/env/<name>.env.example /etc/airmonitor/<name>.env
```

### Missing hardware registry (`/etc/airmonitor/hardware.yaml`)

Not fatal on its own: `load_registry()` falls back to an empty registry if
the file doesn't exist, and the shipped install pins sensors to stable
`/dev/airmonitor-sgx` / `/dev/airmonitor-sps30` paths via udev rather than
this registry. Recreate it with:

```bash
cd ~/airmonitor
bash tools/update.sh   # "Ensuring hardware registry exists" step recreates it if missing, preserves it if present
```

### Missing filament policy (`/etc/airmonitor/filament-policy.yaml`)

Contains no secrets, so `tools/update.sh` already keeps it in sync on every
run (backing up the previous copy with a timestamp if it changed). If it's
missing entirely, the next `bash tools/update.sh` recreates it from
`config/filament-policy.yaml` in the repo.

### Missing udev serial rule (`/etc/udev/rules.d/99-airmonitor-serial.rules`)

Sensors fall back to unstable `/dev/ttyUSB*` enumeration instead of the
pinned `/dev/airmonitor-sgx` / `/dev/airmonitor-sps30` paths.
`tools/update.sh`'s "Installing stable AirMonitor serial device names" step
always reinstalls this file unconditionally (it's not a secret and doesn't
vary by host beyond the one pinned CP2105 serial number), so:

```bash
cd ~/airmonitor
bash tools/update.sh
```

### Missing `/etc/airmonitor/install.conf`

Not required for day-to-day operation — `tools/update.sh` only reads
`DOMAIN` and `LEGACY_GRAFANA_REDIRECT` from it, and falls back to skipping
domain-dependent steps if it's absent (see the "Operations note" in
`docs/roadmap.md` for exactly this happening on the production appliance
before it was backfilled). To recreate it, either rerun `bash
tools/install.sh` (it re-prompts and re-saves the file) or write it by hand
following `config/install.conf.example`.

## Full appliance rebuild (destination host is gone entirely)

If the SD card / host itself is lost rather than just its database or
config:

1. Fresh `bash tools/install.sh` on the new host (see `docs/install.md`).
2. Restore the database from your most recent backup (`docs/backup-restore.md`)
   — note that backups currently only live on the appliance's own disk, so
   this only works if you copied backup files off the old host beforehand.
3. Re-enter secrets (VeSync/Kasa credentials, Bambu printer access code,
   MQTT credentials if set) by hand; nothing here stores them recoverably
   for you.
4. Re-pin the udev rule to the new host's actual CP2105 serial number if
   it's a different physical adapter (`config/udev/99-airmonitor-serial.rules`).

`tools/install.sh --migrate-from user@old-host` automates steps 2–3's file
transfer (config and database) when the old host is still reachable over
SSH — see `docs/install.md`. It does not help once the old host is gone.
