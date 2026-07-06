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
| Measurement integrity | `feature/measurement-integrity` |

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

## Feature 3: Measurement integrity (thermal system ID: impulse response or PRBS cross-correlation)

**Branch:** `feature/measurement-integrity`  
**Status:** Planned — next feature after I2C sensor identification  
**Scope:** Replace the placeholder `integrity` block with a real **sensor health check** that verifies the temperature channel responds to a known physical stimulus. Phase 1 uses a **GPIO-driven heating resistor** placed near the temperature sensor; excitation is either a **time-domain impulse** or **PRBS (pseudo-random binary sequence)** with **cross-correlation** to recover the thermal impulse response.

Today, `pico/main.py` always reports `"state": "green"` with no verification. A stuck, disconnected, or drifting sensor can still produce plausible-looking readings. Integrity testing injects a controlled heat input and checks that the sensor’s temperature trace matches expected dynamics.

### Concept

```
                    ┌─────────────────┐
  GPIO ──▶ driver ──▶ heating resistor ──▶ air / board near sensor
                              │
                              ▼
                    temperature sensor (I2C)
                              │
                              ▼
              compare excitation vs response → integrity score
```

The heater is a **known input** \( u(t) \) (0/1 or PWM). The sensor output is \( y(t) \) (temperature vs time). A healthy sensor shows a **causal, correlated** response; a fault shows flat line, wrong delay, wrong gain, or no coupling.

### Phase 1 excitation modes (implement one first, support both later)

| Mode | Heater drive \( u(t) \) | Analysis | Pros | Cons |
|------|-------------------------|----------|------|------|
| **Impulse response** | Single pulse (or short burst), then off | Measure rise time, peak ΔT, time constant τ from step/impulse | Simple, easy to interpret on server | SNR low for small ΔT; ambient drift during test |
| **PRBS + cross-correlation** | Binary PRBS on GPIO for duration \( T \) | \( h[k] = r_{uy}[k] \); peak location, area, shape vs baseline | Averages out noise; better SNR for small heaters | More RAM/CPU; longer test window; needs aligned sampling |

**Impulse flow (sketch):**

1. Record baseline temperature for \( T_0 \) seconds (heater off).
2. Assert heater ON for \( T_{\mathrm{pulse}} \) (ms–s, tuned to safe power).
3. Heater OFF; sample temperature at fixed Δt until response settles.
4. Fit or threshold: ΔT\_max, delay to 63% (τ), monotonicity.
5. Map metrics → `integrity.state` (`green` / `yellow` / `red`) and `integrity.score`.

**PRBS flow (sketch):**

1. Generate maximal-length or Gold-code **PRBS** at chip period \( T_c \) (e.g. 100–500 ms).
2. Drive heater GPIO with PRBS; sample temperature every \( T_c \) (or faster, then decimate).
3. Compute cross-correlation \( r_{uy}[k] = \sum_n (u[n]-\bar u)(y[n+k]-\bar y) \) (or normalized variant).
4. Peak amplitude, peak delay, and side-lobe ratio vs stored baseline → score.
5. Optional: upload compact summary (peak, lag, correlation coefficient), not full raw vectors, to save bandwidth.

Choose **impulse** for the first lab prototype if RAM is tight; add **PRBS** when noise rejection matters in the field.

### Hardware (phase 1)

| Component | Role |
|-----------|------|
| **GPIO pin** (e.g. GP15 — TBD, avoid I2C GP4/GP5) | Digital drive to heater circuit |
| **N-channel MOSFET or NPN + base resistor** | Switch heater current; do not drive resistor directly from GPIO |
| **Power resistor** (e.g. 10–47 Ω, rated wattage) | Localized heat source near temp sensor die / breakout |
| **Separate supply or USB rail** | Heater current may exceed safe GPIO load; size for duty cycle |

**Safety constraints (firmware-enforced):**

- Maximum pulse duration and maximum duty cycle per test.
- Cooldown period between integrity runs.
- Abort if baseline temperature exceeds a ceiling (avoid runaway in hot enclosure).
- Heater off on any exception before WiFi or long blocking work.

Mechanical: resistor physically close to the **same** temperature sensor used for integrity (initially AHT20; later the designated primary temp channel from Feature 2).

### Pico software sketch

