# Plant Sensor Server

A small two-part system for monitoring temperature and humidity near plants. A **Raspberry Pi Pico W** reads an **AHT20** sensor over I2C and posts readings to a **Flask** server on a host computer. The server stores data in daily CSV files and serves a simple status page.

```
┌─────────────────┐     WiFi      ┌──────────────────────┐
│  Raspberry Pi   │  POST /api/   │  Host computer       │
│  Pico W         │  submit       │  (Flask / app.py)    │
│  + AHT20 sensor │──────────────▶│  CSV logs + /check   │
└─────────────────┘               └──────────────────────┘
```

## What it does

### Host server (`app.py`)

Runs on a computer on your LAN and:

- Accepts sensor payloads at `POST /api/submit`
- Keeps the most recent reading per `node_id` in memory
- Appends every reading to a daily CSV file in `data/` (e.g. `data/2026-07-06.csv`)
- Exposes a JSON API at `GET /api/latest`
- Serves a human-readable status table at `GET /check`
- Lists and serves CSV files at `GET /data`

### Pico W firmware (`pico/main.py`)

Runs on the microcontroller and:

- Connects to WiFi using credentials in `secrets.py`
- Reads temperature (°F) and relative humidity (%) from an AHT20 every 60 seconds
- POSTs a JSON payload to the host server, with retries and backoff on failure
- Blinks the onboard LED while taking a reading cycle

Each node identifies itself with a `node_id` (default: `plant-080`). Multiple Picos can report to the same server.

## Sensor: AHT20

This project uses an **AHT20** digital temperature and humidity sensor on **I2C**.

| Property | Value |
|----------|-------|
| Interface | I2C |
| Address | `0x38` |
| Wiring (Pico W) | SDA → **GP4**, SCL → **GP5**, 3.3 V, GND |
| Readings | Temperature (converted to °F in firmware), relative humidity (%) |

The AHT20 is a low-cost environmental sensor, not a soil-moisture probe. It measures **air** temperature and humidity where you place it. That is still useful for plant care:

- **Tropical / humidity-loving plants** — track whether ambient humidity stays in a comfortable range (many houseplants prefer roughly 40–60% RH).
- **Succulents and cacti** — spot overly humid conditions that encourage rot, especially in poorly ventilated spots.
- **Seasonal heating / AC** — dry winter air or cold AC vents can stress plants before visible damage appears.
- **Greenhouse or grow-tent monitoring** — correlate temperature swings with watering or ventilation schedules.
- **Multi-plant setups** — deploy several Pico W nodes (different `node_id` values) to compare microclimates near windows, radiators, or grow lights.

The server stores an `integrity` block with each reading (currently a placeholder `green` state from the Pico). Planned **measurement integrity** tests use a GPIO-driven heating resistor and thermal impulse response (or PRBS cross-correlation) to verify the sensor responds to physical stimulus — see [docs/ROADMAP.md](docs/ROADMAP.md) Feature 3.

## MicroPython on Pico W (not CircuitPython, not Pico 2)

The firmware in `pico/` is written for **MicroPython**, not CircuitPython. You can tell from the imports and APIs:

- `machine.Pin`, `machine.I2C` — hardware access
- `network.WLAN` — WiFi
- `urequests` — HTTP client

**Target board: Raspberry Pi Pico W only** (RP2040 + CYW43439 WiFi). This repo is not written or tested for:

- **Raspberry Pi Pico 2 / Pico 2 W** (RP2350) — different chip and MicroPython builds; pin names and WiFi stack may differ.
- **Original Pico** (no W) — no onboard WiFi; this code depends on `network.WLAN`.
- **CircuitPython** — would need a full port (`wifi`, `adafruit_ahtx0`, different project layout).

### Flashing MicroPython on Pico W

