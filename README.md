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

The initial command is a read-only hardware probe. It tries the July 2023
combined-read request first and falls back to the legacy February 2022 request.
It does not change upload mode, sleep state, calibration, or indicator lights.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
airmonitor probe --port /dev/serial0
```

The sensor needs up to two minutes to settle after power-up in clean air. Treat
early values as warm-up data.

## Deployment convention

Perform repository clone, update, and install steps as your normal local
administrative user. Do not clone or maintain the repository as the service
account.

Long-running services should run under a low-privilege service account. The
example systemd units in this project family use `automation` as the shared
service account name.

If your system uses a different service account, update the relevant systemd
unit before installing it.

## Public repository notes

Do not commit populated environment files, printer serial numbers, printer
access codes, device IP addresses, private hostnames, logs containing secrets,
or local-only credentials.

## Safety and interpretation

This is a cross-sensitive TVOC monitor calibrated with isobutylene. It is useful
for trends, ventilation, and filter control, but it is not a compound-selective
or life-safety instrument.
