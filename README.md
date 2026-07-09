# Air Monitor

Raspberry Pi air-quality monitoring with pluggable sensor drivers and room for
the enclosure CAD that turns the electronics into a finished object.

The first supported sensor is the Amphenol SGX Sensortech
`PS1-VOC-1000-MOD`, connected to a Raspberry Pi 4B over its 3.3 V UART.

## Repository layout

```text
src/airmonitor/sensors/       Sensor protocol implementations
hardware/sgx-ps1-voc-1000-mod/ Wiring, protocol, and reference notes
hardware/sensirion-sps30/     Wiring, protocol, and reference notes
hardware/waveshare-ft232-usb-uart-board-type-c/ USB-C FT232 UART interface notes
cad/enclosure/source/         Editable FreeCAD, OpenSCAD, or other CAD sources
cad/enclosure/exports/        Generated STL, 3MF, and STEP files
cad/enclosure/previews/       Rendered images for design review
docs/                         Software architecture and operating notes
tests/                        Offline protocol tests
```

## Current status

AirMonitor can perform a one-shot read-only hardware probe and can continuously
log SGX VOC, temperature, humidity, and current printer context to SQLite.

The SGX command tries the July 2023 combined-read request first and falls back to
the legacy February 2022 request. It does not change upload mode, sleep state,
calibration, or indicator lights.

One-shot probe:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
airmonitor probe --port /dev/serial0
```

Continuous logger:

```bash
airmonitor log \
  --port /dev/serial0 \
  --sensor-id sgx-voc-01 \
  --database /var/lib/airmonitor/airmonitor.sqlite3 \
  --interval 10
```

The logger subscribes to normalized printer state from `printer-mqtt-service` by
default:

```text
printer/state
printer/available
```

AirMonitor creates a print record when the printer enters an active state such as
`PREPARE`, `RUNNING`, or `PAUSE`. SGX samples reference the active `print_id`.
When the print reaches a terminal state, the print is closed, but samples keep
referencing that print for a configurable post-print context window so VOC decay
can be associated with the completed print.

The sensor needs up to two minutes to settle after power-up in clean air. Treat
early values as warm-up data.

## SQLite storage

AirMonitor uses SQLite as an embedded database. There is no separate database
server, database user, password, grant, or manual schema load.

The database is a regular file, normally:

```text
/var/lib/airmonitor/airmonitor.sqlite3
```

The `automation` service account owns the directory and writes the database
file. AirMonitor creates and migrates its tables on startup.

Install the `sqlite3` package for command-line inspection and troubleshooting.
Python's SQLite library is included with Python itself.

## SQLite schema

The schema separates relatively stable metadata from high-rate sensor samples.

Main tables:

```text
sensors              physical sensor inventory
sensor_sessions      logger runtime sessions
prints               print jobs detected from normalized printer MQTT state
sgx_voc_samples      SGX VOC, temperature, and humidity samples
```

The legacy `air_samples` table is retained for existing installations, but new
code writes to the normalized tables.

`sgx_voc_samples.print_id` is nullable. It is set while a print is active and for
the post-print context window after a print completes.

## Systemd deployment

Perform repository clone, update, and install steps as your normal local
administrative user. Do not clone or maintain the repository as the service
account.

Long-running services should run under a low-privilege service account. The
example systemd units in this project family use `automation` as the shared
service account name.

If your system uses a different service account, update the relevant systemd
unit before installing it.

Example install using SSH cloning:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv sqlite3
id automation || sudo useradd --system --no-create-home --shell /usr/sbin/nologin automation

git clone git@github.com:ddivins/airmonitor.git
cd airmonitor

sudo install -d -o root -g root -m 0755 /opt/airmonitor
sudo install -d -o automation -g automation -m 0755 /var/lib/airmonitor
sudo python3 -m venv /opt/airmonitor/venv
sudo /opt/airmonitor/venv/bin/pip install --upgrade pip
sudo /opt/airmonitor/venv/bin/pip install .

sudo install -o root -g root -m 0644 config/airmonitor.env.example /etc/airmonitor.env
sudo editor /etc/airmonitor.env

sudo install -o root -g root -m 0644 systemd/airmonitor.service /etc/systemd/system/airmonitor.service
sudo systemctl daemon-reload
sudo systemctl enable --now airmonitor.service
```

Verify recent samples:

```bash
systemctl status airmonitor.service
journalctl -u airmonitor.service -f
sqlite3 /var/lib/airmonitor/airmonitor.sqlite3 '
select s.sampled_at, s.gas_ppm, s.temperature_c, s.humidity_rh,
       p.id as print_id, p.last_gcode_state, p.subtask_name, p.filament_type
from sgx_voc_samples s
left join prints p on p.id = s.print_id
order by s.id desc
limit 5;'
```

Verify detected prints:

```bash
sqlite3 /var/lib/airmonitor/airmonitor.sqlite3 '
select id, started_at, ended_at, last_gcode_state, subtask_name, filament_type, filament_color
from prints
order by id desc
limit 5;'
```

## Public repository notes

Do not commit populated environment files, printer serial numbers, printer
access codes, device IP addresses, private hostnames, logs containing secrets,
or local-only credentials.

## Safety and interpretation

This is a cross-sensitive TVOC monitor calibrated with isobutylene. It is useful
for trends, ventilation, and filter control, but it is not a compound-selective
or life-safety instrument.
