ADDRESSES = [0x59]
LABEL = "SGP40"
DRIVER = "sgp40"

CMD_MEASURE_RAW = b"\x26\x0F"
CMD_GET_FEATURE_SET = b"\x20\x2F"


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


def _rh_ticks(rh_percent):
    rh = max(0.0, min(100.0, rh_percent))
    return int(rh * 65535 / 100 + 0.5)


def _temp_ticks(temp_c):
    temp = max(-45.0, min(130.0, temp_c))
    return int((temp + 45) * 65535 / 175 + 0.5)


def _verify_crc(data):
    if len(data) != 3:
        raise OSError("short SGP40 response")
    if _crc8(data[:2]) != data[2]:
        raise OSError("SGP40 CRC mismatch")
    return (data[0] << 8) | data[1]


def _compensation(i2c):
    import sensors.aht20 as aht20

    if not aht20.probe(i2c, 0x38):
        return 50.0, 25.0

    data = aht20.read(i2c, 0x38)
    temp_c = (data["temperature_F"] - 32) * 5 / 9
    return data["humidity_percent"], temp_c


def probe(i2c, addr):
    if addr not in ADDRESSES:
        return False
    try:
        i2c.writeto(addr, CMD_GET_FEATURE_SET)
        import time

        time.sleep(0.01)
        data = i2c.readfrom(addr, 3)
        _verify_crc(data)
        return True
    except OSError:
        return False


def read(i2c, addr):
    import time

    rh, temp_c = _compensation(i2c)
    cmd = CMD_MEASURE_RAW + _sensirion_word(_rh_ticks(rh)) + _sensirion_word(_temp_ticks(temp_c))
    i2c.writeto(addr, cmd)
    time.sleep(0.03)
    raw = _verify_crc(i2c.readfrom(addr, 3))
    return {"voc_raw": raw}
