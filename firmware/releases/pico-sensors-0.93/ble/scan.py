"""Passive BLE scan via aioble."""

import asyncio
import aioble
import ble.dedup as dedup
import ble.scoring as scoring

DEFAULT_DURATION_S = 15


async def _scan_async(duration_ms):
    devices = {}
    async with aioble.scan(duration_ms, interval_us=30000, window_us=30000) as scanner:
        async for result in scanner:
            addr = bytes(result.device.addr)
            dedup.merge_advertisement(devices, addr, result.rssi)
    return devices


def run(duration_s=DEFAULT_DURATION_S):
    """Return readings fragment + ble_scan metadata dict."""
    duration_ms = int(duration_s * 1000)
    devices = asyncio.run(_scan_async(duration_ms))
    readings = scoring.score(devices)
    return {
        "readings": readings,
        "meta": {
            "window_s": duration_s,
            "advertisers": len(devices),
        },
    }
