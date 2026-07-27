"""TI TMP119 (Adafruit 6482) — high-precision I2C temperature.

Register map matches TMP117; device ID distinguishes the parts.
Reports tmp119_temperature_F so AHT20 can keep temperature_F.
"""

ADDRESSES = [0x48, 0x49]
LABEL = "TMP119"
DRIVER = "tmp119"

REG_TEMP_RESULT = 0x00
REG_DEVICE_ID = 0x0F

# DID[11:0] == 0x117 for TMP117/TMP119; high nibble is silicon revision.
DEVICE_ID_DID = 0x117
DEVICE_ID_MASK = 0x0FFF
TMP119_REVISION = 0x2  # full ID 0x2117
TMP117_REVISION = 0x0  # full ID 0x0117

RESOLUTION_C = 0.0078125


def _read_reg16(i2c, addr, reg):
    i2c.writeto(addr, bytes([reg]))
    data = i2c.readfrom(addr, 2)
    return (data[0] << 8) | data[1]


def _signed16(value):
    if value & 0x8000:
        value -= 0x10000
    return value


def identify(i2c, addr):
    if addr not in ADDRESSES:
        return None
    try:
        part_id = _read_reg16(i2c, addr, REG_DEVICE_ID)
    except OSError:
        return None
    if (part_id & DEVICE_ID_MASK) != DEVICE_ID_DID:
        return None
    rev = (part_id >> 12) & 0x0F
    label = "TMP119" if rev == TMP119_REVISION else "TMP117"
    return {
        "driver": DRIVER,
        "address": hex(addr),
        "label": label,
    }


def probe(i2c, addr):
    return identify(i2c, addr) is not None


def read(i2c, addr):
    raw = _signed16(_read_reg16(i2c, addr, REG_TEMP_RESULT))
    # Power-on / before first conversion: datasheet reports -256 °C
    if raw == -32768:
        raise OSError("TMP119 no conversion yet")
    temperature_C = raw * RESOLUTION_C
    temperature_F = temperature_C * 9 / 5 + 32
    return {
        "tmp119_temperature_F": temperature_F,
    }
