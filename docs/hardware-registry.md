# AirMonitor Hardware Guide

AirMonitor Sensors are DIY-built assemblies based on commercially available sensing
modules. The recommended design uses USB for host connectivity and an EEPROM-programmed
USB-UART interface for reliable hardware identification.

Current sensor modules:

| AirMonitor Sensor | Sensor module | Measurements |
| --- | --- | --- |
| AirMonitor VOC Sensor | Amphenol SGX Sensortech `PS1-VOC-1000-MOD` | TVOC, temperature, humidity |
| AirMonitor PM Sensor | Sensirion `SPS30` | PM mass, particle counts, typical particle size |

AirMonitor is not a certified air-quality instrument and should not be used for regulatory,
medical, or life-safety decisions.

## Recommended USB Architecture

```text
Sensor module
    │ TTL UART
USB-UART Interface
    │ EEPROM identity
USB cable
    │
Raspberry Pi or Linux host
    │
AirMonitor hardware registry and driver
```

USB is the primary supported build because it provides:

- power and communications over a standard external connection
- stable discovery independent of `/dev/ttyUSB*` numbering
- support for hubs and multiple sensors
- easier replacement, testing, and troubleshooting
- no dependency on a specific Raspberry Pi GPIO header

The underlying sensor protocols remain UART-based. USB-UART interfaces bridge those
protocols to the host.

## EEPROM-Based Identification

Each recommended FTDI USB-UART interface is programmed with identifying strings in its
EEPROM. AirMonitor uses those values to associate a physical USB device with the correct
sensor driver and logical hardware ID.

Example identity:

```text
Manufacturer: DSD
Product:      AirMonitor
Serial:       SGX-VOC-1000-01
```

The serial must be unique for each physical AirMonitor Sensor. A useful convention is:

```text
<SENSOR-TYPE>-<MODEL>-<INSTANCE>
```

Examples:

```text
SGX-VOC-1000-01
SPS30-01
```

EEPROM identity avoids assumptions such as `/dev/ttyUSB0`. Sensors may be moved between
USB ports or hubs without changing AirMonitor configuration.

## Hardware Registry

AirMonitor can identify serial sensors in two ways:

1. Match a USB serial adapter by its USB EEPROM identity.
2. Use an explicit device path for native UARTs or adapters with unhelpful or unwritable EEPROMs.

The persistent registry is:

```text
/etc/airmonitor/hardware.yaml
```

The sensor service reads `AIRMONITOR_HARDWARE_ID` from its environment file. When
`AIRMONITOR_PORT=auto`, it resolves that hardware ID at startup.

## Discover Connected Devices

```bash
airmonitor-hardware discover
```

The output includes the device path, real tty, manufacturer, product, serial, VID, and PID
reported by udev.

## Register an EEPROM-Identified USB Interface

```bash
sudo /opt/airmonitor/venv/bin/airmonitor-hardware \
  --registry /etc/airmonitor/hardware.yaml \
  add sgx-voc-01 \
  --driver airmonitor.sensors.sgx.ps1_voc \
  --transport usb-uart \
  --usb-vendor DSD \
  --usb-product AirMonitor \
  --usb-serial SGX-VOC-1000-01 \
  --fallback-device /dev/airmonitor-sgx \
  --force
```

Verify:

```bash
sudo /opt/airmonitor/venv/bin/airmonitor-hardware --registry /etc/airmonitor/hardware.yaml list
sudo /opt/airmonitor/venv/bin/airmonitor-hardware --registry /etc/airmonitor/hardware.yaml resolve sgx-voc-01
```

## FTDI EEPROM Provisioning

`tools/provision-ftdi.sh` safely:

1. reads and preserves an EEPROM backup
2. builds a replacement image
3. refuses to flash unless `FLASH=1`
4. writes the selected manufacturer, product, and serial strings
5. installs a serial-specific udev rule

Build and back up without flashing:

```bash
CURRENT_SERIAL=BG02D9OG \
SERIAL=SGX-VOC-1000-01 \
bash tools/provision-ftdi.sh
```

After reviewing the backup and generated image:

```bash
CURRENT_SERIAL=BG02D9OG \
SERIAL=SGX-VOC-1000-01 \
FLASH=1 \
bash tools/provision-ftdi.sh
```

The defaults are `MANUFACTURER=DSD`, `PRODUCT=AirMonitor`, and
`SYMLINK_NAME=airmonitor-sgx`.

EEPROMs can be reprogrammed when naming or metadata conventions change, but always retain
a backup of the original image and verify that the selected adapter is the intended device
before flashing.

## Service Configuration

Recommended `/etc/airmonitor/sgx-voc.env` settings:

```text
AIRMONITOR_PORT=auto
AIRMONITOR_HARDWARE_ID=sgx-voc-01
AIRMONITOR_HARDWARE_REGISTRY=/etc/airmonitor/hardware.yaml
AIRMONITOR_SENSOR_TRANSPORT=usb-uart
AIRMONITOR_SENSOR_SERIAL=SGX-VOC-1000-01
```

Restart and verify:

```bash
sudo systemctl restart airmonitor.service
sudo journalctl -u airmonitor.service -n 30 --no-pager
sudo /opt/airmonitor/venv/bin/airmonitor-doctor
```

## Enclosures

Purpose-built 3D-printable enclosures are being developed for the AirMonitor VOC Sensor and
AirMonitor PM Sensor. Printable releases and recommended print profiles will be linked here
from MakerWorld when they are ready.

Until those releases are published, this repository remains the source for hardware notes,
wiring information, and any available CAD source files.

Planned enclosure documentation will include:

- MakerWorld print-file and profile link
- supported sensor and USB Interface revision
- bill of materials
- assembly instructions
- airflow and mounting notes
- available Fusion 360 or STEP source files

## Advanced: Native UART Connections

AirMonitor sensor modules communicate internally using TTL UART. Advanced builders may
connect a module directly to a Raspberry Pi GPIO UART or another embedded host instead of
using the recommended USB Interface.

Native UART operation has important tradeoffs:

- EEPROM-based automatic identification is unavailable.
- The device path must be configured explicitly.
- Voltage levels, grounding, pinout, and power requirements must be verified by the builder.
- Host UART configuration may be platform-specific.
- A direct GPIO connection is less portable than a USB-connected AirMonitor Sensor.

Use native UART wiring as an advanced integration option, not as the default public build.
Retain the sensor-specific wiring and pinout notes under `hardware/` for this purpose.

### Manually Register a Native UART

```bash
sudo /opt/airmonitor/venv/bin/airmonitor-hardware \
  --registry /etc/airmonitor/hardware.yaml \
  add sgx-voc-01 \
  --driver airmonitor.sensors.sgx.ps1_voc \
  --transport gpio-uart \
  --device /dev/serial0 \
  --force
```

### Register a Generic USB Adapter by Device Path

Use this when an adapter EEPROM cannot be programmed or does not provide a unique identity:

```bash
sudo /opt/airmonitor/venv/bin/airmonitor-hardware \
  --registry /etc/airmonitor/hardware.yaml \
  add sgx-voc-01 \
  --transport usb-uart \
  --device /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_ABC123-if00-port0 \
  --force
```

An explicit `AIRMONITOR_PORT` always bypasses registry discovery. Set it to `auto` to use
the hardware registry.