```
pico/
├── integrity/
│   ├── __init__.py
│   ├── heater.py          # GPIO on/off, optional PWM, safety limits
│   ├── impulse.py         # impulse test sequence + metrics
│   ├── prbs.py            # PRBS generation, cross-correlation (may need lib/ or ulab if added)
│   └── scoring.py         # metrics → state, score, mode
└── main.py                # normal read loop; periodic integrity schedule
```

**Scheduling:** Integrity tests should **not** run every 60 s submit cycle. Suggested default: once per hour or on server command (future remote config). Normal submits carry the **last** integrity result until a new test completes.

**Sampling:** During an active test, temporarily increase temperature read rate (e.g. 2–10 Hz) using the existing AHT20 driver; return to slow polling afterward.

### `integrity` payload (replaces placeholder)

```json
{
  "integrity": {
    "state": "green",
    "score": 0.92,
    "mode": "prbs-crosscorr",
    "test_timestamp_node": "2026-07-06T14:30:00",
    "metrics": {
      "delta_t_max_f": 0.8,
      "peak_lag_s": 12.5,
      "corr_peak": 0.87,
      "baseline_temp_f": 71.2
    },
    "excitation": {
      "type": "prbs",
      "length_bits": 127,
      "chip_period_ms": 200
    }
  }
}
```

For impulse mode, `mode` is `impulse-response` and `metrics` holds e.g. `tau_s`, `delta_t_max_f`, `rise_monotonic`.

Server and `/check` already read `integrity.state`; extend display for score, mode, last test age, and key metrics.

### Server changes

| Change | Purpose |
|--------|---------|
| Store full `integrity` JSON in CSV (already via `integrity_json`) | History and trending |
| `/check` columns or detail row | Show state, score, mode, last test time |
| Optional baseline registry per `node_id` | Compare current PRBS peak shape to commissioning baseline |
| Alert rules (later) | `red` or score below threshold → notification |

Heavy correlation analysis can stay **on the Pico** in phase 1; server receives summaries only. Optional later: upload raw traces to server for offline analysis (larger payloads).

### Dependencies on other features

| Dependency | Reason |
|------------|--------|
| Feature 2 (sensor ID) | Know which device is the primary temperature channel for scoring |
| Feature 1 (OTA) | Ship `integrity/` module and algorithm tweaks without USB |
| Modular `sensors/` | Fast repeated reads during test window |

Integrity phase 1 can start with **hardcoded AHT20** on the lab bench before Feature 2 is complete.

### Rollout phases

| Phase | Work | Depends on |
|-------|------|------------|
| 1 | Bench wiring: GPIO + MOSFET + resistor; `heater.py` with limits | — |
| 2 | Impulse test + on-Pico metrics + real `integrity` in submit payload | Phase 1 |
| 3 | Server `/check` shows integrity score, mode, test age | Phase 2 |
| 4 | PRBS generator + cross-correlation path; compare vs impulse in lab | Phase 2 |
| 5 | Scheduled tests + cooldown; optional server-triggered test (remote config) | Phase 3 |
| 6 | OTA rollout of `integrity/` to field; baseline capture at install | Feature 1 |

### Risks and constraints

- **Small ΔT** — low power/heater may produce subtle response; PRBS helps; avoid false reds from noise.
- **Ambient coupling** — sunlight, HVAC, or watering swamps the test; schedule tests or detect unstable baseline.
- **Humidity cross-talk** — heating affects RH; integrity focuses on **temperature** response; document expected RH drift.
- **RAM / CPU** — PRBS buffer length limits; prefer fixed-length sequences (e.g. 7- or 127-bit LFSR); avoid large float arrays if possible (fixed-point OK).
- **WiFi during test** — defer POST until test completes; do not heat during OTA flash.
- **Multi-sensor nodes** — define which sensor must respond; others reported but not scored in phase 1.

### Out of scope (phase 1)

- Closed-loop PID temperature control (open-loop pulse/PRBS only).
- Integrity via non-thermal actuators (fan, humidifier) — future phases.
- Full transfer-function upload and server-side system ID (summaries only initially).

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
| 3 | Measurement integrity | `feature/measurement-integrity` | GPIO heater, impulse or PRBS + cross-corr | Display/store integrity metrics on `/check` | Yes — lab Pico first; brief heater tests |
