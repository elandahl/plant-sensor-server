"""Sensirion SCD40 / SCD41 (Adafruit STEMMA) — true NDIR CO2 + T/RH.

Both parts share I2C address 0x62 and the same command set; inventory
label is SCD4x. Readings are namespaced so ENS160 eCO2 co2_ppm is not
overwritten.
"""

ADDRESSES = [0x62]
LABEL = "SCD4x"
DRIVER = "scd4x"

CMD_START_PERIODIC = b"\x21\xb1"
CMD_STOP_PERIODIC = b"\x3f\x86"
CMD_READ_MEASUREMENT = b"\xec\x05"
CMD_DATA_READY = b"\xe4\xb8"
CMD_SERIAL_NUMBER = b"\x36\x82"

_started = set()
_cache = {}


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


def _verify_crc(data):
    if len(data) != 3:
        raise OSError("short SCD4x response")
    if _crc8(data[:2]) != data[2]:
        raise OSError("SCD4x CRC mismatch")
    return (data[0] << 8) | data[1]


def _read_words(i2c, addr, count):
    raw = i2c.readfrom(addr, count * 3)
    words = []
    for i in range(count):
        chunk = raw[i * 3:(i + 1) * 3]
        words.append(_verify_crc(chunk))
    return words


def _cmd(i2c, addr, cmd, delay_s=0.0):
    import time

    i2c.writeto(addr, cmd)
    if delay_s:
        time.sleep(delay_s)


def _data_ready(i2c, addr):
    _cmd(i2c, addr, CMD_DATA_READY, 0.001)
    word = _read_words(i2c, addr, 1)[0]
    # Ready when least-significant 11 bits are non-zero.
    return (word & 0x07FF) != 0


def _ensure_started(i2c, addr):
    if addr in _started:
        return
    import time

    # Stop in case a previous session left periodic mode running.
    try:
        _cmd(i2c, addr, CMD_STOP_PERIODIC, 0.5)
    except OSError:
        time.sleep(0.5)
    _cmd(i2c, addr, CMD_START_PERIODIC)
    _started.add(addr)


def probe(i2c, addr):
    if addr not in ADDRESSES:
        return False
    # Works while measuring.
    try:
        _data_ready(i2c, addr)
        return True
    except OSError:
        pass
    # Works in idle (before start_periodic).
    try:
        _cmd(i2c, addr, CMD_SERIAL_NUMBER, 0.001)
        _read_words(i2c, addr, 3)
        return True
    except OSError:
        return False


def identify(i2c, addr):
    if not probe(i2c, addr):
        return None
    return {
        "driver": DRIVER,
        "address": hex(addr),
        "label": LABEL,
    }


def read(i2c, addr):
    _ensure_started(i2c, addr)

    if _data_ready(i2c, addr):
        import time

        _cmd(i2c, addr, CMD_READ_MEASUREMENT, 0.001)
        co2, temp_raw, rh_raw = _read_words(i2c, addr, 3)
        temp_c = -45.0 + 175.0 * (temp_raw / 65535.0)
        rh = 100.0 * (rh_raw / 65535.0)
        _cache[addr] = {
            "scd4x_co2_ppm": int(co2),
            "scd4x_temperature_F": temp_c * 9 / 5 + 32,
            "scd4x_humidity_percent": rh,
        }

    cached = _cache.get(addr)
    if cached is None:
        raise OSError("SCD4x warm-up")
    return dict(cached)
