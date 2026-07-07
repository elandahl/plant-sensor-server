ADDRESSES = [0x53, 0x52]
LABEL = "ENS160"
DRIVER = "ens160"

PART_IDS = {0x0160, 0x0161}

REG_PART_ID = 0x00
REG_OPMODE = 0x10
REG_TEMP_IN = 0x13
REG_RH_IN = 0x15
REG_STATUS = 0x20
REG_DATA_AQI = 0x21

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


def probe(i2c, addr):
    if addr not in ADDRESSES:
        return False
    try:
        part_id = _read_reg16(i2c, addr, REG_PART_ID)
        return part_id in PART_IDS
    except OSError:
        return False


def read(i2c, addr):
    _ensure_standard_mode(i2c, addr)

    rh, temp_c = _compensation(i2c)
    _write_compensation(i2c, addr, rh, temp_c)

    status = _read_reg8(i2c, addr, REG_STATUS)
    validity = (status >> 2) & 0x03
    if validity == 1:
        raise OSError("ENS160 warm-up")
    if validity == 2:
        raise OSError("ENS160 initial start-up")
    if validity == 3:
        raise OSError("ENS160 invalid output")
    if not (status & 0x02):
        raise OSError("ENS160 no new data")

    i2c.writeto(addr, bytes([REG_DATA_AQI]))
    data = i2c.readfrom(addr, 5)

    aqi = data[0] & 0x03
    tvoc = data[1] | (data[2] << 8)
    eco2 = data[3] | (data[4] << 8)

    return {
        "co2_ppm": eco2,
        "tvoc_ppb": tvoc,
        "aqi": aqi,
    }
