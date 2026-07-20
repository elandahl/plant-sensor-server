"""ScioSense ENS160 / ENS161 (Adafruit STEMMA) — eCO2, TVOC, AQI."""

ADDRESSES = [0x53, 0x52]
LABEL = "ENS160"  # overridden per-device via identify()
DRIVER = "ens160"

PART_ID_ENS160 = 0x0160
PART_ID_ENS161 = 0x0161
PART_IDS = {PART_ID_ENS160, PART_ID_ENS161}

REG_PART_ID = 0x00
REG_OPMODE = 0x10
REG_TEMP_IN = 0x13
REG_RH_IN = 0x15
REG_STATUS = 0x20
REG_DATA_AQI = 0x21
REG_DATA_AQI_S = 0x26

OPMODE_STANDARD = 0x02

_initialized = set()


def _read_reg8(i2c, addr, reg):
    i2c.writeto(addr, bytes([reg]))
    return i2c.readfrom(addr, 1)[0]


def _read_reg16(i2c, addr, reg):
    i2c.writeto(addr, bytes([reg]))
    data = i2c.readfrom(addr, 2)
    return data[0] | (data[1] << 8)


def _write_reg8(i2c, addr, reg, value):
    i2c.writeto(addr, bytes([reg, value]))


def _write_reg16(i2c, addr, reg, value):
    i2c.writeto(addr, bytes([reg, value & 0xFF, (value >> 8) & 0xFF]))


def _compensation(i2c):
    import sensors.aht20 as aht20

    if not aht20.probe(i2c, 0x38):
        return 50.0, 25.0

    data = aht20.read(i2c, 0x38)
    temp_c = (data["temperature_F"] - 32) * 5 / 9
    return data["humidity_percent"], temp_c


def _ensure_standard_mode(i2c, addr):
    if addr in _initialized:
        return
    import time

    _write_reg8(i2c, addr, REG_OPMODE, OPMODE_STANDARD)
    time.sleep(0.01)
    _initialized.add(addr)


def _write_compensation(i2c, addr, rh, temp_c):
    rh_val = int(rh * 512 + 0.5)
    temp_k = int((temp_c + 273.15) * 64 + 0.5)
    _write_reg16(i2c, addr, REG_TEMP_IN, temp_k)
    _write_reg16(i2c, addr, REG_RH_IN, rh_val)


def _label_for_part(part_id):
    if part_id == PART_ID_ENS161:
        return "ENS161"
    return "ENS160"


def identify(i2c, addr):
    """Return inventory dict if this address is ENS160/161, else None."""
    if addr not in ADDRESSES:
        return None
    try:
        part_id = _read_reg16(i2c, addr, REG_PART_ID)
        if part_id not in PART_IDS:
            return None
        return {
            "driver": DRIVER,
            "address": hex(addr),
            "label": _label_for_part(part_id),
            "part_id": part_id,
        }
    except OSError:
        return None


def probe(i2c, addr):
    return identify(i2c, addr) is not None


def read(i2c, addr):
    _ensure_standard_mode(i2c, addr)

    rh, temp_c = _compensation(i2c)
    _write_compensation(i2c, addr, rh, temp_c)

    status = _read_reg8(i2c, addr, REG_STATUS)
    validity = (status >> 2) & 0x03
    if validity == 1:
        raise OSError("ENS16x warm-up")
    if validity == 2:
        raise OSError("ENS16x initial start-up")
    if validity == 3:
        raise OSError("ENS16x invalid output")
    if not (status & 0x02):
        raise OSError("ENS16x no new data")

    part_id = _read_reg16(i2c, addr, REG_PART_ID)

    i2c.writeto(addr, bytes([REG_DATA_AQI]))
    data = i2c.readfrom(addr, 5)

    # UBA AQI is 3 bits, values 1–5 (Excellent … Unhealthy)
    aqi = data[0] & 0x07
    tvoc = data[1] | (data[2] << 8)
    eco2 = data[3] | (data[4] << 8)

    result = {
        "co2_ppm": eco2,
        "tvoc_ppb": tvoc,
        "aqi": aqi,
    }

    # ENS161: ScioSense relative AQI-S, 0–500 (100 ≈ recent average)
    if part_id == PART_ID_ENS161:
        result["aqi_s"] = _read_reg16(i2c, addr, REG_DATA_AQI_S)

    return result
