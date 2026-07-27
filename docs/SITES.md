# Sites, prefixes, and credentials

Each Pico’s **`NODE_ID` prefix** names a **site**. A site has its own WiFi and its own plant-sensor server. Do not mix credentials across prefixes.

## Naming

```
NODE_ID = "<Prefix>-<NNN>"
```

| Part | Meaning | Examples |
|------|---------|----------|
| **Prefix** | Location / network / server | `Plant`, `Byrne417` |
| **NNN** | Floor, room, sensor-within-room (reused from existing plant IDs) | `123`, `080` |

Examples:

- `Plant-123` — production plant node (3-digit ID reused from prior hardware)
- `Byrne417_01` — lab node in Byrne Hall 417 (underscore form used in lab)

Lab IDs may keep the existing `Byrne417_NN` form. **New plant installs use `Plant-NNN`.**

## Rule: prefix ⇒ WiFi + server

| Prefix | WiFi | Server (`SERVER_URL`) | Notes |
|--------|------|------------------------|--------|
| `Plant` | Plant LAN only | Plant Raspberry Pi 5 | Production |
| `Byrne417` | Lab / Byrne network only | Lab Pi (`pi08`, e.g. `140.192.162.150`) | Development |

**Never** put plant WiFi + Byrne `SERVER_URL` (or the reverse) on the same board. OTA and logs will target the wrong place, and nodes may appear “missing” on the site you expect.

`secrets.py` is **USB-only** and is never overwritten by OTA. That is intentional: site binding lives only there.

## Commissioning checklist (USB)

For each Pico moving to (or staying at) a site:

1. Confirm intended `NODE_ID` (`Plant-NNN` or `Byrne417_NN`).
2. Set **only** that site’s `WIFI_SSID` / `WIFI_PASSWORD`.
3. Set `SERVER_URL` to that site’s Pi: `http://<site-pi-ip>:5000/api/submit`.
4. Copy `secrets.py` to the Pico (keep lab `secrets.py` off plant boards).
5. Soft-reset; verify the node appears on **that** site’s `/check` with the correct `NODE_ID`.
6. Attach the sensor subset for that location (AHT20, ENS160/161, SGP30/40, TMP119 as needed).

### Plant shortcut (current firmware)

On a Mac on Plantnet, with the Pico on USB and MicroPython already installed:

```bash
./scripts/commission_plant_pico.sh Plant-080
```

That writes gitignored `pico/secrets.py` for Plantnet → `http://192.168.1.19:5000/api/submit`, copies `firmware/releases/pico-sensors-0.91/` plus `secrets.py` onto the Pico, and hard-resets. Then confirm on http://192.168.1.19:5000/check.

### Migrating old wall Picos (CircuitPython / ancient firmware)

Old plant hangers often run **CircuitPython** or very old MicroPython (`pico-aht20-0.2`). They cannot OTA to `0.91`. Per board:

1. Note the 3-digit ID (reuse as `Plant-NNN`).
2. Unplug wall power; hold **BOOTSEL**; plug USB.
3. Run:

```bash
./scripts/migrate_plant_pico.sh Plant-NNN
```

That flashes a BT-capable Pico W MicroPython UF2 (from `firmware/uf2/`, gitignored), then runs the same plant commission as above. Put back on wall power and confirm `/check`.

UF2 used for new plant boards today: **RPI_PICO_W v1.28.0** (same family as lab Byrne nodes).

## Plant Pi

The plant Raspberry Pi 5 should run the same server tree (`app.py`, `firmware/releases/`, `firmware/LATEST`) so OTA and `/check` behave like the lab. Lab and plant firmwares can stay in sync; only Pico `secrets.py` differs by site.

**Known plant host (Plantnet LAN):** `192.168.1.19` (`plant-server`), also Tailscale `100.65.123.65`.

**Health monitor:** systemd timer `plant-health-monitor.timer` runs every minute and appends to `logs/network-health.log` on the Pi (Ethernet carrier/IP, gateway ping, Flask `/api/health`, Tailscale IP, and whether any node has posted recently).

## Adding a new site later

1. Choose a new prefix (e.g. `Greenhouse`).
2. Stand up a Pi on that network with this server repo.
3. Commission boards with that prefix + that network’s WiFi + that Pi’s `SERVER_URL`.
4. Add a row to the table above in this doc.
