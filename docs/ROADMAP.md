# Development Roadmap

This document describes how the plant-sensor-server architecture scales to new features, how we deploy experimental work alongside production, and phased plans for upcoming capabilities.

For current behavior and setup, see [README.md](../README.md).

## Core architecture

```
┌─────────────────┐     WiFi / HTTP    ┌──────────────────────────────┐
│  Raspberry Pi   │◀────────────────▶│  Host server (Flask)         │
│  Pico W         │   POST /api/     │  Ingest, store, coordinate   │
│  + I2C sensors  │   submit + GET   │  Optional: OTA, config, UI   │
└─────────────────┘                    └──────────────────────────────┘
```

The Pico W is an **edge client**: it reads sensors, reports JSON to the server, and optionally pulls configuration or firmware updates. The host is the **coordination point**: logging, dashboards, alerting, release artifacts, and per-node desired state.

This pattern supports most future work without redesign:

| Extension point | Purpose |
|-----------------|---------|
| `readings` (JSON object) | Add new sensor values without breaking older nodes |
| `integrity` (JSON object) | Health, faults, calibration state, data quality |
| `firmware_version` | Capability negotiation between Pico and server |
| `POST /api/submit` response | Push hints: updates, config changes, commands |
| New `GET` endpoints | Manifests, per-node config, calibration data |
| Server-only features | Dashboards, CSV tools, alerts — no Pico change required |

### Two ways to change Pico behavior

| Change type | Mechanism | Examples |
|-------------|-----------|----------|
| **Remote config** | JSON in submit response or `GET /api/node/<id>/config` | Read interval, alert thresholds |
| **Application code** | OTA file download (see Feature 1) | New drivers, sensor libraries, bug fixes |
| **Server-only** | Flask changes | `/check` UI, notifications, analytics |
| **One-time / risky** | USB flash | MicroPython runtime, bootstrap firmware |

As features accumulate, expect the Flask app to split into modules (blueprints) such as `ingest`, `firmware`, `config`, and `admin`. Pico firmware should split similarly (`wifi.py`, `sensors/`, `update.py`, etc.) so OTA can update pieces independently.

---

## Deployment model (production + experiments)

Field nodes must keep running while new features are developed. Use this workflow:

```
Production (main)              Experiment (feature branch)
─────────────────────          ────────────────────────────
branch: main                   branch: feature/<name>
port:   5000                   port:   5001 (or path prefix)
nodes:  all field Picos        nodes:  lab / test Picos only
```

**Git worktree** (recommended on the host):

```bash
# Primary checkout — production
cd plant-sensor-server
git checkout main

# Second checkout — feature work, same repo
git worktree add ../plant-sensor-ota feature/pico-ota
```

Run two server processes on different ports until a feature is proven, then merge to `main`. Field Picos keep `SERVER_URL` pointing at production until deliberately migrated.

### Branch naming

| Feature | Suggested branch |
|---------|------------------|
| OTA updates | `feature/pico-ota` |
| I2C sensor identification | `feature/i2c-sensor-discovery` |

---

## Feature 1: WiFi OTA (application updates)

**Branch:** `feature/pico-ota`  
**Status:** Planned — not started  
**Scope:** Update `.py` files on the Pico filesystem over WiFi. Does **not** include reflashing the MicroPython UF2 runtime (USB only for that).

### Why this is feasible

The Pico W already has WiFi, HTTP (`urequests`), and reports `firmware_version` in every submit payload. The server can serve versioned artifacts and the Pico can download, verify, swap, and reboot.

### Server changes (OTA branch)

New endpoints:

| Endpoint | Purpose |
|----------|---------|
| `GET /api/firmware/manifest` | Version, file list, SHA-256 hashes, sizes |
| `GET /api/firmware/<filename>` | Serve `main.py` and other modules |

Optional extension to existing ingest:

| Change | Purpose |
|--------|---------|
| `POST /api/submit` response | Include `update_available` and manifest URL when `firmware_version` is behind |

Release artifacts stored under something like:

```
firmware/releases/pico-aht20-0.3/
├── manifest.json
├── main.py
├── discovery.py
├── sensors/
│   ├── __init__.py
│   ├── aht20.py
│   └── scd4x.py
└── lib/                    # optional third-party / shared MicroPython modules
    └── ...
```

The manifest lists **every file** in the release (application code, `sensors/` drivers, and `lib/` dependencies) with path, SHA-256, and size. The Pico updater installs each file to the matching path on the filesystem.

### Pico changes

Refactor the main loop to support an update cycle:

1. Connect WiFi.
2. Check manifest (dedicated GET or hint from submit response).
3. If server version > `FIRMWARE_VERSION`: download each file to a temp path (e.g. `main.py.new`).
4. Verify SHA-256 and size.
5. Backup current file → `main.py.bak`.
6. Atomically replace, then `machine.reset()`.

Optional `boot.py` for rollback if the new code fails immediately after reboot.

