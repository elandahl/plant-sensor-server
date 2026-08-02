"""Sensirion SCD30 (Adafruit STEMMA) — true NDIR CO2 + T/RH at 0x61.

Readings are namespaced (scd30_*) so ENS160 eCO2 co2_ppm is not overwritten.
"""

ADDRESSES = [0x61]
LABEL = "SCD30"
DRIVER = "scd30"

CMD_CONTINUOUS_MEASUREMENT = 0x0010
CMD_GET_DATA_READY = 0x0202
CMD_READ_MEASUREMENT = 0x0300
CMD_READ_FIRMWARE = 0xD100
CMD_SET_MEASUREMENT_INTERVAL = 0x4600

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


def _send_command(i2c, addr, command, argument=None):
    import time

    buf = bytearray(5)
    buf[0] = (command >> 8) & 0xFF
    buf[1] = command & 0xFF
    if argument is None:
        i2c.writeto(addr, buf[:2])
    else:
        hi = (argument >> 8) & 0xFF
        lo = argument & 0xFF
        buf[2] = hi
        buf[3] = lo
        buf[4] = _crc8(bytes([hi, lo]))
        i2c.writeto(addr, buf)
    # Datasheet: >3 ms before a following read; Adafruit uses ~50 ms.
    time.sleep(0.05)


def _read_register(i2c, addr, command):
    import time

    cmd = bytes([(command >> 8) & 0xFF, command & 0xFF])
    i2c.writeto(addr, cmd)
    time.sleep(0.01)
    raw = i2c.readfrom(addr, 3)
    if _crc8(raw[:2]) != raw[2]:
        raise OSError("SCD30 CRC mismatch")
    return (raw[0] << 8) | raw[1]


def _unpack_float(b0, b1, b2, b3):
    import struct

    return struct.unpack(">f", bytes([b0, b1, b2, b3]))[0]


def _ensure_started(i2c, addr):
    if addr in _started:
        return
    # 2 s interval is the SCD30 default and matches our ~60 s submit loop.
    try:
        _send_command(i2c, addr, CMD_SET_MEASUREMENT_INTERVAL, 2)
    except OSError:
        pass
    _send_command(i2c, addr, CMD_CONTINUOUS_MEASUREMENT, 0)
    _started.add(addr)


def probe(i2c, addr):
    if addr not in ADDRESSES:
        return False
    try:
        _read_register(i2c, addr, CMD_READ_FIRMWARE)
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
    import time

    _ensure_started(i2c, addr)

    ready = _read_register(i2c, addr, CMD_GET_DATA_READY)
    if ready:
        _send_command(i2c, addr, CMD_READ_MEASUREMENT)
        raw = i2c.readfrom(addr, 18)
        for i in range(0, 18, 3):
            if _crc8(raw[i:i + 2]) != raw[i + 2]:
                raise OSError("SCD30 CRC mismatch")
        co2 = _unpack_float(raw[0], raw[1], raw[3], raw[4])
        temp_c = _unpack_float(raw[6], raw[7], raw[9], raw[10])
        rh = _unpack_float(raw[12], raw[13], raw[15], raw[16])
        _cache[addr] = {
            "scd30_co2_ppm": int(co2 + 0.5),
            "scd30_temperature_F": temp_c * 9 / 5 + 32,
            "scd30_humidity_percent": rh,
        }

    cached = _cache.get(addr)
    if cached is None:
        raise OSError("SCD30 warm-up")
    return dict(cached)
