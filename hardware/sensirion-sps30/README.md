# Sensirion SPS30

## USB-UART wiring

The SPS30 uses a 5-pin JST ZH connector. The Air Monitor build should use a dedicated FTDI USB-to-UART cable for the SPS30 so it can be discovered independently from other sensors.

| SPS30 pin | Sensor signal | FTDI TTL-232R-5V wire | FTDI signal |
|---:|---|---|---|
| 1 | VDD | Red | +5 V |
| 2 | RX | Orange | TXD |
| 3 | TX | Yellow | RXD |
| 4 | SEL | Not connected | Leave floating for UART mode |
| 5 | GND | Black | Ground |

Leave `SEL` floating for UART mode. Connecting `SEL` to ground selects I2C mode instead.

The SPS30 supply is 5 V. Its UART interface accepts both TTL 5 V and LVTTL 3.3 V levels, so the FTDI `TTL-232R-5V` cable can be connected directly without a level shifter.

## Connector

Sensor connector:

- JST ZH series
- 5 positions
- 1.5 mm pitch

Mating parts:

| Part | JST part number | Notes |
|---|---|---|
| Housing | `ZHR-5` | 5-position receptacle housing |
| Crimp contact | `SZH-002T-P0.5` | Common ZH crimp contact; verify wire gauge before crimping |

The FTDI TTL-232R cable conductors are 24 AWG. If the chosen ZH contact or insulation crimp does not fit cleanly, splice the FTDI cable to a short 26-28 AWG pigtail and crimp the ZH terminal onto the pigtail.

## Serial settings

- UART mode
- 115200 baud
- 8 data bits
- No parity
- 1 stop bit
- No flow control

## Measurements to capture

The SPS30 provides mass concentration values for:

- PM1.0
- PM2.5
- PM4.0
- PM10

It also provides number concentration values for:

- Particles greater than 0.5 um
- Particles greater than 1.0 um
- Particles greater than 2.5 um
- Particles greater than 4.0 um
- Particles greater than 10.0 um

Also capture:

- Typical particle size

## Logging notes

Poll once per second and store decoded values in the SPS30-specific sample table. The synchronized `environment_snapshot` row should include at least PM1.0, PM2.5, PM4.0, PM10, and the current printer state.

PM values are cumulative buckets. For example, PM2.5 includes PM1.0, and PM10 includes PM2.5.

## FTDI EEPROM naming

Recommended FTDI EEPROM descriptor values for the SPS30 cable:

| Field | Value |
|---|---|
| Manufacturer | `Sensirion` |
| Product | `SPS30` |
| Serial | `SPS30-01` |

This allows the software to auto-discover the SPS30 by USB descriptor instead of relying on `/dev/ttyUSB0` ordering.

## Vendor references

- [Sensirion SPS30 datasheet](https://sensirion.com/media/documents/8600FF88/64A3B8D6/Sensirion_PM_Sensors_Datasheet_SPS30.pdf)
- [Mouser SPS30 product page](https://www.mouser.com/ProductDetail/Sensirion/SPS30)

Vendor PDFs are linked rather than copied into this repository.
