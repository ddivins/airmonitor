# AirMonitor architecture

AirMonitor is the umbrella application for the printer air-quality appliance.
The active repository is `ddivins/airmonitor`; older standalone repositories
are backup/reference sources after migration.

The long-term model is one repository, one Python package, one shared database, one shared configuration model, and multiple optional integrations.

## Package layout

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

- `airmonitor.sensors.sgx.ps1_voc` for SGX Sensortech PS1-VOC-1000-MOD
- `airmonitor.sensors.sensirion.sps30` for Sensirion SPS30 particulate matter sensing

Printers:

- `airmonitor.printers.bambu` for the Bambu Lab local MQTT bridge and X1C plus AMS state

Filters:

- `airmonitor.filters.bento` for Bento Box outlet control
- `airmonitor.filters.levoit` for Levoit/Core 400S room filter control

## Services

The code lives in one package, but services may remain separate so failures are isolated:

```text
airmonitor.service                 SGX logger and SQLite writer
airmonitor-printer-mqtt.service    Bambu local MQTT normalizer
airmonitor-bento.service           Kasa-powered Bento Box control
airmonitor-levoit.service          VeSync/Levoit room purifier control
```

## Configuration

Keep local environment files outside the repo and preserve them across reinstall or reset operations:

```text
/etc/airmonitor.env
/etc/bambu-bento.env
/etc/levoit-filter.env
/etc/printer-mqtt-service.env
```

Future consolidated config:

```text
/etc/airmonitor/config.yaml
/etc/airmonitor/filament-policy.yaml
```

## Database

SQLite remains the default local database:

```text
/var/lib/airmonitor/airmonitor.sqlite3
```

The app should manage schema migrations and expose normalized tables or views
for Grafana. SQL should live behind repository helpers where practical. Filter
manual override state is persisted in `filter_control_state` and accessed
through `FilterControlRepository`.

## Grafana

Grafana dashboards are generated and imported through the Grafana API. Manual dashboard edits are temporary and should be overwritten by the installer/update scripts.

Long-term dashboards:

- Live appliance dashboard
- Print history
- Air quality history
- Filter activity
- Exposure and return-to-baseline analysis

## Migration policy

Existing standalone pieces such as `bambu-bento` and `levoit-filter` should migrate into this repository as modules. Compatibility wrappers can remain temporarily, but new work should target the umbrella package paths.
