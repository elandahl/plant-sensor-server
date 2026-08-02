"""Arbitrate timed activities (BLE scan vs normal sensor loop)."""

BLE_SCAN_INTERVAL_S = 60
BLE_SCAN_DURATION_S = 15

_last_ble_scan_at = 0


def should_ble_scan(now):
    global _last_ble_scan_at
    if (now - _last_ble_scan_at) >= BLE_SCAN_INTERVAL_S:
        _last_ble_scan_at = now
        return True
    return False


def ble_scan_duration_s():
    return BLE_SCAN_DURATION_S
