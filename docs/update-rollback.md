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
