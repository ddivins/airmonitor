# AirMonitor

<p align="center">
  <img src="docs/assets/branding/airmonitor-logo-1536px.png" alt="AirMonitor — Monitor. Understand. Don’t Die." width="760">
</p>

<p align="center"><strong><em>Monitor. Understand. Don’t Die.</em></strong></p>

AirMonitor is an open-source DIY air-quality monitoring platform for 3D-printing spaces.
It combines commercially available sensor modules, USB-connected interfaces, automatic
hardware discovery, local data storage, Grafana dashboards, printer awareness, and filter
automation in a Raspberry Pi-based appliance.

The current AirMonitor Sensors are built around:

- [Amphenol SGX Sensortech `PS1-VOC-1000-MOD`](hardware/sgx-ps1-voc-1000-mod/README.md) for TVOC, temperature, and humidity
- [Sensirion `SPS30`](hardware/sensirion-sps30/README.md) for particulate matter mass, particle counts, and typical particle size

These are DIY-built sensor assemblies, not custom sensing chips. Each AirMonitor Sensor
packages a commercial sensor module with the required interface electronics, wiring, and
a purpose-built enclosure.

See the [Hardware Guide](docs/hardware-registry.md) for the current USB architecture,
EEPROM identification, supported sensor modules, enclosure plans, and advanced UART notes.

> **DIY project notice:** AirMonitor is not a certified air-quality instrument and should
> not be relied upon for regulatory, medical, occupational-exposure, or life-safety decisions.

## Project Overview

AirMonitor currently provides:

- USB-connected AirMonitor Sensors
- EEPROM-based USB identity and stable device discovery
- Modular Python sensor drivers
- Local SQLite storage
- Provisioned Grafana dashboards
- Bambu printer-state integration
- Bento Box and Levoit filter automation
- Planned 3D-printable enclosures, with printable releases to be linked from MakerWorld

## Project Philosophy

- Open hardware whenever practical
- Reproducible experiments
- Repeatability over claims of absolute accuracy
- Engineering decisions backed by measurements
- AI-assisted development with human review and real-world validation
- Documentation as a first-class project deliverable

## AI-Assisted Development

AirMonitor was developed with extensive AI assistance. The majority of the software and
documentation, along with portions of the CAD and project-planning work, were generated
collaboratively with AI tools and then reviewed, tested, modified, and integrated by the
project author.

AI accelerates implementation and documentation, but it is not treated as a source of
experimental truth. Hardware behavior, sensor communications, installation procedures,
and reported results are validated against physical devices and collected measurements.
The repository and repeatable real-world testing remain the sources of truth for the
project.

## Hardware Model

```text
Commercial sensor module
        │
USB Interface
(USB-UART + EEPROM identity)
        │
Linux device discovery
        │
AirMonitor hardware registry
        │
Python sensor driver
        │
SQLite / Grafana / automation
```

USB is the recommended connection method. Native UART wiring remains documented as an
advanced option for builders using a Raspberry Pi GPIO UART or another embedded host.

## Why the Amphenol SGX PS1-VOC-1000-MOD?

AirMonitor is intended for comparative indoor-air-quality testing during FDM 3D printing.
The Amphenol SGX `PS1-VOC-1000-MOD` occupies a useful middle ground between the inexpensive
metal-oxide-semiconductor (MOS) sensors commonly used in hobbyist air-quality monitors and
professional photoionization-detector (PID) instruments.

Unlike those inexpensive MOS sensors, the SGX PS1 uses **Solid Polymer Electrolyte (SPE)**
electrochemical sensing technology. The manufacturer specifies fast response, low power
consumption, repeatability, and a long expected service life. The complete MOD assembly
combines the sensing element with onboard processing, temperature and humidity measurement,
environmental compensation, factory-matched calibration, and a UART interface. This avoids
the analog-front-end design and initial calibration work required by a bare sensing element.

A primary reason for selecting the SGX module is its unusually explicit published
cross-sensitivity table. The listed gases include **styrene**, a compound of particular
interest when printing materials such as ABS and ASA. Published characterization of a
sensor's response to styrene is uncommon in practical integrated VOC modules. This does not
make the device a selective styrene analyzer, but it gives AirMonitor a documented reason to
expect a response to a VOC that is directly relevant to its intended application.

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

The SGX logger records VOC samples and associates samples with the active print and a
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
AirMonitor service state. It links to the detailed Grafana dashboard and never accesses
sensor hardware directly. See [Status Page](docs/status-page.md).

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
`airmonitor-sqlite`. Manual Grafana dashboard edits are temporary; the installer
regenerates and reprovisions the dashboard from the repository.

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

Local secret and host-specific configuration files live outside the repository and should
be preserved across updates:

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

The recommended build uses FTDI USB-UART adapters with distinct EEPROM identities. Linux
creates stable `/dev/serial/by-id/...` symlinks, while the AirMonitor hardware registry
matches the configured manufacturer, product, and serial values.

Example hardware registry entries:

```yaml
version: 1
devices:
  sgx-voc-01:
    driver: airmonitor.sensors.sgx.ps1_voc
    transport: usb-uart
    match:
      vendor: DSD
      product: AirMonitor
      serial: SGX-VOC-EXAMPLE
  sps30-01:
    driver: airmonitor.sensors.sensirion.sps30
    transport: usb-uart
    match:
      vendor: DSD
      product: AirMonitor
      serial: SPS30-EXAMPLE
```

See the [Hardware Guide](docs/hardware-registry.md) for build architecture, EEPROM
provisioning, discovery, and advanced native UART information.

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

## Interpreting VOC Measurements

AirMonitor is designed to produce **repeatable comparative measurements**, not laboratory
chemical analysis or regulatory occupational-exposure measurements. The SGX module is
factory calibrated with isobutylene, but it is cross-sensitive to multiple VOCs and cannot
identify which individual compound or mixture produced a reading.

The project therefore treats reported VOC values primarily as **relative measurements**.
Controlled experiments aim to change one variable at a time while keeping other conditions
as consistent as practical. Useful questions include:

- Does a filter reduce the VOC peak or total response compared with no filtration?
- Does opening a window reduce the peak or shorten the return to baseline?
- How do different filament materials compare under similar print conditions?
- How quickly does the room return toward its pre-print baseline?

The displayed ppm value must not be interpreted as a compound-specific styrene
concentration or compared directly with OSHA, NIOSH, or other exposure limits. Regulatory
limits apply to specific compounds, defined sampling periods, and validated measurement
methods. AirMonitor's value is in trends, controlled comparisons, and documenting the
relative effect of ventilation, filtration, materials, and operating conditions.

The SPS30 readings are particulate measurements reported as PM mass concentrations and
particle counts. They complement the SGX VOC signal; they do not replace gas sensing or
certified occupational-exposure instrumentation.
