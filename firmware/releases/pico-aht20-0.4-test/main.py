from machine import Pin, I2C, reset
import network
import time
import urequests
import json
import secrets
import update

FIRMWARE_VERSION = "pico-aht20-0.4-test"

SERVER_URL = secrets.SERVER_URL
SERVER_BASE = SERVER_URL.rsplit("/api/", 1)[0]
NODE_ID = secrets.NODE_ID

AHT20_ADDR = 0x38
READ_INTERVAL_S = 60

led = Pin("LED", Pin.OUT)
i2c = I2C(0, sda=Pin(4), scl=Pin(5), freq=100000)


def connect_wifi(max_attempts=3):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if wlan.isconnected():
        return True

    for attempt in range(1, max_attempts + 1):
        print("WiFi attempt", attempt)
        wlan.connect(secrets.WIFI_SSID, secrets.WIFI_PASSWORD)

        start = time.time()
        while not wlan.isconnected():
            if time.time() - start > 15:
                break
            time.sleep(1)

        if wlan.isconnected():
            print("WiFi connected:", wlan.ifconfig())
            return True

        backoff = attempt * 5
        print("WiFi failed, backing off", backoff, "s")
        time.sleep(backoff)

    return False


def read_aht20():
    i2c.writeto(AHT20_ADDR, b'\xBE\x08\x00')
    time.sleep(0.01)

    i2c.writeto(AHT20_ADDR, b'\xAC\x33\x00')
    time.sleep(0.08)

    data = i2c.readfrom(AHT20_ADDR, 6)

    raw_humidity = ((data[1] << 16) | (data[2] << 8) | data[3]) >> 4
    humidity = raw_humidity * 100 / 1048576

    raw_temp = ((data[3] & 0x0F) << 16) | (data[4] << 8) | data[5]
    temperature_C = raw_temp * 200 / 1048576 - 50
    temperature_F = temperature_C * 9 / 5 + 32

    return temperature_F, humidity


def build_payload(temp, humidity):
    return {
        "node_id": NODE_ID,
        "firmware_version": FIRMWARE_VERSION,
        "timestamp_node": "",
        "readings": {
            "temperature_F": temp,
            "humidity_percent": humidity
        },
        "integrity": {
            "state": "yellow",
            "score": 0.5,
            "mode": "ota-test"
        }
    }


def post_payload(payload, max_attempts=3):
    for attempt in range(1, max_attempts + 1):
        try:
            response = urequests.post(
                SERVER_URL,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload)
            )

            status = response.status_code
            text = response.text
            response.close()

            print("POST", status, text)

            if 200 <= status < 300:
                return True

        except Exception as e:
            print("POST failed:", e)

        backoff = attempt * 5
        print("POST backoff", backoff, "s")
        time.sleep(backoff)

    return False


while True:
    led.on()

    if connect_wifi():
        if update.check_and_apply(SERVER_BASE, FIRMWARE_VERSION):
            reset()

        try:
            temp, humidity = read_aht20()
            print("T:", temp, "H:", humidity)

            payload = build_payload(temp, humidity)
            ok = post_payload(payload)

            if not ok:
                print("POST ultimately failed")

        except Exception as e:
            print("Sensor or payload error:", e)
    else:
        print("WiFi ultimately failed")

    led.off()
    time.sleep(READ_INTERVAL_S)
