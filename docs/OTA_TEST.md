# OTA test procedure (integrity yellow)

Lab procedure for verifying WiFi OTA end-to-end without changing real sensor readings. Used successfully on **Byrne417_01** (2026-07-06).

## What you see when it works

| Where | Test signal |
|-------|-------------|
| `/check` | **Integrity** column shows `yellow` (not `green`) |
| `/api/latest` | `firmware_version`: `pico-aht20-0.4-test`, `integrity.state`: `yellow` |
| Readings | Temperature and humidity stay realistic (unchanged) |

Revert restores `green` and `pico-aht20-0.3`.

## Test release (`pico-aht20-0.4-test`)

Stored under `firmware/releases/pico-aht20-0.4-test/`. Only `main.py` differs from `0.3`:

- `FIRMWARE_VERSION = "pico-aht20-0.4-test"`
- `integrity.state = "yellow"`, `score = 0.5`, `mode = "ota-test"`

`update.py` is the same as `0.3`.

## Deploy test firmware

On the machine with the repo (host or laptop):

```bash
# Point LATEST at the test release
echo pico-aht20-0.4-test > firmware/LATEST

# Rebuild manifest if you edited main.py
python3 scripts/build_firmware_manifest.py firmware/releases/pico-aht20-0.4-test

# Copy to Pi (adjust host if needed)
rsync -avz firmware/ pi@140.192.162.150:~/plant-sensor-server/firmware/
```

No server restart required — Flask reads `firmware/LATEST` on each request.

The Pico checks for updates once per loop (~60 s) after WiFi connect. Allow 1–2 minutes, then open:

- http://&lt;pi-host&gt;:5000/check
- http://&lt;pi-host&gt;:5000/api/latest

## Revert to production firmware

```bash
echo pico-aht20-0.3 > firmware/LATEST
rsync -avz firmware/ pi@140.192.162.150:~/plant-sensor-server/firmware/
```

Wait 1–2 minutes. Confirm `green` on `/check` and `firmware_version` `pico-aht20-0.3` on `/api/latest`.

## Prerequisites

- Pico already has OTA bootstrap: `update.py` + `main.py` with OTA check (Step 1 complete).
- `secrets.py` on the Pico holds `SERVER_URL` and `NODE_ID` (not overwritten by OTA).
- Pi serves `/api/firmware/manifest` and `/api/firmware/file/...`.

## Publishing a new real release (not the test)

1. Copy or edit files in `firmware/releases/<version>/`.
2. Run `python3 scripts/build_firmware_manifest.py firmware/releases/<version>`.
3. Set `firmware/LATEST` to that version name.
4. Deploy `firmware/` to the Pi.

Bump `FIRMWARE_VERSION` inside the release `main.py` to match the folder name.

## Other innocuous test ideas

| Signal | Visible on `/check`? | Notes |
|--------|----------------------|--------|
| Integrity `yellow` | Yes | **Recommended** — used for this test |
| `FIRMWARE_VERSION` only | No (use `/api/latest`) | Proves OTA without UI change |
| Offset temperature | Yes | Avoid — looks like sensor failure |

See [ROADMAP.md](ROADMAP.md) for full OTA architecture.
