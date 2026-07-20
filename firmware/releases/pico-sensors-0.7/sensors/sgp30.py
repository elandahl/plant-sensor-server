"""Sensirion SGP30 (Adafruit 3709) — eCO2 + TVOC over I2C."""

ADDRESSES = [0x58]
LABEL = "SGP30"
DRIVER = "sgp30"

# Adafruit: (feature_set & 0xF0) == 0x0020 for SGP30.
SGP30_FEATURESET_MASK = 0xF0
SGP30_FEATURESET = 0x20

CMD_GET_FEATURE_SET = b"\x20\x2F"
CMD_INIT_AIR_QUALITY = b"\x20\x03"
CMD_MEASURE_AIR_QUALITY = b"\x20\x08"
CMD_SET_HUMIDITY = b"\x20\x61"

_initialized = set()


def _crc8(data):
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x31) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def _sensirion_word(value):
    hi = (value >> 8) & 0xFF
    lo = value & 0xFF
    payload = bytes([hi, lo])
    return payload + bytes([_crc8(payload)])


def _verify_crc(data):
    if len(data) != 3:
        raise OSError("short SGP30 response")
    if _crc8(data[:2]) != data[2]:
        raise OSError("SGP30 CRC mismatch")
    return (data[0] << 8) | data[1]


def _read_words(i2c, addr, count):
    raw = i2c.readfrom(addr, count * 3)
    words = []
    for i in range(count):
        chunk = raw[i * 3:(i + 1) * 3]
        words.append(_verify_crc(chunk))
    return words


def _absolute_humidity_ticks(rh_percent, temp_c):
    """Sensirion fixed-point absolute humidity for Set_humidity (g/m^3 * 256)."""
    import math

    rh = max(0.0, min(100.0, rh_percent))
    t = temp_c
    # Magnus formula → water vapor pressure → absolute humidity g/m^3
    ah = 216.7 * (
        (rh / 100.0) * 6.112 * math.exp((17.62 * t) / (243.12 + t))
        / (273.15 + t)
    )
    ah = max(0.0, min(255.0, ah))
    return int(ah * 256 + 0.5) & 0xFFFF


def _compensation(i2c):
    import sensors.aht20 as aht20

    if not aht20.probe(i2c, 0x38):
        return None
    data = aht20.read(i2c, 0x38)
    temp_c = (data["temperature_F"] - 32) * 5 / 9
    return data["humidity_percent"], temp_c


def _ensure_init(i2c, addr):
    if addr in _initialized:
        return
    import time

    i2c.writeto(addr, CMD_INIT_AIR_QUALITY)
    time.sleep(0.01)
    _initialized.add(addr)


def probe(i2c, addr):
    if addr not in ADDRESSES:
        return False
    try:
        import time

        i2c.writeto(addr, CMD_GET_FEATURE_SET)
        time.sleep(0.01)
        feature = _verify_crc(i2c.readfrom(addr, 3))
        return (feature & SGP30_FEATURESET_MASK) == SGP30_FEATURESET
    except OSError:
        return False


def read(i2c, addr):
    import time

    _ensure_init(i2c, addr)

    comp = _compensation(i2c)
    if comp is not None:
        rh, temp_c = comp
        cmd = CMD_SET_HUMIDITY + _sensirion_word(
            _absolute_humidity_ticks(rh, temp_c)
        )
        i2c.writeto(addr, cmd)
        time.sleep(0.01)

    i2c.writeto(addr, CMD_MEASURE_AIR_QUALITY)
    time.sleep(0.015)
    eco2, tvoc = _read_words(i2c, addr, 2)

    # First ~15s after init the chip returns fixed 400 / 0.
    if eco2 == 400 and tvoc == 0:
        raise OSError("SGP30 warm-up")

    return {
        "co2_ppm": eco2,
        "tvoc_ppb": tvoc,
    }
