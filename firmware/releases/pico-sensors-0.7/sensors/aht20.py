ADDRESSES = [0x38]
LABEL = "AHT20"
DRIVER = "aht20"


def probe(i2c, addr):
    if addr not in ADDRESSES:
        return False
    try:
        i2c.writeto(addr, b'\xBE\x08\x00')
        return True
    except OSError:
        return False


def read(i2c, addr):
    import time

    i2c.writeto(addr, b'\xBE\x08\x00')
    time.sleep(0.01)

    i2c.writeto(addr, b'\xAC\x33\x00')
    time.sleep(0.08)

    data = i2c.readfrom(addr, 6)

    raw_humidity = ((data[1] << 16) | (data[2] << 8) | data[3]) >> 4
    humidity = raw_humidity * 100 / 1048576

    raw_temp = ((data[3] & 0x0F) << 16) | (data[4] << 8) | data[5]
    temperature_C = raw_temp * 200 / 1048576 - 50
    temperature_F = temperature_C * 9 / 5 + 32

    return {
        "temperature_F": temperature_F,
        "humidity_percent": humidity,
    }
