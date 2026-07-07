from machine import Pin, reset
import network
import time
import urequests
import json
import secrets
import update
import i2c_bus
import discovery

FIRMWARE_VERSION = "pico-sensors-0.1"

SERVER_URL = secrets.SERVER_URL
SERVER_BASE = SERVER_URL.rsplit("/api/", 1)[0]
NODE_ID = secrets.NODE_ID

READ_INTERVAL_S = 60

led = Pin("LED", Pin.OUT)
i2c = i2c_bus.create_bus()

attached_sensors = []
last_scan_at = 0
last_inventory_sig = ""


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


def maybe_rescan():
    global attached_sensors, last_scan_at, last_inventory_sig

    now = time.time()
    if attached_sensors and (now - last_scan_at) < discovery.RESCAN_INTERVAL_S:
        return []

    attached_sensors, scan_errors = discovery.discover(i2c)
    last_scan_at = now

    sig = discovery.inventory_signature(attached_sensors)
    change_errors = []
    if last_inventory_sig and sig != last_inventory_sig:
        print("Inventory changed:", last_inventory_sig, "->", sig)
        change_errors.append({
            "code": "inventory_changed",
            "detail": last_inventory_sig + " -> " + sig,
        })
    last_inventory_sig = sig

    print("Attached sensors:", attached_sensors)
    return discovery.merge_sensor_errors(scan_errors, change_errors)


def build_payload(readings, sensor_errors):
    integrity = discovery.integrity_from_errors(sensor_errors)
    return {
        "node_id": NODE_ID,
        "firmware_version": FIRMWARE_VERSION,
        "timestamp_node": "",
        "attached_sensors": attached_sensors,
        "readings": readings,
        "integrity": integrity,
    }


def post_payload(payload, max_attempts=3):
    for attempt in range(1, max_attempts + 1):
        try:
            response = urequests.post(
                SERVER_URL,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
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
            rescan_errors = maybe_rescan()
            readings, read_errors = discovery.read_all(i2c, attached_sensors)
            sensor_errors = discovery.merge_sensor_errors(rescan_errors, read_errors)

            print("T:", readings.get("temperature_F"), "H:", readings.get("humidity_percent"))

            payload = build_payload(readings, sensor_errors)
            ok = post_payload(payload)

            if not ok:
                print("POST ultimately failed")

        except Exception as e:
            print("Sensor or payload error:", e)
    else:
        print("WiFi ultimately failed")

    led.off()
    time.sleep(READ_INTERVAL_S)