### Safety rules

- **Never overwrite `secrets.py`** via OTA.
- **Verify before swap** — hash + size at minimum.
- **Download to temp, then rename** — avoid half-written files on power loss.
- **Keep `main.py.bak`** for manual or automatic rollback.
- **Bootstrap problem:** the first OTA-aware firmware must reach each Pico **once via USB**. After that, updates are over WiFi.

### Rollout phases

| Phase | Work | Field impact |
|-------|------|--------------|
| 0 | Create branch; deploy OTA server on `:5001` | None |
| 1 | Server manifest + file serving only | None |
| 2 | Pico update client on lab device (USB bootstrap once) | None |
| 3 | Test publish `0.3` → lab Pico updates without USB | None |
| 4 | USB-bootstrap field Picos when convenient | One-time USB per node |
| 5 | Merge to `main` or enable OTA on production port | Controlled migration |

### Out of scope

- Full MicroPython UF2 OTA over WiFi (high brick risk).
- Updating WiFi credentials over OTA (stay in `secrets.py`, USB-managed).

---

## Feature 2: I2C sensor identification (next after OTA)

**Branch:** `feature/i2c-sensor-discovery`  
**Status:** Planned — depends on OTA for painless field rollout  
**Scope:** Detect which Adafruit (and compatible) sensor boards are attached on the I2C bus, report capabilities to the server, and read from supported drivers dynamically.

Today, `pico/main.py` hardcodes a single **AHT20** at address `0x38` on GP4/GP5. Future nodes may carry different or multiple boards: higher-resolution temperature, VOC, CO2, particulate matter, etc.

### Goals

1. **Scan the I2C bus** at boot (and optionally periodically) for device addresses.
2. **Identify boards** using address + probe reads (chip ID registers) where possible.
3. **Report inventory** to the server so `/check` and logs show what each node actually has attached.
4. **Load the right driver** per identified device and merge all readings into the existing `readings` payload.
5. **Graceful degradation** — unknown address → log/report as `unknown`; known address but read failure → `integrity` fault, not a crash.

### Why OTA comes first

New sensor drivers and their supporting libraries will ship as files on the Pico filesystem. Without OTA, every new Adafruit board support requires a USB visit to each field Pico. OTA makes driver and library additions deployable from the server.

### Driver libraries: pre-load and OTA update