1. Download the latest **Raspberry Pi Pico W** MicroPython UF2 from [micropython.org/download/RPI_PICO_W](https://micropython.org/download/RPI_PICO_W/).
2. Hold **BOOTSEL**, plug in USB, release — the board appears as a USB drive.
3. Copy the `.uf2` file onto the drive; the board reboots into MicroPython.
4. Copy `main.py`, `secrets.py`, and install `urequests` (bundled in recent MicroPython builds or copy from the [micropython-lib](https://github.com/micropython/micropython-lib) project) to the Pico filesystem via Thonny, `mpremote`, or `rshell`.

## Hosting the server

`app.py` is plain Python 3 with **Flask**. It binds to `0.0.0.0:5000`, so it accepts connections from other devices on the network.

### Raspberry Pi SBC options

Any Raspberry Pi that runs a current **Raspberry Pi OS** (or other Linux) and **Python 3** works well:

| Board | Notes |
|-------|--------|
| **Pi 5** | Fastest; good if you add more services later |
| **Pi 4** | Solid default for a always-on home server |
| **Pi 3 B / B+** | Fine for this light Flask workload |
| **Pi Zero 2 W** | Low power; sufficient for receiving one or a few nodes |
| **Pi Zero W** | Works but slower; OK for a single sensor node |

Older boards (Pi 1, Pi 2) can run Flask but are increasingly impractical for new setups; prefer Pi 3 or newer.

Pi OS Lite (no desktop) is enough — you only need SSH and Python.

### Other Linux hosts

The server does not require a Raspberry Pi. Any machine on the LAN with Python 3 can host it:

- **x86 mini PC** (Intel NUC, Beelink, old laptop)
- **Other ARM boards** (Orange Pi, Libre Computer, etc.) running Debian/Ubuntu/Armbian
- **Home server / NAS** with Python (Synology and some NAS units can run Python in a container or chroot)
- **Virtual machine or LXC container** on a hypervisor
- **Cloud VPS** — possible, but the Pico must reach it over the internet; you would use the VPS public IP or a tunnel and should put HTTPS and authentication in front of Flask for production

### Software on the host

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install flask
python app.py
```

Then open `http://<host-ip>:5000/check` from a browser on the same network.

For a durable deployment, run Flask behind **gunicorn** + **nginx**, or use **systemd** to start `app.py` on boot. The stock `app.run()` in `app.py` is intended for development and light home use.

**macOS or Windows** can run the server for testing, but a small always-on Linux box is the usual choice for a plant monitor that runs 24/7.

## Moving to a different network

Only the **Pico** needs network-specific configuration. The host server usually stays the same.

### 1. WiFi credentials (Pico)

Copy `pico/secrets_template.py` to `pico/secrets.py` on the device (do not commit `secrets.py`):

```python
WIFI_SSID = "your-network-name"
WIFI_PASSWORD = "your-network-password"
```

### 2. Server URL (Pico)

In `pico/main.py`, set `SERVER_URL` to the **LAN IP address** of the machine running `app.py`:

```python
SERVER_URL = "http://192.168.1.42:5000/api/submit"
```

Use the host’s IP on the **same WiFi/LAN** as the Pico, not the Pico’s own address.

### 3. Host server (`app.py`)

No changes are required for a new network. Defaults are already correct:

```python
app.run(host="0.0.0.0", port=5000)
```

Change the port only if you must; then update `SERVER_URL` on the Pico to match.

### 4. Checklist

1. Start the Flask server on the host (`python app.py` or your process manager).
2. Find the host IP (`hostname -I` on Linux, or your router’s DHCP client list).
3. Update `SERVER_URL` on the Pico and flash/copy the updated `main.py`.
4. Ensure the host **firewall allows TCP port 5000** from the local subnet.
5. Confirm the Pico and host are on the same network (or routable).
6. Optional: set a unique `NODE_ID` per Pico if you have multiple plants.

### Optional identifiers

| Variable | File | Purpose |
|----------|------|---------|
| `NODE_ID` | `pico/main.py` | Unique name for this sensor node |
| `READ_INTERVAL_S` | `pico/main.py` | Seconds between readings (default `60`) |
| `FIRMWARE_VERSION` | `pico/main.py` | Reported to the server for tracking |

## API reference

### `POST /api/submit`

Request body (JSON):

```json
{
  "node_id": "plant-080",
  "firmware_version": "pico-aht20-0.2",
  "timestamp_node": "",
  "readings": {
    "temperature_F": 72.5,
    "humidity_percent": 48.2
  },
  "integrity": {
    "state": "green",
    "score": 1.0,
    "mode": "aht20-loop-retry"
  }
}
```

### `GET /api/latest`

Returns the latest record per node, including `data_age_s` (seconds since last report).

### `GET /check`

HTML table of all known nodes and their last readings.

## Repository layout

```
plant-sensor-server/
├── app.py                 # Flask server (host computer)
├── docs/
│   └── ROADMAP.md         # Architecture and planned features (OTA, sensor discovery)
├── pico/
│   ├── main.py            # MicroPython firmware (Pico W)
│   └── secrets_template.py
├── data/                  # Daily CSV logs (created at runtime, gitignored)
└── README.md
```

## Development roadmap

Planned features, deployment strategy (production `main` alongside feature branches), and phased designs for **WiFi OTA updates** and **I2C sensor identification** (Adafruit breakouts) are documented in [docs/ROADMAP.md](docs/ROADMAP.md).

## License

Not specified in this repository; add a license file if you plan to distribute or open-source the project.
