# Fresh host installation

`tools/install.sh` is the supported bootstrap path for a new Raspberry Pi OS or Debian host.
Run it from a clone owned by the normal administrative user, not as root and not as the
`automation` service account.

## Quick start

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/ddivins/airmonitor.git
cd airmonitor
bash tools/install.sh
```

With no arguments and nothing saved yet, the installer asks a few short questions — install
mode, and (for a full install) a public domain and Let's Encrypt contact email — then saves the
answers to `/etc/airmonitor/install.conf`. Rerunning `bash tools/install.sh` later reuses those
answers automatically, the same way `apt` remembers `debconf` answers; edit that file (or pass a
different one with `--config`) to change them.

For unattended installs, copy [`config/install.conf.example`](../config/install.conf.example) to
a file of your own, edit it, and run:

```bash
bash tools/install.sh --config /path/to/install.conf --non-interactive
```

## Core installation

```text
MODE=core
```

Core mode installs the host dependencies, Mosquitto, the `automation` service account, serial
permissions, `/opt/airmonitor/venv`, missing `/etc/airmonitor/*.env` templates, systemd units,
the hardware registry, and the AirMonitor application. Existing configuration and secrets are
preserved. No domain, TLS, or public routing is required.

After the first run, configure at least:

```text
/etc/airmonitor/printer-mqtt.env
/etc/airmonitor/bento.env
/etc/airmonitor/levoit.env
```

Rerun the installer safely after editing configuration.

## Full installation

```text
MODE=full
DOMAIN=airmonitor.example.com
CERT_EMAIL=admin@example.com
```

Full mode additionally installs Grafana OSS from Grafana's official stable APT repository,
nginx, Certbot, and `python3-certbot-dns-cloudflare`, then provisions the AirMonitor Grafana
datasource and dashboards under `https://DOMAIN/grafana/`.

The installer does not enable the checked-in public nginx site until a certificate exists for
`DOMAIN`. This prevents a fresh nginx installation from failing because the configured
certificate path doesn't exist yet.

To let the installer request that certificate automatically, create a root-readable Cloudflare
credentials file with mode `0600`, add its path as `CERTBOT_CLOUDFLARE_CREDENTIALS` in your
config, then run `bash tools/install.sh --config /path/to/install.conf`:

```bash
sudo install -d -o root -g root -m 0700 /root/.secrets
sudo install -o root -g root -m 0600 cloudflare.ini /root/.secrets/cloudflare.ini
```

```text
CERTBOT_CLOUDFLARE_CREDENTIALS=/root/.secrets/cloudflare.ini
```

The Cloudflare file uses Certbot's standard format:

```ini
dns_cloudflare_api_token = replace-with-scoped-api-token
```

The installer never prints this file or stores its token in the repository. Leaving
`CERTBOT_CLOUDFLARE_CREDENTIALS` blank skips automatic issuance; obtain the certificate yourself
and rerun `--config ... MODE=full` once it exists.

### Historical Grafana subdomain

An older AirMonitor host may have served Grafana at a separate `grafana.DOMAIN` hostname before
the app moved to a unified origin with Grafana under `/grafana/`. Set
`LEGACY_GRAFANA_REDIRECT=true` in your config to also obtain a certificate for `grafana.DOMAIN`
and redirect it into the unified app. New installs don't need this — leave it `false`.

## Migrating an existing appliance

```text
MIGRATE_FROM=user@old-airmonitor
```

or

```bash
bash tools/install.sh --migrate-from user@old-airmonitor
```

Migration copies `/etc/airmonitor`, the AirMonitor SQLite database, and—when `MODE=full`—the
Grafana SQLite database. It briefly stops AirMonitor and Grafana on the source so the database
files are consistent, restarts them immediately after the archive is transferred, and backs up
any destination files before replacing them. SSH access and passwordless remote `sudo` are
required. Certificates are deliberately not migrated; issue or restore them separately for the
new host. `MIGRATE_FROM` is never saved to `/etc/airmonitor/install.conf` — it's a one-time
action, not a standing setting.

## Non-interactive mode

```bash
bash tools/install.sh --config /path/to/install.conf --non-interactive
```

This disables prompts and editors. `MODE=full` requires `DOMAIN` and `CERT_EMAIL` to already be
set in the config file — the installer fails fast with a clear message instead of guessing. The
final report lists template values and missing certificates that still require attention.

## CP2105 safety check

The checked-in udev rules currently identify CP2105 serial `00B9A86D`:

```text
/dev/airmonitor-sgx   -> interface 00
/dev/airmonitor-sps30 -> interface 01
```

If another USB serial adapter is connected and the expected serial is absent, installation
stops before deploying the rule. Update `config/udev/99-airmonitor-serial.rules` intentionally
for the replacement adapter. If no adapter is connected, installation continues with a clear
warning and the aliases can be verified after insertion.

## Idempotence and secrets

- Existing `/etc/airmonitor` files are never overwritten during an ordinary installation.
- Migrated destination files receive timestamped backups.
- Environment files are installed with mode `0600`.
- Public routing is enabled only once a certificate for `DOMAIN` exists.
- `tools/update.sh` remains the normal updater after installation, and reads
  `/etc/airmonitor/install.conf` itself so routine updates keep using the same domain.

## Verification

```bash
sudo /opt/airmonitor/venv/bin/airmonitor-doctor

systemctl --no-pager --full status \
  airmonitor.target \
  airmonitor-voc.service \
  airmonitor-sps30.service \
  airmonitor-printer-mqtt.service \
  airmonitor-bento.service \
  airmonitor-levoit.service \
  airmonitor-status.service \
  airmonitor-export.service \
  mosquitto.service
```

For a full installation, also inspect:

```bash
systemctl --no-pager --full status grafana-server.service nginx.service
```
