#!/usr/bin/env bash
# USB-commission a Pico W onto Plantnet with pico-sensors-0.91.
#
# Usage:
#   ./scripts/commission_plant_pico.sh Plant-080
#
# Prerequisites:
#   - Pico plugged in over USB (MicroPython already flashed)
#   - mpremote available
#   - pico/secrets.py already has Plant WiFi password, or PLANT_WIFI_PASSWORD set

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

NODE_ID="${1:-}"
if [[ -z "$NODE_ID" || "$NODE_ID" != Plant-* ]]; then
  echo "Usage: $0 Plant-NNN" >&2
  echo "Example: $0 Plant-080" >&2
  exit 1
fi

REL="firmware/releases/pico-sensors-0.91"
if [[ ! -f "$REL/main.py" || ! -f "$REL/manifest.json" ]]; then
  echo "Missing release tree: $REL" >&2
  exit 1
fi

python3 scripts/write_plant_secrets.py "$NODE_ID"

echo "Looking for Pico..."
mpremote connect list || true
mpremote devs

echo "Copying $REL + secrets.py ..."
# Ensure remote dirs exist, then recursive copy of release + secrets.
mpremote mkdir :ble || true
mpremote mkdir :sensors || true
mpremote mkdir :lib || true
mpremote mkdir :lib/aioble || true
mpremote cp -r "$REL/." :
mpremote cp pico/secrets.py :secrets.py

echo "Hard-reset (so main.py starts after USB session)..."
mpremote reset || mpremote exec "import machine; machine.reset()"

echo
echo "Done. Board should join Plantnet and POST as $NODE_ID"
echo "  Check: http://192.168.1.19:5000/check"
echo "  Latest: http://192.168.1.19:5000/api/latest"
echo "Note: leave USB connected is fine; unplug to wall power when ready."
