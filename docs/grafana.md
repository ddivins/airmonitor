# Grafana

AirMonitor can provision Grafana automatically with:

- SQLite datasource for `/var/lib/airmonitor/airmonitor.sqlite3`
- Light-theme server defaults
- Anonymous, read-only Viewer access
- AirMonitor logo and tagline banner
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

For a navigation-free kiosk display that is pinned to the light theme:

```text
https://airmonitor.example.com/d/airmonitor-live/airmonitor-live?kiosk&theme=light
```

Anonymous access is enabled with the Grafana `Viewer` role. The landing page links to the
Grafana login for authenticated access, while the provisioned dashboard cannot be edited
or deleted in the UI and the repository
remains the source of truth. Anyone who can reach the Grafana site can view dashboards
and datasources available to the configured Grafana organization. If its name is not
`Main Org.`, pass it when provisioning, for example:

```bash
GRAFANA_ANONYMOUS_ORG_NAME='Example Org' bash tools/install-grafana.sh
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

The installer sets AirMonitor Live as the server home dashboard and Light as the default
theme. Use the kiosk URL above for unattended displays so the theme is also explicit in
the URL.
