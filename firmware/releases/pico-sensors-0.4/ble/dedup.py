"""In-window BLE advertiser dedup: keep strongest RSSI per address."""


def merge_advertisement(devices, addr, rssi):
    if addr not in devices or rssi > devices[addr]:
        devices[addr] = rssi


def count_close(devices, threshold_dbm):
    close = 0
    for rssi in devices.values():
        if rssi >= threshold_dbm:
            close += 1
    return close