We will not rely on CircuitPython bundles or `mip` alone for field nodes. Each supported board needs a **MicroPython driver** (our own minimal port or vendored from [micropython-lib](https://github.com/micropython/micropython-lib)). Those modules reach the Pico in two ways:

| Method | When | What |
|--------|------|------|
| **USB pre-load** | Initial flash, new hardware in the lab, or recovery | Copy `main.py`, `sensors/`, `lib/`, and `secrets.py` via Thonny / `mpremote` |
| **OTA update** | Field rollout after Feature 1 | Server manifest delivers new or changed files under `sensors/` and `lib/` |

**Pre-load (bootstrap):** When a node is first provisioned, install the full known driver set (or a “starter bundle” for the boards expected on that node). Flash is cheap relative to RAM; pre-loading common Adafruit drivers avoids a download on first boot in the greenhouse.

**OTA (ongoing):** When identification finds a chip the server knows about but the Pico has no driver for, the server can include a targeted library pack in the next manifest (or respond to submit with `update_available` and a manifest that adds only the missing `sensors/<driver>.py` and any `lib/` deps). After reboot, discovery runs again and the new board is read normally.

**Library layout on the Pico:**

```
pico/
├── main.py
├── secrets.py
├── i2c_bus.py
├── discovery.py
├── sensors/           # per-board drivers (OTA-updatable)
│   ├── base.py
│   ├── aht20.py
│   └── ...
└── lib/               # shared helpers, vendored micropython-lib snippets (OTA-updatable)
    └── ...
```

**Server-side:** Maintain a **driver registry** mapping board ID → required files (driver module + `lib/` dependencies + minimum `firmware_version`). Release manifests are built from that registry so OTA never pushes unrelated boards’ code unless bundled intentionally.

**Safety:** Same OTA rules as Feature 1 — verify hashes, never overwrite `secrets.py`, keep backups, reboot after install. If a new library fails on import, `boot.py` rollback restores the last known-good set.

### Target hardware (initial)

Primarily **Adafruit STEMMA QT / I2C breakouts**, for example:

| Sensor type | Example boards | Notes |
|-------------|----------------|-------|
| Temperature / humidity | AHT20 (current), SHT4x, BME680 | Some share addresses; probe ID registers to disambiguate |
| VOC / gas | BME680, SGP40 | BME680 combines T/RH/P + gas; SGP40 needs compensation |
| CO2 | SCD-40, SCD-41 | NDIR; different measurement cadence than AHT20 |
| Particulate | PMSA003I | Larger payloads; may need slower poll interval |

Exact board list will grow incrementally. Identification logic should be **table-driven** (address + ID bytes → driver name), not one giant `if` chain.

### Pico design sketch

```
pico/
├── main.py              # loop: wifi → discover → read → post
├── secrets.py
├── i2c_bus.py           # init I2C(0), scan(), shared bus handle
├── discovery.py         # scan + probe → list of SensorDevice records
└── sensors/
    ├── __init__.py
    ├── base.py          # SensorDriver interface: probe(), read() → dict
    ├── aht20.py         # existing logic, migrated
    ├── sht4x.py         # future
    ├── bme680.py        # future
    ├── scd4x.py         # future
    └── pmsa003i.py      # future
```

**`SensorDriver` interface (conceptual):**

- `addresses: list[int]` — addresses this driver claims.
- `probe(i2c, addr) -> bool` — read ID register(s); True if this driver matches.
- `read(i2c, addr) -> dict` — return fragment for `readings` (e.g. `{"temperature_F": ..., "humidity_percent": ...}`).
- `min_interval_s` — optional; CO2/particulate may need slower polling than temperature.

**Discovery flow:**

1. `i2c.scan()` → candidate addresses.
2. For each address, run `probe()` on registered drivers in priority order.
3. Build `attached_sensors: [{ "driver": "aht20", "address": "0x38", "board": "AHT20" }, ...]`.
4. On each loop, call `read()` on each attached driver; merge dicts into `readings`.
5. Handle address conflicts (e.g. two driver types at `0x76`/`0x77`) via probe, not address alone.

### Payload extensions

Extend submit JSON (backward compatible — server accepts extra fields):

```json
{
  "node_id": "plant-080",
  "firmware_version": "pico-sensors-0.1",
  "attached_sensors": [
    { "driver": "aht20", "address": "0x38", "label": "AHT20" },
    { "driver": "scd41", "address": "0x62", "label": "SCD41" }
  ],
  "readings": {
    "temperature_F": 72.5,
    "humidity_percent": 48.2,
    "co2_ppm": 812,
    "voc_index": 120
  },
  "integrity": {
    "state": "green",
    "sensor_errors": []
  }
}
```

Server should store `attached_sensors` in CSV or a structured column for history. `/check` can show detected hardware per node.

### Server changes

| Change | Purpose |
|--------|---------|
| Accept `attached_sensors` in `POST /api/submit` | Persist inventory per node |
| Show sensors on `/check` | Operator visibility |
| Optional `GET /api/node/<id>/sensors` | Query last known hardware |
| Driver ↔ board registry (server-side, docs) | Reference for supported combinations |

### Rollout phases

| Phase | Work | Depends on |
|-------|------|------------|
| 1 | Extract AHT20 into `sensors/aht20.py`; add `i2c_bus.py` | — |
| 2 | `discovery.py` + `attached_sensors` in payload; server stores/displays | Phase 1 |
| 3 | Add second driver + any `lib/` deps; USB pre-load on lab Pico | — |
| 4 | Table-driven driver registry (board → files); OTA manifest includes `sensors/` + `lib/` | Feature 1 |
| 5 | Lab test: identify new board → server pushes missing driver via OTA | Phases 3–4 |
| 6 | Discovery + library OTA to field nodes | Feature 1 complete |

### Risks and constraints

- **I2C address collisions** — multiple chip families use `0x76`/`0x77`; probing is mandatory.
- **Bus errors** — long cables, multiple boards: consider pull-ups, clock speed (100 kHz default is safe), and error isolation per driver.
- **Memory** — MicroPython on Pico W has limited RAM; not every Adafruit CircuitPython driver ports cleanly; prefer small dedicated MicroPython drivers.
- **Power / warm-up** — CO2 and gas sensors need time after boot; discovery should not assume instant valid readings.
- **CircuitPython vs MicroPython** — Adafruit docs often target CircuitPython; we stay on **MicroPython** and port or write minimal drivers.

---

## Future considerations (not yet planned)

These fit the same architecture but are not scheduled:

- **Persistent server state** (SQLite) for config, alerts, and sensor history beyond daily CSV
- **Remote config channel** (`config_version` + desired state per node)
- **Authentication** (API keys per `node_id`) before exposing OTA or config on a LAN
- **Alerting** (email, webhook) from server-side rules on `readings` and `integrity`
- **HTTPS** reverse proxy in front of Flask for non-LAN access

---

## Feature summary

| Order | Feature | Branch | Pico | Server | Field-safe parallel deploy |
|-------|---------|--------|------|--------|----------------------------|
| 1 | WiFi OTA (`.py` updates) | `feature/pico-ota` | Update client + modular code | Manifest + artifact hosting | Yes — `:5001` + lab Pico |
| 2 | I2C sensor identification | `feature/i2c-sensor-discovery` | Bus scan, drivers, `lib/` pre-load + OTA | Store/display `attached_sensors`; driver registry | Yes — after OTA for driver/library rollout |
