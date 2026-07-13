# AirMonitor Architecture

AirMonitor is an open-source DIY air-quality monitoring platform for 3D-printing spaces.
The project uses commercially available sensor modules packaged as USB-connected
AirMonitor Sensors, with local collection, storage, dashboards, printer awareness, and
filter automation running on a Raspberry Pi or other Linux host.

The model is one repository, one Python package, one shared database, one shared
configuration model, and multiple optional integrations.

## End-to-End Data Path

```text
Commercial sensor module
        │ TTL UART
USB Interface
(USB-UART bridge + EEPROM identity)
        │ USB
Linux / udev discovery
        │
AirMonitor hardware registry
        │
Sensor driver and service
        │
SQLite database
        │
Grafana / filter automation / operating tools
```

USB is the recommended physical connection. Native UART remains available as an advanced
integration path, but it bypasses EEPROM-based identity and normally requires an explicit
device path.

## Hardware Discovery

Each recommended USB Interface is assigned a unique EEPROM identity containing manufacturer,
product, and serial strings. AirMonitor matches those values through
`/etc/airmonitor/hardware.yaml` rather than relying on changing `/dev/ttyUSB*` numbers.

This separates three concepts:

- **AirMonitor Sensor** — the complete DIY physical device
- **sensor module** — the commercial sensing component, such as the SPS30
- **USB Interface** — the USB-UART bridge and EEPROM identity associated with the device

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
airmonitor.service                 SGX logger and SQLite writer
airmonitor-sps30.service           SPS30 logger and SQLite writer
airmonitor-printer-mqtt.service    Bambu local MQTT normalizer
airmonitor-bento.service           Kasa-powered Bento Box control
airmonitor-levoit.service          VeSync/Levoit room-purifier control
```

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

## Database

SQLite remains the default local database:

```text
/var/lib/airmonitor/airmonitor.sqlite3
```

The application manages schema migrations and exposes normalized tables or views for
Grafana. SQL should live behind repository helpers where practical. Filter manual override
state is persisted in `filter_control_state` and accessed through
`FilterControlRepository`.

## Grafana

Grafana dashboards are generated and imported through the Grafana API. Manual dashboard
edits are temporary and should be overwritten by the installer or update scripts.

Planned dashboard areas include:

- live appliance status
- print history
- air-quality history
- filter activity
- exposure and return-to-baseline analysis
