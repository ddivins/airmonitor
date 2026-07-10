# AirMonitor hardware registry

AirMonitor can identify serial sensors in two ways:

1. Match a USB serial adapter by its USB EEPROM identity.
2. Use an explicit device path for true UARTs or adapters with unhelpful or unwritable EEPROMs.

The persistent registry is:

```text
/etc/airmonitor/hardware.yaml
```

The sensor service reads `AIRMONITOR_HARDWARE_ID` from `/etc/airmonitor.env`. When `AIRMONITOR_PORT=auto`, it resolves that hardware id at startup.

## Discover connected devices

```bash
airmonitor-hardware discover
```

The output includes the device path, real tty, manufacturer, product, serial, VID, and PID reported by udev.

For the dedicated SGX adapter, the intended EEPROM identity is:

```text
Manufacturer: DSD
Product:      AirMonitor
Serial:       SGX-VOC-1000-01
```

## Register an EEPROM-identified USB adapter

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

## Manually register a device path

Use this for:

- a Raspberry Pi GPIO UART
- a USB adapter with an unwritable EEPROM
- a USB adapter whose EEPROM identity is not unique
- a stable `/dev/serial/by-id/...` path created by Linux
- a custom udev symlink

True UART example:

```bash
sudo /opt/airmonitor/venv/bin/airmonitor-hardware \
  --registry /etc/airmonitor/hardware.yaml \
  add sgx-voc-01 \
  --driver airmonitor.sensors.sgx.ps1_voc \
  --transport gpio-uart \
  --device /dev/serial0 \
  --force
```

Generic USB example:

```bash
sudo /opt/airmonitor/venv/bin/airmonitor-hardware \
  --registry /etc/airmonitor/hardware.yaml \
  add sgx-voc-01 \
  --transport usb-uart \
  --device /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_ABC123-if00-port0 \
  --force
```

An explicit `AIRMONITOR_PORT` in `/etc/airmonitor.env` always bypasses registry discovery. Set it to `auto` to use the registry.

## FTDI provisioning

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

The defaults are `MANUFACTURER=DSD`, `PRODUCT=AirMonitor`, and `SYMLINK_NAME=airmonitor-sgx`.

## Service configuration

Recommended `/etc/airmonitor.env` settings:

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
