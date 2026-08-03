"""WiFi connect helpers tuned for weak Pico W / Plantnet links."""

import network
import time
import secrets

# Skip BLE radio time-slice when association is already marginal.
WEAK_WIFI_RSSI_DBM = -72

CONNECT_TIMEOUT_S = 20
MAX_CONNECT_ATTEMPTS = 4

_last_bssid = None


def wlan():
    return network.WLAN(network.STA_IF)


def _set_pm_none(radio):
    """Disable STA power-save; Pico W often looks connected while packets die."""
    try:
        radio.config(pm=network.WLAN.PM_NONE)
        return
    except Exception:
        pass
    try:
        # Documented cyw43 "none" value used in some MicroPython builds.
        radio.config(pm=0xA11140)
    except Exception:
        pass


def disconnect(radio=None):
    radio = radio or wlan()
    try:
        if radio.isconnected():
            radio.disconnect()
    except Exception:
        pass
    try:
        radio.active(False)
    except Exception:
        pass


def force_reset():
    """Full radio bounce — clears zombie associations after POST/TCP failures."""
    radio = wlan()
    disconnect(radio)
    time.sleep(1)
    radio.active(True)
    time.sleep(0.5)
    _set_pm_none(radio)


def _ssid_str(raw):
    if isinstance(raw, (bytes, bytearray)):
        try:
            return raw.decode()
        except Exception:
            return ""
    return raw or ""


def best_bssid(radio, ssid):
    """Return (rssi, bssid_bytes) for strongest matching AP, or None."""
    best = None
    try:
        scan = radio.scan()
    except Exception as e:
        print("WiFi scan failed:", e)
        return None

    for entry in scan:
        if _ssid_str(entry[0]) != ssid:
            continue
        rssi = entry[3]
        bssid = entry[1]
        if best is None or rssi > best[0]:
            best = (rssi, bssid)
    return best


def link_info(radio=None):
    """Return dict with rssi / bssid hex while associated, else empty fields."""
    global _last_bssid
    radio = radio or wlan()
    info = {"rssi": None, "bssid": _last_bssid}
    if not radio.isconnected():
        return info

    try:
        info["rssi"] = radio.status("rssi")
    except Exception:
        pass

    return info


def _bssid_hex(bssid):
    if not bssid:
        return None
    return ":".join("{:02x}".format(b) for b in bssid)


def connect(max_attempts=MAX_CONNECT_ATTEMPTS):
    global _last_bssid
    radio = wlan()
    radio.active(True)
    time.sleep(0.3)
    _set_pm_none(radio)

    if radio.isconnected():
        info = link_info(radio)
        print("WiFi already up", radio.ifconfig(), "rssi", info.get("rssi"))
        return True

    ssid = secrets.WIFI_SSID
    password = secrets.WIFI_PASSWORD

    for attempt in range(1, max_attempts + 1):
        print("WiFi attempt", attempt)
        best = best_bssid(radio, ssid)
        bssid = None
        if best:
            print("WiFi best AP rssi", best[0], _bssid_hex(best[1]))
            bssid = best[1]
            _last_bssid = _bssid_hex(bssid)
        else:
            print("WiFi no AP for", ssid, "- trying open connect")
            _last_bssid = None

        try:
            if bssid:
                radio.connect(ssid, password, bssid=bssid)
            else:
                radio.connect(ssid, password)
        except Exception as e:
            print("WiFi connect error:", e)

        start = time.time()
        while not radio.isconnected():
            if time.time() - start > CONNECT_TIMEOUT_S:
                break
            time.sleep(1)

        if radio.isconnected():
            info = link_info(radio)
            print("WiFi connected:", radio.ifconfig(), "rssi", info.get("rssi"))
            return True

        print("WiFi failed, radio reset")
        force_reset()
        backoff = attempt * 5
        print("WiFi backoff", backoff, "s")
        time.sleep(backoff)

    return False


def rssi_ok_for_ble(rssi):
    if rssi is None:
        return True
    return rssi > WEAK_WIFI_RSSI_DBM
