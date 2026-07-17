# AirMonitor

<p align="center">
  <img src="docs/assets/branding/airmonitor-logo-1536px.png" alt="AirMonitor — Monitor. Understand. Don’t Die." width="760">
</p>

<p align="center"><strong><em>Monitor. Understand. Don’t Die.</em></strong></p>

AirMonitor is an open-source DIY measurement platform for evaluating air-filtration
performance in 3D-printing spaces.

The primary goal is **not** to treat inexpensive or cross-sensitive sensor readings as
laboratory-grade measurements of indoor VOC concentration, particulate exposure, or personal
safety. Instead, AirMonitor uses repeatable sensor signals to answer practical comparative
questions:

- Does a filter reduce the peak response produced by a print?
- Does it reduce the total measured response over the full print and post-print period?
- Does the room return to baseline faster with filtration enabled?
- How do different filters, fan speeds, placements, enclosures, and filament materials compare?

AirMonitor combines commercially available sensor modules, USB-connected interfaces, local
data storage, Grafana dashboards, printer awareness, and filter automation in a Raspberry
Pi-based appliance.

The current AirMonitor Sensors are built around:

- [Amphenol SGX Sensortech `PS1-VOC-1000-MOD`](hardware/sgx-ps1-voc-1000-mod/README.md) for a cross-sensitive VOC response, temperature, and humidity
- [Sensirion `SPS30`](hardware/sensirion-sps30/README.md) for particulate matter mass, particle counts, and typical particle size

These are DIY-built sensor assemblies, not custom sensing chips. Each AirMonitor Sensor
packages a commercial sensor module with the required interface electronics, wiring, and a
purpose-built enclosure.

See the [Hardware Guide](docs/hardware-registry.md) for the current USB architecture,
supported sensor modules, enclosure plans, device configuration, and advanced UART notes.

> **DIY project notice:** AirMonitor is not a certified air-quality instrument and should
> not be relied upon for regulatory, medical, occupational-exposure, or life-safety decisions.

## Project Overview

AirMonitor currently provides:

- USB-connected AirMonitor Sensors
- Explicit, host-configured serial device paths
- Modular Python sensor drivers
- Local SQLite storage
- Provisioned Grafana dashboards
- Bambu printer-state integration
- Bento Box and Levoit filter automation
- Planned 3D-printable enclosures, with printable releases to be linked from MakerWorld

## Project Philosophy

- Measure **filter efficacy**, not claim laboratory air analysis
- Prefer controlled comparisons over isolated absolute readings
- Change one experimental variable at a time whenever practical
- Reproducible experiments
- Repeatability over claims of absolute accuracy
- Engineering decisions backed by measurements
- AI-assisted development with human review and real-world validation
- Documentation as a first-class project deliverable

## Measurement Model

AirMonitor treats its sensors as instruments for comparative experiments.

A typical test records:

1. a pre-print baseline
2. the active print period
3. a configurable post-print recovery period
4. whether each filter was enabled, disabled, or manually overridden
5. the printer, filament, and other experimental context

Useful comparisons include unfiltered versus filtered runs, different filter media, fan speeds,
filter placements, enclosure states, and room ventilation conditions. Absolute values remain
visible because they are useful for plotting and repeatability, but the project emphasizes
changes in peak, area under the response curve, and time to return toward baseline.

## AI-Assisted Development

AirMonitor was developed with extensive AI assistance. The majority of the software and
documentation, along with portions of the CAD and project-planning work, were generated
collaboratively with AI tools and then reviewed, tested, modified, and integrated by the
project author.

AI accelerates implementation and documentation, but it is not treated as a source of
experimental truth. Hardware behavior, sensor communications, installation procedures, and
reported results are validated against physical devices and collected measurements. The
repository and repeatable real-world testing remain the sources of truth for the project.

## Hardware Model

```text
Commercial sensor module
        │ TTL UART
USB-UART interface
        │ USB
Configured Linux serial device
        │
Python sensor driver
        │
SQLite / Grafana / filter analysis and automation
```

USB is the recommended connection method because it is convenient, replaceable, and easy to
route outside an enclosure. AirMonitor currently favors explicit device configuration over a
custom EEPROM identity and automatic hardware-matching scheme.

Native UART wiring remains documented as an advanced option for builders using a Raspberry Pi
GPIO UART or another embedded host.

## Why the Amphenol SGX PS1-VOC-1000-MOD?

AirMonitor is intended for comparative filter testing during FDM 3D printing. The Amphenol
SGX `PS1-VOC-1000-MOD` occupies a useful middle ground between inexpensive
metal-oxide-semiconductor sensors commonly used in hobbyist air-quality monitors and
professional photoionization-detector instruments.

