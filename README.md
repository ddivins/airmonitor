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

Each sensor sample is stored with the latest printer context, including print
state, active flag, progress, layer, filename, print error, and best-effort
filament fields when present in the Bambu AMS payload. The full normalized
printer JSON is also stored with each sample.

The sensor needs up to two minutes to settle after power-up in clean air. Treat
early values as warm-up data.

## SQLite schema

The initial database is intentionally simple. The main table is `air_samples`.
Each row represents one sensor sample plus the latest known printer state at the
time of that sample.

Important columns include:

```text
sampled_at
sensor_id
sensor_model
sensor_protocol
sensor_port
gas_ppm
gas_mass
full_scale
temperature_c
humidity_rh
printer_available
printer_active
printer_gcode_state
printer_progress_percent
printer_layer_num
printer_total_layer_num
printer_subtask_name
printer_print_error
printer_filament_type
printer_filament_color
printer_state_json
```

This keeps time-series queries easy while still preserving the full printer
payload for later schema evolution.

## Systemd deployment

Perform repository clone, update, and install steps as your normal local
administrative user. Do not clone or maintain the repository as the service
account.

Long-running services should run under a low-privilege service account. The
example systemd units in this project family use `automation` as the shared
service account name.

If your system uses a different service account, update the relevant systemd
unit before installing it.

Example install:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
id automation || sudo useradd --system --no-create-home --shell /usr/sbin/nologin automation

git clone https://github.com/ddivins/airmonitor.git
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

Verify:

```bash
systemctl status airmonitor.service
journalctl -u airmonitor.service -f
sqlite3 /var/lib/airmonitor/airmonitor.sqlite3 'select sampled_at, gas_ppm, temperature_c, humidity_rh, printer_gcode_state, printer_subtask_name from air_samples order by id desc limit 5;'
```

## Public repository notes

Do not commit populated environment files, printer serial numbers, printer
access codes, device IP addresses, private hostnames, logs containing secrets,
or local-only credentials.

## Safety and interpretation

This is a cross-sensitive TVOC monitor calibrated with isobutylene. It is useful
for trends, ventilation, and filter control, but it is not a compound-selective
or life-safety instrument.
