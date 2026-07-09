# SGX PS1-VOC-1000-MOD

## Connector and cable

The SGX `PS1-VOC-1000-MOD` uses a 4-pin, 1.0 mm pitch sensor connector. Based on physical measurement of the four positions spanning approximately 4 mm and successful fit of the supplied mating cable, the connector appears to be JST-SH rather than JST-ZH.

The vendor documents used so far do not explicitly name the connector series, so this should be treated as a measured/observed identification rather than a vendor-confirmed part number.

Air Monitor uses the factory wire-ended harness directly; no sensor-side crimping is required.

Spare cable:

| Part | Value |
|---|---|
| Mouser part | `523-MOD-4PIN-CABLE` |
| Manufacturer part | `MOD-4PIN-Cable` |
| Description | Module 4-pin wire-ended cable |

The spare `MOD-4PIN-Cable` appears to be the same style of 4-pin, 1.0 mm pitch JST-SH-to-wire-end harness supplied with the module and is useful as a replacement or for additional builds.

## Connector orientation

The vendor documentation numbers the connector from the bottom or connector side of the module.

In the vendor bottom-view drawing, pin 1 / red VCC is on the left side of the connector. When viewing the sensor from the top or component side, pin 1 appears on the right-hand side of the connector. Pin 1 corresponds to the red VCC wire.

## Raspberry Pi 4B GPIO UART wiring

The SGX `MOD-4PIN-CABLE` is approximately 100 mm long. The cable maps neatly onto the even-numbered column of the Raspberry Pi header:

| Cable | Module signal | Raspberry Pi 4B |
|---|---|---|
| Red | VCC | Physical pin 4, 5 V |
| Black | GND | Physical pin 6, ground |
| Yellow | RX | Physical pin 8, GPIO14/TXD |
| Green | TX | Physical pin 10, GPIO15/RXD |

The module accepts 3.3-5.5 V power and specifies a 3.3 V UART output. Raspberry Pi GPIO is not 5 V tolerant; verify the module TX idle level before first connection if there is any doubt about the hardware revision.

## Long-term USB-C interface

The initial Air Monitor hardware validation used the Raspberry Pi 4B native GPIO UART at `/dev/serial0`.

The preferred long-term sensor enclosure design embeds a Waveshare FT232 USB UART Board (Type-C) inside the sensor enclosure. In that design the SGX still uses the same UART protocol, but the host sees the sensor as a USB serial device instead of the Pi GPIO UART.

For the Waveshare board, use 3.3 V UART logic and 5 V sensor power:

| Waveshare board | SGX signal | SGX cable color |
|---|---|---|
| 5V / VCC | VCC | Red |
| GND | GND | Black |
| TXD | RX | Yellow |
| RXD | TX | Green |

## Serial settings

- 9600 baud
- 8 data bits
- No parity
- 1 stop bit
- No flow control
- Default mode after power-up: question and answer

Mode changes are not treated as persistent configuration for Air Monitor. Normal operation assumes the sensor starts in question-and-answer mode after power-up and uses read-only combined queries.

## Combined read compatibility

The vendor documents disagree in byte 1 of the read-only combined request:

```text
July 2023:      FF 01 87 00 00 00 00 00 78
February 2022:  FF 00 87 00 00 00 00 00 79
```

Both document the same 13-byte response:

```text
FF 87 GG GG RR RR PP PP TT TT HH HH CC
```

`GG` and `PP` are concentration values, `RR` is full scale, `TT` is signed temperature in hundredths of a degree Celsius, `HH` is unsigned humidity in hundredths of percent RH, and `CC` is the checksum.

The driver tries the newer request first and falls back to the legacy request.

## Verified by Air Monitor

Initial hardware validation was performed with the factory SGX cable connected directly to a Raspberry Pi 4B GPIO UART.

Verified:

- Raspberry Pi 4B GPIO UART at `/dev/serial0`
- Linux user `automation` running the installed Air Monitor virtualenv
- 9600 8N1 serial settings
- 2023 combined-read protocol response
- Default power-up mode is question-and-answer
- No upload-mode configuration required for normal reads
- Read-only probe command successfully returned VOC, temperature, and humidity
- Connector appears to be 4-pin JST-SH, 1.0 mm pitch, based on physical measurement and supplied cable fit

Example successful probe output:

```json
{
  "frame_hex": "ff 87 00 18 03 e8 00 18 09 97 13 7e 2d",
  "full_scale": 1000,
  "gas_mass": 2.4,
  "gas_ppm": 2.4,
  "humidity_rh": 49.9,
  "protocol": "2023",
  "temperature_c": 24.55
}
```

## Vendor references

- [PS1/PS4-VOC-1000-MOD datasheet](https://www.mouser.com/catalog/specsheets/Amphenol_5262023_DS_0425_PS1_PS4_VOC_1000_MOD.pdf)
- [Gas Module communication protocol](https://www.sgxsensortech.com/uploads/f_note/Gas%20Module%20-%20Communication%20Protocol.pdf)

Vendor PDFs are linked rather than copied into this repository.
