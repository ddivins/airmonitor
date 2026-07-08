# Waveshare FT232 USB UART Board (Type-C)

## Purpose

This board is the preferred long-term Air Monitor USB-UART interface for UART sensors. It can be embedded inside each sensor enclosure so the finished sensor exposes only a USB-C connector to the printer host.

```text
Printer host USB
    |
USB-C cable
    |
Sensor enclosure
    |
Waveshare FT232 USB UART Board (Type-C)
    |
TTL UART
    |
SGX PS1-VOC-1000-MOD, Sensirion SPS30, or another UART sensor
```

## Air Monitor standard

All Air Monitor UART sensor interfaces should use:

- USB-C externally
- FT232 USB-UART internally
- 3.3 V TTL UART logic
- 5 V sensor power when required by the sensor
- One USB-UART board per sensor
- FTDI EEPROM descriptors programmed to identify the attached sensor

Set the Waveshare logic-level selector to **3.3 V** for Air Monitor sensors.

## Important electrical warning

This board is for **TTL UART only**.

Do **not** connect it directly to RS-232 serial circuits, DB9 serial ports, or equipment that uses positive/negative RS-232 voltage levels. TTL UART uses 0-3.3 V or 0-5 V logic. RS-232 commonly uses negative and positive voltages and requires an RS-232 level shifter/transceiver.

## Board characteristics

From the Waveshare documentation:

- USB to UART TTL bridge
- 5 V board power from USB
- Selectable 3.3 V or 5 V TTL UART levels
- Baud rate range: 300 bps to 3 Mbps
- Linux support through the default FT232 driver
- Appears as `/dev/ttyUSB*` on Linux

## Header signals

Core UART signals used by Air Monitor:

| Board signal | Direction | Connects to sensor |
|---|---|---|
| VCC / 5V | Power | Sensor VCC or VDD, if sensor requires 5 V |
| GND | Ground | Sensor ground |
| TXD | Output from FT232 | Sensor RX |
| RXD | Input to FT232 | Sensor TX |

Hardware-flow-control pins such as RTS and CTS are not used by the current Air Monitor sensors.

## Sensor wiring patterns

### SGX PS1-VOC-1000-MOD

Use 3.3 V UART logic and 5 V sensor power.

| Waveshare board | SGX signal | SGX cable color |
|---|---|---|
| 5V / VCC | VCC | Red |
| GND | GND | Black |
| TXD | RX | Yellow |
| RXD | TX | Green |

### Sensirion SPS30

Use 3.3 V UART logic and 5 V sensor power. Leave `SEL` floating for UART mode.

| Waveshare board | SPS30 pin | SPS30 signal |
|---|---:|---|
| 5V / VCC | 1 | VDD |
| TXD | 2 | RX |
| RXD | 3 | TX |
| Not connected | 4 | SEL, leave floating |
| GND | 5 | GND |

## Linux validation

After connecting a board to the printer host:

```bash
lsusb
ls -l /dev/ttyUSB*
ls -l /dev/serial/by-id/
```

The board should appear as an FTDI USB serial device. The long-term Air Monitor software should avoid relying on `/dev/ttyUSB0` ordering and instead use FTDI EEPROM descriptors or `/dev/serial/by-id/` names.

## FTDI EEPROM naming

Program the FTDI EEPROM to describe the attached sensor, not just the USB-UART board.

Recommended examples:

| Attached sensor | Manufacturer | Product | Serial |
|---|---|---|---|
| SGX VOC module | `SGX` | `PS1-VOC-1000-MOD` | `PS1-VOC-01` |
| Sensirion PM module | `Sensirion` | `SPS30` | `SPS30-01` |

This allows Air Monitor to auto-discover sensors by USB descriptor and load the correct driver without hardcoded port names.

## Enclosure notes

For final sensor enclosures, mount the Waveshare board on standoffs with the USB-C connector accessible from the outside of the enclosure. The sensor-specific UART harness remains internal.

This makes each sensor enclosure a standalone USB-C peripheral.

## Vendor references

- [Waveshare FT232 USB UART Board Type-C product page](https://www.waveshare.com/ft232-usb-uart-board-type-c.htm)
- [Waveshare FT232 USB UART Board wiki](https://www.waveshare.com/wiki/FT232_USB_UART_Board_(Type_A))

Vendor pages are linked rather than copied into this repository.
