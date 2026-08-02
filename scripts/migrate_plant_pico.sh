#!/usr/bin/env bash
# Migrate an old plant wall Pico (CircuitPython or ancient MicroPython)
# to Plantnet + fleet baseline firmware (default pico-sensors-0.91).
#
# Two phases:
#   1) Flash BT-capable MicroPython UF2 (wipes CircuitPython / old runtime)
#   2) Load app + Plant secrets (same as commission_plant_pico.sh)
#
# Usage:
#   ./scripts/migrate_plant_pico.sh Plant-080
#   ./scripts/migrate_plant_pico.sh Plant-080 pico-sensors-0.92
#
# Physical steps when prompted:
#   - Unplug wall power
#   - Hold BOOTSEL on the Pico W, plug USB into this Mac (or hold BOOTSEL + reset)
#   - Wait for RPI-RP2 (or similar) volume
#   - Script copies the UF2; board reboots into MicroPython
#   - Then app + secrets are loaded automatically

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

NODE_ID="${1:-}"
RELEASE_NAME="${2:-pico-sensors-0.91}"
if [[ -z "$NODE_ID" || "$NODE_ID" != Plant-* ]]; then
  echo "Usage: $0 Plant-NNN [release-name]" >&2
  echo "Example: $0 Plant-080" >&2
  echo "Example: $0 Plant-080 pico-sensors-0.92" >&2
  exit 1
fi

UF2_DIR="$ROOT/firmware/uf2"
UF2="$(ls -1 "$UF2_DIR"/RPI_PICO_W-*.uf2 2>/dev/null | sort | tail -1 || true)"
if [[ -z "$UF2" || ! -f "$UF2" ]]; then
  echo "No Pico W UF2 in $UF2_DIR" >&2
  echo "Download from https://micropython.org/download/RPI_PICO_W/" >&2
  exit 1
fi

echo "=== Migrate wall Pico → $NODE_ID ==="
echo "UF2: $(basename "$UF2")"
echo "App: firmware/releases/$RELEASE_NAME"
echo "WiFi/server: Plantnet → http://192.168.1.19:5000/api/submit"
echo
echo "1) Unplug from wall."
echo "2) Hold BOOTSEL, plug USB into this Mac (Pico W only)."
echo "3) Confirm an RPI-RP2 (BOOTSEL) volume appears."
read -r -p "Press Enter when the BOOTSEL volume is mounted... "

# Find BOOTSEL mass-storage volume (macOS)
RP2=""
for cand in /Volumes/RPI-RP2 /Volumes/RP2350; do
  if [[ -d "$cand" ]]; then
    RP2="$cand"
    break
  fi
done
if [[ -z "$RP2" ]]; then
  # Fallback: any volume with INFO_UF2.TXT
  while IFS= read -r vol; do
    if [[ -f "$vol/INFO_UF2.TXT" ]]; then
      RP2="$vol"
      break
    fi
  done < <(ls -d /Volumes/* 2>/dev/null || true)
fi
if [[ -z "$RP2" ]]; then
  echo "BOOTSEL volume not found under /Volumes." >&2
  echo "Hold BOOTSEL while plugging in, then re-run." >&2
  exit 1
fi

echo "Copying UF2 to $RP2 ..."
# macOS: strip xattrs or FAT copy fails with "Operation not permitted"
/bin/cp -X "$UF2" "$RP2/" || cp "$UF2" "$RP2/firmware.uf2"
echo "UF2 copied — board should reboot into MicroPython (volume will disappear)."
echo "Waiting for MicroPython serial..."

# Wait for usbmodem MicroPython device
PORT=""
for _ in $(seq 1 40); do
  sleep 1
  while IFS= read -r line; do
    if [[ "$line" == *usbmodem* && "$line" == *MicroPython* ]]; then
      PORT="${line%% *}"
      break 2
    fi
  done < <(mpremote devs 2>/dev/null || true)
done

if [[ -z "$PORT" ]]; then
  echo "MicroPython serial not seen yet. Unplug/replug USB (no BOOTSEL) and re-run:" >&2
  echo "  ./scripts/commission_plant_pico.sh $NODE_ID $RELEASE_NAME" >&2
  exit 1
fi

echo "Found $PORT — verifying bluetooth + network..."
mpremote connect "$PORT" exec "import bluetooth, network; print('runtime_ok')"

echo "Commissioning app + secrets..."
./scripts/commission_plant_pico.sh "$NODE_ID" "$RELEASE_NAME"

echo
echo "Done. Confirm on http://192.168.1.19:5000/check as $NODE_ID ($RELEASE_NAME)"
echo "Then move back to wall power and verify it keeps posting."
