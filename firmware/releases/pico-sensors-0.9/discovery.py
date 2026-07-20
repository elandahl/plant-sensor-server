import sensors

RESCAN_INTERVAL_S = 900  # 15 minutes during development


def _hex_addr(addr):
    return hex(addr)


def _identify_address(i2c, addr):
    for driver in sensors.DRIVERS:
        if addr not in driver.ADDRESSES:
            continue
        try:
            if hasattr(driver, "identify"):
                info = driver.identify(i2c, addr)
                if info:
                    return info
            elif driver.probe(i2c, addr):
                return {
                    "driver": driver.DRIVER,
                    "address": _hex_addr(addr),
                    "label": driver.LABEL,
                }
        except OSError:
            continue
    return {
        "driver": "unknown",
        "address": _hex_addr(addr),
        "label": "unknown",
    }


def discover(i2c):
    attached = []
    sensor_errors = []
    seen_drivers = {}

    try:
        addresses = i2c.scan()
    except OSError as e:
        return attached, [{"code": "bus_scan_failed", "detail": str(e)}]

    for addr in sorted(addresses):
        entry = _identify_address(i2c, addr)
        attached.append(entry)

        if entry["driver"] == "unknown":
            sensor_errors.append({
                "address": entry["address"],
                "code": "unknown_device",
                "detail": "No driver matched this address",
            })
            continue

        driver_key = entry["driver"]
        if driver_key in seen_drivers:
            sensor_errors.append({
                "address": entry["address"],
                "code": "duplicate_or_ambiguous",
                "detail": "Multiple devices matched driver " + driver_key,
            })
        seen_drivers[driver_key] = entry["address"]

    return attached, sensor_errors


def read_all(i2c, attached):
    readings = {}
    sensor_errors = []

    for entry in attached:
        driver_name = entry["driver"]
        addr = int(entry["address"], 16)

        if driver_name == "unknown":
            continue

        driver = None
        for candidate in sensors.DRIVERS:
            if candidate.DRIVER == driver_name:
                driver = candidate
                break

        if driver is None:
            sensor_errors.append({
                "address": entry["address"],
                "code": "driver_missing",
                "detail": driver_name,
            })
            continue

        try:
            fragment = driver.read(i2c, addr)
            readings.update(fragment)
        except OSError as e:
            sensor_errors.append({
                "address": entry["address"],
                "code": "read_failed",
                "detail": str(e),
            })
        except Exception as e:
            sensor_errors.append({
                "address": entry["address"],
                "code": "read_failed",
                "detail": str(e),
            })

    return readings, sensor_errors


def inventory_signature(attached):
    parts = []
    for entry in attached:
        parts.append(entry["driver"] + "@" + entry["address"])
    return "|".join(sorted(parts))


def merge_sensor_errors(*error_lists):
    merged = []
    for errors in error_lists:
        merged.extend(errors)
    return merged


def integrity_from_errors(sensor_errors, base_state="green", base_score=1.0):
    if not sensor_errors:
        return {
            "state": base_state,
            "score": base_score,
            "mode": "sensor-discovery",
            "sensor_errors": [],
        }

    state = "yellow"
    for err in sensor_errors:
        if err.get("code") in ("duplicate_or_ambiguous", "bus_scan_failed"):
            state = "red"
            break

    return {
        "state": state,
        "score": 0.5 if state == "yellow" else 0.25,
        "mode": "sensor-discovery",
        "sensor_errors": sensor_errors,
    }
