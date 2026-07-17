# AirMonitor Hardware Guide

AirMonitor Sensors are DIY-built assemblies based on commercially available sensing modules.
The recommended design uses USB for host connectivity through ordinary USB-UART interfaces.

The project is primarily intended to compare **filter effectiveness** during controlled
3D-printing experiments. The sensors provide repeatable signals that can be compared between
filtered and unfiltered runs; they are not presented as certified exposure instruments.

Current sensor modules:

| AirMonitor Sensor | Sensor module | Measurements |
| --- | --- | --- |
| AirMonitor VOC Sensor | Amphenol SGX Sensortech `PS1-VOC-1000-MOD` | Cross-sensitive VOC response, temperature, humidity |
| AirMonitor PM Sensor | Sensirion `SPS30` | PM mass, particle counts, typical particle size |

AirMonitor is not a certified air-quality instrument and should not be used for regulatory,
medical, occupational-exposure, or life-safety decisions.

## Recommended USB Architecture

```text
Sensor module
    │ TTL UART
USB-UART interface
    │ USB cable
Raspberry Pi or Linux host
    │ configured serial device path
AirMonitor sensor service and driver
```

USB is the primary supported build because it provides:

- power and communications over a standard external connection
- support for hubs and multiple sensors
- easier replacement, testing, and troubleshooting
- no dependency on a specific Raspberry Pi GPIO header
- clean routing through a purpose-built enclosure

The underlying sensor protocols remain UART-based. USB-UART interfaces bridge those protocols
to the host.

## Device Identification and Configuration

The current recommended design uses an explicitly configured Linux serial device path for each
sensor. Suitable paths include:

- a stable `/dev/serial/by-id/...` symlink supplied by Linux
- a project-specific udev symlink
- a known `/dev/ttyUSB*` or `/dev/ttyACM*` device on a fixed installation
- `/dev/serial0` for an advanced native GPIO UART installation

A stable by-id or custom udev path is preferable when the host has multiple serial devices.
The selected path is configured in the corresponding AirMonitor service environment file.

Example:

```text
AIRMONITOR_PORT=/dev/serial/by-id/usb-Silicon_Labs_CP2105_Dual_USB_to_UART_Bridge_Controller_EXAMPLE-if00-port0
AIRMONITOR_SENSOR_TRANSPORT=usb-uart
```

Use the actual path reported by the target host. Do not copy example serial strings verbatim.

Useful discovery commands include:

```bash
ls -l /dev/serial/by-id/
udevadm info --query=property --name=/dev/ttyUSB0
```

## EEPROM and Automatic Discovery Status

Earlier AirMonitor development explored reprogramming FTDI EEPROM manufacturer, product, and
serial strings, then matching those values through `/etc/airmonitor/hardware.yaml`.

That approach is **not part of the recommended public build**. Builders do not need to flash an
FTDI EEPROM, assign AirMonitor-specific USB metadata, or rely on automatic registry matching.
The additional provisioning complexity did not provide enough practical benefit for the
current fixed-appliance design.

Some EEPROM provisioning scripts, hardware-registry code, or configuration fields may remain
in the repository for development history, compatibility, or future experimentation. Their
presence should not be interpreted as a required installation step.

For current builds:

1. connect each sensor through its USB-UART interface
2. identify a reliable Linux device path
3. set that path explicitly in the sensor service configuration
4. restart and verify the service

## Service Configuration

Configure the applicable sensor environment file with an explicit port.

Example SGX settings:

```text
AIRMONITOR_PORT=/dev/serial/by-id/<actual-sgx-adapter-path>
AIRMONITOR_SENSOR_TRANSPORT=usb-uart
```

Example SPS30 settings:

```text
AIRMONITOR_PORT=/dev/serial/by-id/<actual-sps30-adapter-path>
AIRMONITOR_SENSOR_TRANSPORT=usb-uart
```

Restart and verify:

```bash
sudo systemctl restart airmonitor-voc.service
sudo systemctl restart airmonitor-sps30.service
sudo journalctl -u airmonitor-voc.service -n 30 --no-pager
sudo journalctl -u airmonitor-sps30.service -n 30 --no-pager
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
- supported sensor and USB-interface revision
- bill of materials
- assembly instructions
- airflow and mounting notes
- available Fusion 360 or STEP source files

## Advanced: Native UART Connections

AirMonitor sensor modules communicate internally using TTL UART. Advanced builders may connect
a module directly to a Raspberry Pi GPIO UART or another embedded host instead of using the
recommended USB interface.

Native UART operation has important tradeoffs:

- the device path must be configured explicitly
- voltage levels, grounding, pinout, and power requirements must be verified by the builder
- host UART configuration may be platform-specific
- a direct GPIO connection is less portable than a USB-connected AirMonitor Sensor

Use native UART wiring as an advanced integration option, not as the default public build.
Retain the sensor-specific wiring and pinout notes under `hardware/` for this purpose.

Example configuration:

```text
AIRMONITOR_PORT=/dev/serial0
AIRMONITOR_SENSOR_TRANSPORT=gpio-uart
```

The sensor-specific hardware pages contain the relevant pinout and wiring information.
