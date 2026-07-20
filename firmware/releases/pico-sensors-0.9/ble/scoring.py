"""Map BLE scan table to occupancy metrics."""

CLOSE_RSSI_DBM = -75


def score(devices):
    seen = len(devices)
    close = 0
    for rssi in devices.values():
        if rssi >= CLOSE_RSSI_DBM:
            close += 1

    if close >= 6 or seen >= 15:
        estimate = 3
        band = "high"
    elif close >= 3 or seen >= 8:
        estimate = 2
        band = "medium"
    elif seen >= 2:
        estimate = 1
        band = "low"
    else:
        estimate = 0
        band = "low"

    return {
        "ble_devices_seen": seen,
        "ble_devices_close": close,
        "occupancy_estimate": estimate,
        "occupancy_band": band,
    }
