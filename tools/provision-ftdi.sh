#!/usr/bin/env bash
set -euo pipefail

VENDOR_ID="${VENDOR_ID:-0x0403}"
PRODUCT_ID="${PRODUCT_ID:-0x6001}"
MANUFACTURER="${MANUFACTURER:-DSD}"
PRODUCT="${PRODUCT:-AirMonitor}"
SERIAL="${SERIAL:-SGX-VOC-1000-01}"
CURRENT_SERIAL="${CURRENT_SERIAL:-}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/ftdi-backups}"
UDEV_RULE="${UDEV_RULE:-/etc/udev/rules.d/99-airmonitor-sgx.rules}"
SYMLINK_NAME="${SYMLINK_NAME:-airmonitor-sgx}"
FLASH="${FLASH:-0}"

log() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

command -v ftdi_eeprom >/dev/null || fail "ftdi_eeprom is not installed"
command -v udevadm >/dev/null || fail "udevadm is not installed"
mkdir -p "$BACKUP_DIR"
cd "$BACKUP_DIR"

if [[ -z "$CURRENT_SERIAL" ]]; then
  mapfile -t serials < <(
    for dev in /dev/ttyUSB*; do
      [[ -e "$dev" ]] || continue
      udevadm info -q property -n "$dev" 2>/dev/null | sed -n 's/^ID_SERIAL_SHORT=//p'
    done | sort -u
  )
  [[ ${#serials[@]} -eq 1 ]] || fail "set CURRENT_SERIAL explicitly; found ${#serials[@]} FTDI serial candidates"
  CURRENT_SERIAL="${serials[0]}"
fi

selector="s:${VENDOR_ID}:${PRODUCT_ID}:${CURRENT_SERIAL}"
stamp="$(date +%Y%m%d-%H%M%S)"
backup_conf="ft232-${CURRENT_SERIAL}-backup.conf"
backup_file="ft232-${CURRENT_SERIAL}-${stamp}.eeprom"
new_conf="ft232-${SERIAL}.conf"
new_image="ft232-${SERIAL}.eeprom"

log "Backing up current EEPROM: $CURRENT_SERIAL"
cat > "$backup_conf" <<EOF
vendor_id=${VENDOR_ID}
product_id=${PRODUCT_ID}
filename="${backup_file}"
max_power=90
EOF
sudo ftdi_eeprom --device "$selector" --read-eeprom "$backup_conf"
sudo chown "$(id -u):$(id -g)" "$backup_file"
chmod 0444 "$backup_file"

log "Building replacement EEPROM image"
cat > "$new_conf" <<EOF
vendor_id=${VENDOR_ID}
product_id=${PRODUCT_ID}
manufacturer="${MANUFACTURER}"
product="${PRODUCT}"
serial="${SERIAL}"
use_serial=true
self_powered=false
remote_wakeup=true
max_power=90
cbus0=TXLED
cbus1=RXLED
cbus2=TXDEN
cbus3=PWREN
cbus4=SLEEP
filename="${new_image}"
EOF
sudo ftdi_eeprom --device "$selector" --verbose --build-eeprom "$new_conf"
[[ -f "$new_image" ]] || fail "EEPROM image was not created: $new_image"
sudo chown "$(id -u):$(id -g)" "$new_image"

if [[ "$FLASH" != "1" ]]; then
  cat <<EOF

Build complete; EEPROM was NOT flashed.
Backup: $BACKUP_DIR/$backup_file
Image:  $BACKUP_DIR/$new_image

Review the files, then flash with:
  CURRENT_SERIAL='$CURRENT_SERIAL' SERIAL='$SERIAL' FLASH=1 bash tools/provision-ftdi.sh
EOF
  exit 0
fi

log "Flashing FTDI EEPROM"
sudo ftdi_eeprom --device "$selector" --verbose --flash-eeprom "$new_conf"

log "Installing udev rule for the new serial"
sudo tee "$UDEV_RULE" >/dev/null <<EOF
SUBSYSTEM=="tty", ATTRS{idVendor}=="${VENDOR_ID#0x}", ATTRS{idProduct}=="${PRODUCT_ID#0x}", ATTRS{serial}=="${SERIAL}", SYMLINK+="${SYMLINK_NAME}", GROUP="dialout", MODE="0660"
EOF
sudo udevadm control --reload-rules

cat <<EOF

Provisioning complete.
Unplug and reconnect the adapter, then verify:
  ls -l /dev/${SYMLINK_NAME}
  udevadm info -q property -n /dev/${SYMLINK_NAME} | grep -E 'ID_VENDOR=|ID_MODEL=|ID_SERIAL_SHORT='
EOF
