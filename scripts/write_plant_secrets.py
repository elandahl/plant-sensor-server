#!/usr/bin/env python3
"""Write pico/secrets.py for Plantnet commissioning (local/gitignored only).

Usage:
  python3 scripts/write_plant_secrets.py Plant-080

Reads WIFI_PASSWORD from existing pico/secrets.py when present, else from
PLANT_WIFI_PASSWORD. Never prints the password.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "pico" / "secrets.py"

PLANT_SSID = "Plantnet"
PLANT_SERVER_URL = "http://192.168.1.19:5000/api/submit"


def load_existing_password():
    env = os.environ.get("PLANT_WIFI_PASSWORD")
    if env:
        return env
    if not SECRETS.exists():
        return None
    text = SECRETS.read_text()
    m = re.search(r'WIFI_PASSWORD\s*=\s*"([^"]*)"', text)
    return m.group(1) if m else None


def main():
    if len(sys.argv) != 2 or not sys.argv[1].startswith("Plant-"):
        raise SystemExit(
            "Usage: python3 scripts/write_plant_secrets.py Plant-NNN\n"
            "Example: python3 scripts/write_plant_secrets.py Plant-080"
        )
    node_id = sys.argv[1]
    password = load_existing_password()
    if not password:
        raise SystemExit(
            "No WiFi password found. Set pico/secrets.py first or export "
            "PLANT_WIFI_PASSWORD."
        )

    SECRETS.parent.mkdir(parents=True, exist_ok=True)
    SECRETS.write_text(
        "# Local only — gitignored. Never commit or push.\n"
        "# Site: Plant (Plantnet WiFi + plant Pi server)\n"
        "\n"
        f'WIFI_SSID = "{PLANT_SSID}"\n'
        f'WIFI_PASSWORD = "{password}"\n'
        "\n"
        f'SERVER_URL = "{PLANT_SERVER_URL}"\n'
        f'NODE_ID = "{node_id}"\n'
    )
    print(f"Wrote {SECRETS.relative_to(ROOT)}")
    print(f"  WIFI_SSID = {PLANT_SSID}")
    print(f"  SERVER_URL = {PLANT_SERVER_URL}")
    print(f"  NODE_ID = {node_id}")
    print("  WIFI_PASSWORD = (set, not shown)")


if __name__ == "__main__":
    main()
