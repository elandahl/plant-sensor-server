from machine import Pin, reset
import time
import urequests
import json
import secrets
import update
import i2c_bus
import discovery
import schedule
import wifi_link
import ble.scan as ble_scan

FIRMWARE_VERSION = "pico-sensors-0.93"

SERVER_URL = secrets.SERVER_URL
SERVER_BASE = SERVER_URL.rsplit("/api/", 1)[0]
NODE_ID = secrets.NODE_ID

READ_INTERVAL_S = 60

led = Pin("LED", Pin.OUT)
i2c = i2c_bus.create_bus()

attached_sensors = []
last_scan_at = 0
last_inventory_sig = ""


def maybe_ble_scan(wifi_rssi=None):
    now = time.time()
    if not schedule.should_ble_scan(now):
        return None, None

    if not wifi_link.rssi_ok_for_ble(wifi_rssi):
        print("BLE skip weak WiFi rssi", wifi_rssi)
        return None, None

    led.on()
    try:
        wifi_link.disconnect()
        result = ble_scan.run(schedule.ble_scan_duration_s())
        readings = result.get("readings", {})
        meta = result.get("meta")
        print("BLE scan:", readings)
        return readings, meta
    except Exception as e:
        print("BLE scan failed:", e)
        return None, None
    finally:
        led.off()
        wifi_link.wlan().active(True)


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


def build_payload(readings, sensor_errors, ble_readings=None, ble_scan_meta=None, wifi_info=None):
    merged = dict(readings)
    if ble_readings:
        merged.update(ble_readings)
    if wifi_info:
        if wifi_info.get("rssi") is not None:
            merged["wifi_rssi"] = wifi_info["rssi"]
        if wifi_info.get("bssid"):
            merged["wifi_bssid"] = wifi_info["bssid"]

    integrity = discovery.integrity_from_errors(sensor_errors)
    payload = {
        "node_id": NODE_ID,
        "firmware_version": FIRMWARE_VERSION,
        "timestamp_node": "",
        "attached_sensors": attached_sensors,
        "readings": merged,
        "integrity": integrity,
    }
    if ble_scan_meta:
        payload["ble_scan"] = ble_scan_meta
    return payload


def post_payload(payload, max_attempts=3):
    led.on()
    try:
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
    finally:
        led.off()


while True:
    led.off()

    if not wifi_link.connect():
        print("WiFi ultimately failed")
        led.off()
        time.sleep(READ_INTERVAL_S)
        continue

    wifi_info = wifi_link.link_info()
    ble_readings, ble_scan_meta = maybe_ble_scan(wifi_info.get("rssi"))

    # BLE (or skip path) may have dropped the radio — reassociate before POST.
    if not wifi_link.connect():
        print("WiFi ultimately failed after BLE")
        led.off()
        time.sleep(READ_INTERVAL_S)
        continue

    wifi_info = wifi_link.link_info()

    if update.check_and_apply(SERVER_BASE, FIRMWARE_VERSION):
        reset()

    try:
        rescan_errors = maybe_rescan()
        readings, read_errors = discovery.read_all(i2c, attached_sensors)
        sensor_errors = discovery.merge_sensor_errors(rescan_errors, read_errors)

        print("T:", readings.get("temperature_F"), "H:", readings.get("humidity_percent"),
              "rssi:", wifi_info.get("rssi"))

        payload = build_payload(
            readings, sensor_errors, ble_readings, ble_scan_meta, wifi_info
        )
        ok = post_payload(payload)

        if not ok:
            print("POST ultimately failed — forcing WiFi reset")
            wifi_link.force_reset()

    except Exception as e:
        print("Sensor or payload error:", e)

    led.off()
    time.sleep(READ_INTERVAL_S)
