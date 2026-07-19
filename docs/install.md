# Fresh host installation

`tools/install.sh` is the supported bootstrap path for a new Raspberry Pi OS or Debian host.
Run it from a clone owned by the normal administrative user, not as root and not as the
`automation` service account.

## Core installation

Install Git, clone the repository, and run:

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/ddivins/airmonitor.git
cd airmonitor
bash tools/install.sh --core
```

Core mode installs the host dependencies, Mosquitto, the `automation` service account, serial
permissions, `/opt/airmonitor/venv`, missing `/etc/airmonitor/*.env` templates, systemd units,
the hardware registry, and the AirMonitor application. Existing configuration and secrets are
preserved.

After the first run, configure at least:

```text
/etc/airmonitor/printer-mqtt.env
/etc/airmonitor/bento.env
/etc/airmonitor/levoit.env
```

Rerun the installer safely after editing configuration.

## Full installation

```bash
bash tools/install.sh --full
```

Full mode additionally installs Grafana OSS from Grafana's official stable APT repository,
nginx, Certbot, and `python3-certbot-dns-cloudflare`, then provisions the AirMonitor Grafana
datasource and dashboards.

The installer does not enable the checked-in public nginx site until certificates exist for
both `airmonitor.example.com` and `grafana.airmonitor.example.com`. This prevents a
fresh nginx installation from failing because the configured certificate paths do not exist.

To let the installer request both certificates, create a root-readable Cloudflare credentials
file with mode `0600`, then run:

```bash
sudo install -d -o root -g root -m 0700 /root/.secrets
sudo install -o root -g root -m 0600 cloudflare.ini /root/.secrets/cloudflare.ini

AIRMONITOR_CERTBOT_CLOUDFLARE_CREDENTIALS=/root/.secrets/cloudflare.ini \
AIRMONITOR_CERT_EMAIL=admin@example.com \
bash tools/install.sh --full
```

The Cloudflare file uses Certbot's standard format:

```ini
dns_cloudflare_api_token = replace-with-scoped-api-token
```

The installer never prints this file or stores its token in the repository.

## Migrating an existing appliance

```bash
bash tools/install.sh --full --migrate-from USER@old-airmonitor
```

Migration copies `/etc/airmonitor`, the AirMonitor SQLite database, and—when using `--full`—
the Grafana SQLite database. It briefly stops AirMonitor and Grafana on the source so the
database files are consistent, restarts them immediately after the archive is transferred,
and backs up any destination files before replacing them. SSH access and passwordless remote
`sudo` are required. Certificates are deliberately not migrated; issue or restore them
separately for the new host.

## Non-interactive mode

```bash
bash tools/install.sh --core --non-interactive
```

This disables prompts and editors. Existing environment files or unattended configuration
management should populate required values first. The final report lists template values and
missing certificates that still require attention.

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
- Public routing is enabled only when both certificate/key pairs are present.
- `tools/update.sh` remains the normal updater after installation.

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
