# Step 2: I2C sensor discovery — design note

Design decisions for **Feature 2** (`feature/i2c-sensor-discovery`). Implementation plan and phasing; see also [ROADMAP.md](ROADMAP.md) Feature 2.

**Status:** In progress — phase 2a on `feature/i2c-sensor-discovery`  
**Prerequisite:** Step 1 OTA merged and lab-tested (done on Byrne417_01)

---

## Goals (operator view)

1. Notice when sensors are **plugged in or removed**
2. **Read what is present** — never hang the loop on missing or failed devices
3. **Detect and warn** on bus problems (duplicate addresses, unknown chips, read failures)
4. Support **STEMMA QT daisy-chain and passive QT hubs** (same I2C bus rules)
5. Ship drivers via **starter bundle at bootstrap** + **OTA** for additions
6. Provide **live data streams** for check, troubleshoot, and calibration — rich analytics deferred to digital twin team

---

## Decisions (locked)

### 1. Same-address sensors — document, detect, warn

Some boards (e.g. **AHT20** at `0x38`) have a **fixed address**. Two identical boards on one bus without an **I2C multiplexer** (e.g. TCA9548A) will conflict: scan may show one address, reads become unreliable.

| Policy | Detail |
|--------|--------|
| **Document** | Install guide: one fixed-address board per bus unless mux used |
| **Detect** | Ambiguous probe, unstable readings, or operator-reported duplicate wiring |
| **Warn** | `integrity.state` → `yellow` or `red`; `sensor_errors[]` with code `duplicate_or_ambiguous` |
| **Do not** | Report two logical sensors at the same address without mux channel in `attached_sensors` |

Address **collisions between different chip families** at `0x76`/`0x77` are resolved by **ID register probe**, not address alone.

### 2. Rescan interval — every N minutes (OTA-tunable later)

| Phase | Interval | How |
|-------|----------|-----|
| **Development** | **15 minutes** | Constant in firmware (`RESCAN_INTERVAL_S = 900`) |
| **Production** | TBD (e.g. 60–240 min) | Remote config or OTA when config channel exists |

On each rescan:

- Full `i2c.scan()` + probe
- Compare to previous `attached_sensors` inventory
- Log/report **hardware change** (added / removed / reclassified)

Normal **read loop** (e.g. 60 s) uses the **last known good inventory**; rescan updates inventory between read cycles.

### 3. Starter driver bundle + OTA for new boards

**At USB bootstrap** (and in OTA release manifests), pre-load a **starter bundle** of MicroPython drivers for boards we expect in the lab and field.

**OTA** delivers additional or updated `sensors/*.py` and `lib/*` when:

- Discovery finds a supported board the Pico lacks a driver for, or
- Server registry publishes a new manifest (same as Step 1 OTA)

**Server driver registry** (future file in repo): maps `driver` / board ID → manifest file list + minimum firmware version.

#### Test inventory (next ~2 weeks — chemists available)

*To be filled in when hardware list is confirmed.* Expected categories:

| Board / driver | I2C address(es) | Notes |
|----------------|-----------------|-------|
| AHT20 | `0x38` | Current default on Byrne417_01 |
| *(add rows)* | | CO₂, VOC, particulate, higher-res RH/T, etc. |

Starter bundle v1 will include drivers for all rows marked **bootstrap** above; others can ship via targeted OTA manifest.

### 4. Server storage — JSON columns, live streams first

**Near term:** this server is for **live check, troubleshooting, and calibration** — not the long-term analytics store (digital twin team owns that downstream).

| Field | Storage | Notes |
|-------|---------|-------|
| `readings` | Existing `readings_json` CSV column | Variable keys per node; no fixed column explosion |
| `attached_sensors` | New **`attached_sensors_json`** CSV column | Inventory snapshot each submit |
| `integrity` | Existing `integrity_json` | Includes `sensor_errors[]` |

**API:** `POST /api/submit` and `GET /api/latest` accept/return extra fields; backward compatible.

**Website:** easy to evolve later; not blocking Step 2.

### 5. `/check` — primary metrics only (for now)

Show on the status table:

- Node ID, last seen, age
- **Primary metrics** when present: temperature °F, humidity %, CO₂ ppm (first available of each class)
- Integrity state
- Short **hardware summary** (e.g. `AHT20 + SCD41` or count of attached sensors)

Defer: dynamic columns for every possible reading key, per-sensor detail pages, charts.

---

## Pico architecture

```
pico/
├── main.py              # loop: wifi → ota → discover (if due) → read all → post
├── discovery.py         # scan, probe, inventory diff, conflict detection
├── i2c_bus.py           # shared I2C(0), GP4/GP5, 100 kHz
├── sensors/
│   ├── base.py          # SensorDriver interface
│   ├── aht20.py
│   └── …                # starter bundle + OTA additions
└── lib/                 # shared / vendored snippets
```

### SensorDriver interface

- `addresses: list[int]`
- `probe(i2c, addr) -> bool` — ID registers, disambiguation
- `read(i2c, addr) -> dict` — fragment for `readings` (may be empty on failure)
- `min_interval_s` — optional; slow sensors (CO₂) polled less often than fast RH/T

### Read loop behavior

```text
for each device in attached_sensors:
    try:
        merge driver.read() into readings
    except:
        append to integrity.sensor_errors; continue
post submit either way
```

---

## Wiring: QT chain and hub

STEMMA QT **daisy-chain** and **passive QT hub** are equivalent electrically: one I2C bus, unique addresses required.

- PiCowbell QT → cable → board → cable → board … **OK**
- PiCowbell QT → hub → multiple boards **OK**
- Stay at **100 kHz**; isolate per-driver errors

---

## Implementation phases

| Phase | Deliverable |
|-------|-------------|
| **2a** | Extract AHT20 to `sensors/aht20.py`; `discovery.py` + `attached_sensors` in payload; server stores `attached_sensors_json`; `/check` hardware summary |
| **2b** | Rescan every 15 min; plug/unplug detection; same-address / unknown warnings in `integrity` |
| **2c** | Second driver from test inventory; starter bundle in bootstrap + registry; targeted OTA for missing driver |
| **2d** | Additional boards from inventory table; document install limits |

---

## Open items

1. **Complete test inventory table** — user to supply Adafruit SKUs / board list for chemist window
2. **Primary metric precedence** — if two temp sensors, which wins on `/check`? (Proposal: first in probe order, or designate `primary_temp` in config later)
3. **Hardware-change notification** — yellow integrity only, or separate flag in payload?
4. **Mux (TCA9548A)** — support in v1 or document as out-of-scope until needed?
5. **Production rescan interval** — pick default before large deployment

---

## Related docs

- [ROADMAP.md](ROADMAP.md) — Step 2 feature spec and rollout
- [OTA_TEST.md](OTA_TEST.md) — OTA smoke test (Step 1 validation)
