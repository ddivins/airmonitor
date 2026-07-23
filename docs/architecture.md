# AirMonitor Architecture

AirMonitor is an open-source DIY measurement platform for evaluating air-filtration
performance in 3D-printing spaces. It uses commercially available sensor modules packaged as
USB-connected AirMonitor Sensors, with local collection, storage, dashboards, printer
awareness, and filter automation running on a Raspberry Pi or other Linux host.

The system is designed around comparative experiments rather than claims of laboratory-grade
VOC analysis or certified particulate exposure monitoring. Sensor readings are collected with
print and filter context so filtered and unfiltered runs can be compared for peak response,
total response, and time to return toward baseline.

The software model is one repository, one Python package, one shared database, one shared
configuration model, and multiple optional integrations.

## End-to-End Data Path

```text
Commercial sensor module
        │ TTL UART
USB-UART interface
        │ USB
Configured Linux serial device
        │
Sensor driver and service
        │
SQLite database + print/filter context
        │
Grafana / filter-efficacy analysis / automation
```

USB is the recommended physical connection. Native UART remains available as an advanced
integration path. Current installations use explicit device-path configuration rather than a
custom EEPROM identity and automatic hardware-registry matching scheme.

## Measurement and Experiment Context

Sensor samples are most useful when interpreted alongside the conditions under which they were
collected. AirMonitor associates measurements with information such as:

- pre-print baseline period
- active print and post-print recovery windows
- printer and filament state
- Bento Box and room-filter operating state
- manual filter overrides
- timestamps suitable for aligning multiple sensor signals

This structure supports comparisons such as:

- filtered versus unfiltered runs
- one filter medium versus another
- different fan speeds or filter placements
- enclosure open versus closed
- different filament materials under otherwise similar conditions

The architecture preserves raw reported measurements, but downstream interpretation should
focus on repeatable relative differences rather than treating a single VOC ppm value as a
compound-specific exposure measurement.

The `AirMonitor Compare Prints` Grafana dashboard is where these comparisons actually happen:
pick up to four prints and it shows a side-by-side summary table (peak VOC, peak PM2.5,
filament, duration) plus VOC, PM2.5, and temperature curves for all four aligned on elapsed
time since each print's own start, rather than wall-clock time, since two prints being
compared occurred at different real times. See `docs/status-page.md`.

## Hardware Connection

The physical hardware concepts are:

- **AirMonitor Sensor** — the complete DIY physical device
- **sensor module** — the commercial sensing component, such as the SPS30
- **USB interface** — the USB-UART bridge used to connect the module to the host
- **configured device path** — the Linux serial path selected for the sensor service

A stable `/dev/serial/by-id/...` path or custom udev symlink is preferred when available. The
project does not require builders to reprogram FTDI EEPROM strings or provision an
AirMonitor-specific USB identity.

Earlier EEPROM and registry-based discovery work may remain in the codebase for compatibility,
history, or future experimentation, but it is not the recommended installation architecture.

## Package Layout

```text
airmonitor/
  sensors/
    sgx/
      ps1_voc/
    sensirion/
      sps30/
  printers/
    bambu/
  filters/
    bento/
    levoit/
  database/
  grafana/
  policy/
  config/
  cli/
```

Preferred import paths:

```python
from airmonitor.sensors.sgx.ps1_voc import Measurement, parse_combined_response
from airmonitor.sensors.sensirion.sps30 import SPS30Sensor
from airmonitor.printers.bambu import PrinterStateCache
from airmonitor.filters.bento import BentoFilter
from airmonitor.filters.levoit import LevoitFilter
```

## Integrations

Sensors:

- `airmonitor.sensors.sgx.ps1_voc` for the AirMonitor VOC Sensor based on the SGX Sensortech `PS1-VOC-1000-MOD`
- `airmonitor.sensors.sensirion.sps30` for the AirMonitor PM Sensor based on the Sensirion `SPS30`

Printers:

- `airmonitor.printers.bambu` for the Bambu Lab local MQTT bridge and X1C plus AMS state

Filters:

- `airmonitor.filters.bento` for Bento Box outlet control
- `airmonitor.filters.levoit` for Levoit/Core 400S room-filter control

## Services

The code lives in one package, but services remain separate so failures are isolated:

```text
airmonitor.target                  AirMonitor application lifecycle
airmonitor-voc.service             SGX logger and SQLite writer
airmonitor-sps30.service           SPS30 logger and SQLite writer
airmonitor-printer-mqtt.service    Bambu local MQTT normalizer
airmonitor-bento.service           Kasa-powered Bento Box control
airmonitor-levoit.service          VeSync/Levoit room-purifier control
airmonitor-status.service          Appliance landing page and administration
airmonitor-export.service          Read-only bounded report generation
airmonitor-alerts.service          VOC/PM threshold, stale-sensor, and filter-mismatch alerting
```

The export service is isolated from the landing page and sensor processes because large
PNG, PDF, and workbook generation can temporarily consume significant CPU and memory.
Nginx exposes it beneath `/exports/` on the unified appliance origin. It opens SQLite in
read-only/query-only mode, allows one report generation at a time, and never talks to
sensor, printer, or filter hardware.

## Configuration

Keep local environment files outside the repository and preserve them across updates:

```text
/etc/airmonitor/sgx-voc.env
/etc/airmonitor/sps30.env
/etc/airmonitor/printer-mqtt.env
/etc/airmonitor/bento.env
/etc/airmonitor/levoit.env
/etc/airmonitor/hardware.yaml
/etc/airmonitor/filament-policy.yaml
```

Sensor environment files should specify the selected serial device path explicitly. The
hardware registry may remain available for compatibility, but automatic EEPROM-based matching
is not required for the current design.

## Database

SQLite remains the default local database:

```text
/var/lib/airmonitor/airmonitor.sqlite3
```

The application manages schema migrations and exposes normalized tables or views for Grafana.
SQL should live behind repository helpers where practical. Filter manual override state is
persisted in `filter_control_state` and accessed through `FilterControlRepository`.

## Grafana

Grafana dashboards are generated and imported through the Grafana API. Manual dashboard edits
are temporary and should be overwritten by the installer or update scripts.

Planned dashboard areas include:

- live appliance status
- print history
- filter activity
- filtered-versus-unfiltered comparisons
- peak and total sensor response
- return-to-baseline analysis