The SGX PS1 uses **Solid Polymer Electrolyte (SPE)** electrochemical sensing technology. The
complete MOD assembly combines the sensing element with onboard processing, temperature and
humidity measurement, environmental compensation, factory-matched calibration, and a UART
interface. This avoids the analog-front-end design and initial calibration work required by a
bare sensing element.

A primary reason for selecting the SGX module is its published cross-sensitivity table. The
listed gases include **styrene**, a compound of particular interest when printing materials
such as ABS and ASA. This does not make the device a selective styrene analyzer. It does,
however, provide a documented reason to expect a repeatable response to VOC mixtures relevant
to the intended filter-comparison experiments.

The module is calibrated with isobutylene and reports a cross-sensitive TVOC value. See the
[SGX hardware notes](hardware/sgx-ps1-voc-1000-mod/README.md) and the
[manufacturer datasheet](https://www.mouser.com/catalog/specsheets/Amphenol_5262023_DS_0425_PS1_PS4_VOC_1000_MOD.pdf)
for its specifications, cross-sensitivity table, and operating guidance.

## What Runs

The install provides one Python package with separate systemd services:

```text
airmonitor.target               Umbrella lifecycle for the AirMonitor application
airmonitor-voc.service          SGX VOC / temperature / humidity logger
airmonitor-sps30.service        SPS30 particulate logger
airmonitor-printer-mqtt.service Bambu MQTT normalizer
airmonitor-bento.service        Bento Box outlet automation
airmonitor-levoit.service       Levoit/Core room-filter automation
airmonitor-status.service       Read-only appliance status landing page
airmonitor-export.service       Read-only print report and data exports
mosquitto.service               Local MQTT broker
grafana-server.service          Grafana dashboard
```

## Repository Layout

```text
src/airmonitor/sensors/sgx/ps1_voc/       SGX protocol implementation
src/airmonitor/sensors/sensirion/sps30/   SPS30 SHDLC UART driver
src/airmonitor/printers/bambu/            Bambu printer MQTT support
src/airmonitor/filters/bento/             Kasa/Bento filter automation
src/airmonitor/filters/levoit/            Levoit room-filter automation
src/airmonitor/database/                  SQLite schema and repositories
grafana/                                  Provisioned datasource and dashboard
systemd/                                  Service units
config/                                   Example environment and hardware files
hardware/                                 Wiring and USB-UART notes
docs/                                     Architecture and operating notes
tests/                                    Offline protocol and dashboard tests
```

## Data Flow

The printer MQTT normalizer publishes local state to Mosquitto:

```text
printer/state
printer/available
```

The SGX logger records VOC response samples and associates them with the active print and a
configurable post-print context window. The SPS30 logger records particulate samples
independently. Filter services use printer state, filament policy, sensor state, and manual
override state to decide whether the Bento or Levoit filter should run.

Manual filter override state is persisted in SQLite:

```bash
airmonitor filter bento auto
airmonitor filter bento on
airmonitor filter bento off
airmonitor filter levoit status
```

Manual `on` or `off` wins over automation until set back to `auto`.

## SQLite Storage

AirMonitor uses a local SQLite file. There is no separate database server, database user,
password, grant, or manual schema load.

Default path:

```text
/var/lib/airmonitor/airmonitor.sqlite3
```

Main tables:

```text
sensors              physical sensor inventory
sensor_sessions      logger runtime sessions
prints               print jobs detected from normalized printer MQTT state
sgx_voc_samples      SGX VOC, temperature, and humidity samples
sps30_samples        SPS30 particulate samples
filter_control_state persisted filter manual/automation state
```

## Grafana

The appliance root URL presents a read-only status landing page built from normalized
AirMonitor service state. It links to the detailed Grafana dashboard and never accesses sensor
hardware directly. See [Status Page](docs/status-page.md).

The provisioned AirMonitor Print Window dashboard includes an **Export Selected Print**
link. Public exports are served at:

```text
/exports/print?print_id=<print-id>
```

Available formats are a publication PNG, multipage PDF report, Excel workbook, raw CSV
ZIP, and complete experiment ZIP. Every format is generated from SQLite without contacting
sensor hardware. The selected window starts 30 minutes before the print and ends 30 minutes
after `ended_at`, or `last_seen_at` for an active print. See [Print Exports](docs/print-exports.md).

Grafana is provisioned from this repository:

```text
grafana/provisioning/datasources/airmonitor-sqlite.yaml
grafana/provisioning/dashboards/airmonitor.yaml
tools/generate-grafana-dashboard.py
grafana/dashboards/airmonitor-live.json
```

The dashboard is generated in light mode and uses the SQLite datasource UID
`airmonitor-sqlite`. Manual Grafana dashboard edits are temporary; the installer regenerates
and reprovisions the dashboard from the repository.

Install or refresh Grafana provisioning:

```bash
bash tools/install-grafana.sh
```

## Host Install and Update

Run clone, pull, and install/update steps as the normal local administrative user. Do not
maintain the checkout as the service account.

Typical update on an already-installed host:

```bash
cd ~/airmonitor
git pull --ff-only
bash tools/update.sh
```

Fresh install outline:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv sqlite3
id automation || sudo useradd --system --no-create-home --shell /usr/sbin/nologin automation

git clone https://github.com/ddivins/airmonitor.git
cd airmonitor
bash tools/update.sh
```

Local secret and host-specific configuration files live outside the repository and should be
preserved across updates:

```text
/etc/airmonitor/sgx-voc.env
/etc/airmonitor/sps30.env
/etc/airmonitor/printer-mqtt.env
/etc/airmonitor/bento.env
/etc/airmonitor/levoit.env
/etc/airmonitor/hardware.yaml
/etc/airmonitor/filament-policy.yaml
```

## Hardware Configuration

The current build uses USB-UART interfaces and explicit serial device configuration. Depending
on the adapter and Linux host, the configured path may be a stable `/dev/serial/by-id/...`
symlink, a custom udev symlink, or another known device path.

The deployed AirMonitor appliance uses a Silicon Labs CP2105 dual USB-UART adapter.
Repository-managed udev rules identify serial `00B9A86D` and assign each interface a stable
sensor name:

```text
/dev/airmonitor-sgx   -> CP2105 interface 00
/dev/airmonitor-sps30 -> CP2105 interface 01
```

These aliases remain stable if Linux assigns different `/dev/ttyUSB*` numbers.

AirMonitor does not require builders to reprogram an FTDI EEPROM or depend on automatic
manufacturer/product/serial matching. Earlier EEPROM and registry-based discovery work remains
in the repository as historical or optional implementation material, but it is not the
recommended public build path.

```yaml
version: 1
devices:
  sgx-voc-01:
    driver: airmonitor.sensors.sgx.ps1_voc
    transport: usb-uart
    device: /dev/airmonitor-sgx
  sps30-01:
    driver: airmonitor.sensors.sensirion.sps30
    transport: usb-uart
    device: /dev/airmonitor-sps30
```

See the [Hardware Guide](docs/hardware-registry.md) for the current USB connection model,
device-path configuration, and advanced native UART information.

## Operations

Check service state:

```bash
systemctl --no-pager --full status \
  airmonitor.target \
  airmonitor-voc.service \
  airmonitor-sps30.service \
  airmonitor-printer-mqtt.service \
  airmonitor-bento.service \
  airmonitor-levoit.service \
  airmonitor-status.service \
  airmonitor-export.service \
  grafana-server.service \
  mosquitto.service
```

Follow logs:

```bash
sudo journalctl -u airmonitor-voc.service -f
sudo journalctl -u airmonitor-sps30.service -f
sudo journalctl -u grafana-server.service -f
```

## Public Repository Notes

Do not commit populated environment files, printer serial numbers, printer access codes,
device IP addresses, private hostnames, logs containing secrets, or local-only credentials.

## Interpreting Sensor Measurements

AirMonitor is designed to produce **repeatable comparative measurements of filter
performance**, not laboratory chemical analysis or regulatory occupational-exposure
measurements.

The SGX module is factory calibrated with isobutylene, but it is cross-sensitive to multiple
VOCs and cannot identify which individual compound or mixture produced a reading. AirMonitor
therefore treats its reported value primarily as a relative VOC-response signal.

The SPS30 produces real particulate mass and count estimates, but placement, airflow, room
mixing, print geometry, and experimental timing still affect comparisons. Controlled tests
should keep those factors as consistent as practical.

Useful questions include:

- Does a filter reduce the VOC or particulate peak compared with no filtration?
- Does it reduce the total response across the print and recovery period?
- Does a higher fan speed materially improve removal?
- Does filter placement change measured effectiveness?
- How quickly does the room return toward its pre-print baseline?

The displayed VOC ppm value must not be interpreted as a compound-specific styrene
concentration or compared directly with OSHA, NIOSH, or other exposure limits. Regulatory
limits apply to specific compounds, defined sampling periods, and validated measurement
methods. AirMonitor's value is in trends, controlled comparisons, and documenting the relative
effect of filtration, ventilation, materials, and operating conditions.
