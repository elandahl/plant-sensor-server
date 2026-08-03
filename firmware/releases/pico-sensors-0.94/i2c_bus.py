from machine import Pin, I2C

SDA_PIN = 4
SCL_PIN = 5
I2C_FREQ = 100000


def create_bus():
    return I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)
