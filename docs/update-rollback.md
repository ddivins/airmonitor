# AirMonitor update rollback

`tools/update.sh` records the currently installed Git commit and package version before pulling and installing a new version.

State is stored under:

```text
/var/lib/airmonitor/update-state/
```

Files include:

- `previous-commit`
- `previous-version`
- `target-commit`
- `installed-commit`
- `last-update-started`
- `last-update-succeeded`

## Normal update

```bash
cd ~/airmonitor
bash tools/update.sh
```

The updater installs the package, systemd units, Grafana configuration, restarts services, and runs `airmonitor-doctor`.

## Automatic rollback on failure

If, after an update, any service in `SERVICE_LIST` fails to become active, or
`airmonitor-doctor` reports a required check failure, `tools/update.sh`
automatically runs `tools/rollback.sh` back to the commit that was installed
before the update, rather than leaving the appliance on a broken commit
until someone notices and rolls back by hand.

This is on by default. To disable it (for example, to leave a failed update
in place for debugging) and get the previous behavior of a rollback
suggestion only:

```bash
AUTO_ROLLBACK=0 bash tools/update.sh
```

As with a manual rollback, the main repository checkout stays on the newer,
failing commit — only the installed package and systemd units are reverted.
Investigate before running `tools/update.sh` again.

## Roll back to the previous installed commit

```bash
cd ~/airmonitor
bash tools/rollback.sh
```

The rollback helper:

1. reads the saved previous commit
2. creates a temporary detached Git worktree
3. installs the package from that commit
4. restores that commit's systemd units
5. restarts all AirMonitor services
6. runs `airmonitor-doctor`
7. removes the temporary worktree

The main repository checkout and branch are not changed.

## Roll back to a specific commit

```bash
cd ~/airmonitor
bash tools/rollback.sh COMMIT_SHA
```

## Inspect recorded state

```bash
sudo ls -l /var/lib/airmonitor/update-state
sudo cat /var/lib/airmonitor/update-state/previous-commit
sudo cat /var/lib/airmonitor/update-state/installed-commit
```

## Important limitations

- Database migrations must remain backward compatible for automatic rollback to be safe.
- Local secrets and `/etc/airmonitor/hardware.yaml` are preserved and are not replaced by rollback.
- Grafana dashboards are not currently reverted automatically by `tools/rollback.sh`.
- A rollback restores application code and systemd units, not the Git branch pointer.

## v1.0 upgrade path promise

Starting at v1.0 (see `docs/hardware-bom.md` for the corresponding reference
hardware), this project commits to:

- **Any tagged version can update in place to any later tagged version** via
  `bash tools/update.sh`, without manual database surgery. This holds
  because schema migrations (`airmonitor.database.init_db`) are additive
  only — new tables via `CREATE TABLE IF NOT EXISTS`, new columns via
  `ALTER TABLE ADD COLUMN` (`ensure_columns`) — never destructive
  (`DROP`/rename/retype an existing column). `SCHEMA_VERSION` only
  increases. `tests/test_schema_upgrade_path.py` guards this by migrating a
  populated pre-v1.0-shaped database forward and asserting existing rows
  survive untouched.
- **A failed update rolls back automatically** to the previously installed
  commit (see "Automatic rollback on failure" above), so an update that
  breaks a service or fails its health check doesn't leave the appliance
  degraded unattended.

This project does **not** currently promise that `/etc/airmonitor/*` config
file locations or formats stay fixed forever — a breaking config change
would be called out in `CHANGELOG.md` with a manual migration note, not
silently handled by `tools/update.sh`.
