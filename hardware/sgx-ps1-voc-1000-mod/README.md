# SGX PS1-VOC-1000-MOD

## Raspberry Pi 4B wiring

The SGX `MOD-4PIN-CABLE` is approximately 100 mm long. The cable maps neatly
onto the even-numbered column of the Raspberry Pi header:

| Cable | Module signal | Raspberry Pi 4B |
|---|---|---|
| Red | VCC | Physical pin 4, 5 V |
| Black | GND | Physical pin 6, ground |
| Yellow | RX | Physical pin 8, GPIO14/TXD |
| Green | TX | Physical pin 10, GPIO15/RXD |

The module accepts 3.3-5.5 V power and specifies a 3.3 V UART output. Raspberry
Pi GPIO is not 5 V tolerant; verify the module TX idle level before first
connection if there is any doubt about the hardware revision.

## Serial settings

- 9600 baud
- 8 data bits
- No parity
- 1 stop bit
- No flow control
- Default mode after power-up: question and answer

## Combined read compatibility

The vendor documents disagree in byte 1 of the read-only combined request:

```text
July 2023:    FF 01 87 00 00 00 00 00 78
February 2022: FF 00 87 00 00 00 00 00 79
```

Both document the same 13-byte response:

```text
FF 87 GG GG RR RR PP PP TT TT HH HH CC
```

`GG` and `PP` are concentration values, `RR` is full scale, `TT` is signed
temperature in hundredths of a degree Celsius, `HH` is unsigned humidity in
hundredths of percent RH, and `CC` is the checksum.

The driver tries the newer request first and falls back to the legacy request.

## Vendor references

- [PS1/PS4-VOC-1000-MOD datasheet](https://www.mouser.com/catalog/specsheets/Amphenol_5262023_DS_0425_PS1_PS4_VOC_1000_MOD.pdf)
- [Gas Module communication protocol](https://www.sgxsensortech.com/uploads/f_note/Gas%20Module%20-%20Communication%20Protocol.pdf)

Vendor PDFs are linked rather than copied into this repository.

