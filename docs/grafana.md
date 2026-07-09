# Grafana

AirMonitor can provision Grafana automatically with:

- SQLite datasource for `/var/lib/airmonitor/airmonitor.sqlite3`
- Light-theme server defaults
- AirMonitor Live dashboard
- AirMonitor database group permissions for Grafana

## Prerequisites

Install Grafana, nginx, certbot, and the Cloudflare DNS certbot plugin as documented in the main install notes.

The Grafana SQLite plugin is installed by the provisioning script.

## Provision or update Grafana

From the AirMonitor checkout:

```bash
cd ~/airmonitor
git pull --ff-only
bash tools/install-grafana.sh
```

The dashboard is installed to:

```text
/var/lib/grafana/dashboards/airmonitor/airmonitor-live.json
```

Provisioning files are installed to:

```text
/etc/grafana/provisioning/datasources/airmonitor-sqlite.yaml
/etc/grafana/provisioning/dashboards/airmonitor.yaml
```

## Dashboard URL

```text
https://airmonitor.example.com/d/airmonitor-live/airmonitor-live
```

## Dashboard behavior

The VOC graph uses:

- soft minimum: `0`
- soft maximum: `5`
- automatic expansion above the soft max for larger spikes
- line width `3`
- light fill

This keeps normal VOC ranges visible without clipping IPA/solvent spikes.

## Permissions

The installer creates or reuses the `airmonitor-data` group and adds:

- `grafana`
- `automation`
- the invoking sudo user when available

The database directory is configured as:

```text
/var/lib/airmonitor           root:airmonitor-data 750 + setgid
/var/lib/airmonitor/*.sqlite3 root:airmonitor-data 640
```

If group membership was just changed, log out and back in or run:

```bash
newgrp airmonitor-data
```

## Grafana home dashboard

After provisioning, set the home dashboard in Grafana:

```text
Administration → General → Default preferences → Home Dashboard → AirMonitor Live
```

Keep theme set to Light.
