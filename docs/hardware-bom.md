# v1.0 reference hardware

This is the exact bill of materials this project has actually been built and
run against. It's meant to be buildable by someone else, not just a
description of one existing appliance — but the scope is deliberately
narrow: only what's been validated. Anything not listed here (other
printers, other purifiers, other USB-UART adapters) may work but is
unsupported and untested.

See `docs/install.md` for the software installation steps once the hardware
below is assembled and wired.

## Host

| Component | Reference part |
|---|---|
| Single-board computer | Raspberry Pi 4 or 5 Model B (2 GB or more) |
| OS | Raspberry Pi OS (Debian 12 "bookworm" or 13 "trixie"), 64-bit (`aarch64`) |
| Storage | microSD or USB SSD large enough for months of sensor data and Grafana (a few GB minimum; see `docs/backup-restore.md` for growth/retention) |

Nothing here is board-specific: the sensor and printer interfaces are all
USB/network (no GPIO wiring in the recommended build), and the one
board-read host metric (`/sys/class/thermal/thermal_zone0/temp` in
`status.py`) is generic across both. Validated so far on Raspberry Pi 4
Model B; a Pi 5 migration is planned imminently and this doc will be
updated with the result rather than assumed to just work.

## Sensors

| Component | Reference part | Notes |
|---|---|---|
| VOC sensor | Amphenol SGX Sensortech `PS1-VOC-1000-MOD` | See `hardware/sgx-ps1-voc-1000-mod/README.md` and the README's "Why the Amphenol SGX PS1-VOC-1000-MOD?" section for why this part was chosen. |
| Particulate sensor | Sensirion SPS30 | See `hardware/sensirion-sps30/README.md` for wiring and the required 5V VCCIO setting. |
| USB-UART interface | Silicon Labs CP2105 dual USB-to-UART bridge | One CP2105 dual adapter serves both sensors (one UART port each). Its USB serial number is pinned in `config/udev/99-airmonitor-serial.rules` so the sensors always resolve to stable `/dev/airmonitor-sgx` / `/dev/airmonitor-sps30` device paths regardless of USB enumeration order. `tools/install.sh` refuses to proceed if a different adapter is detected, rather than silently misconfiguring the rule. |

The Waveshare FT232 USB-UART board (`hardware/waveshare-ft232-usb-uart-board-type-c/README.md`)
is documented as an alternative under exploration for embedding inside a
per-sensor enclosure, but the appliance this was validated against uses the
CP2105 dual adapter for both sensors. Treat the FT232 path as experimental
until it's actually running the shipped configuration.

## Printer

| Component | Reference part |
|---|---|
| 3D printer | Bambu Lab X1 Carbon with AMS |

AirMonitor connects over the printer's local (LAN) MQTT interface — see
`src/airmonitor/printers/bambu/mqtt_service.py` and `config/env/printer-mqtt.env.example`.
Other Bambu models exposing the same local MQTT API may work but are untested.
Other printer brands are unsupported (tracked as optional future work in
`docs/roadmap.md` Phase 9).

## Filter automation

| Component | Reference part | Role |
|---|---|---|
| Smart outlet | TP-Link Kasa `KP125M` | Switches a "Bento Box" style enclosure filter on/off based on printer activity. See `src/airmonitor/filters/bento/`. |
| Room air purifier | Levoit Core 400S | Runs when the active filament's policy classification recommends room-level filtration, not just enclosure filtration. See `src/airmonitor/filters/levoit/`, `docs/filter-control.md`, and `docs/vesync-rate-limiting.md` for VeSync cloud rate-limit handling. |

Other Kasa smart-outlet models supporting `python-kasa`'s on/off + energy-
monitoring interface will likely work but are untested. Other VeSync/Levoit
purifier models are untested; `docs/vesync-rate-limiting.md` documents
known cloud API quirks that may differ by model.

## Enclosure

No enclosure CAD design currently exists (`cad/` is scaffolding only). v1.0
does not require one — the reference build above can run without a
purpose-built enclosure. A published enclosure design is separate,
optional future work.
