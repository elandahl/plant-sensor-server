#!/usr/bin/env python3
"""Periodic Plantnet / plant-server health probe.

Logs one compact line per run so we can tell Ethernet, Flask, and
sensor-post failures apart after the fact.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

IFACE = os.environ.get("PLANT_HEALTH_IFACE", "eth0")
GATEWAY = os.environ.get("PLANT_HEALTH_GATEWAY", "192.168.1.1")
HEALTH_URL = os.environ.get("PLANT_HEALTH_URL", "http://127.0.0.1:5000/api/health")
LATEST_URL = os.environ.get("PLANT_LATEST_URL", "http://127.0.0.1:5000/api/latest")
STALE_NODE_S = int(os.environ.get("PLANT_STALE_NODE_S", "300"))
LOG_DIR = Path(os.environ.get("PLANT_HEALTH_LOG_DIR", "/home/pi/plant-sensor-server/logs"))
LOG_FILE = LOG_DIR / "network-health.log"


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_sys(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return "missing"


def iface_ipv4(iface):
    try:
        out = subprocess.check_output(
            ["ip", "-4", "-o", "addr", "show", "dev", iface],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    for line in out.splitlines():
        parts = line.split()
        if "inet" in parts:
            idx = parts.index("inet")
            if idx + 1 < len(parts):
                return parts[idx + 1].split("/")[0]
    return ""


def ping_ok(host, timeout_s=2):
    try:
        subprocess.check_call(
            ["ping", "-c", "1", "-W", str(timeout_s), host],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def http_json(url, timeout_s=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(body)
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


def tailscale_ipv4():
    try:
        out = subprocess.check_output(
            ["tailscale", "ip", "-4"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        return out.strip().splitlines()[0] if out.strip() else ""
    except Exception:
        return ""


def summarize_nodes(latest):
    if not latest:
        return "nodes=0", ["NO_NODES"]

    now = time.time()
    parts = []
    flags = []
    oldest_age = None
    freshest_age = None

    for node_id, record in sorted(latest.items()):
        age = record.get("data_age_s")
        if age is None:
            ts = record.get("server_timestamp")
            if ts:
                try:
                    age = now - datetime.fromisoformat(ts).timestamp()
                except ValueError:
                    age = None
        if age is None:
            parts.append(f"{node_id}=?")
            flags.append(f"BAD_AGE:{node_id}")
            continue

        age_i = int(age)
        parts.append(f"{node_id}={age_i}s")
        oldest_age = age_i if oldest_age is None else max(oldest_age, age_i)
        freshest_age = age_i if freshest_age is None else min(freshest_age, age_i)
        if age_i > STALE_NODE_S:
            flags.append(f"STALE:{node_id}")

    summary = "nodes=" + ",".join(parts)
    if freshest_age is not None:
        summary += f" freshest={freshest_age}s oldest={oldest_age}s"
    return summary, flags


def main():
    carrier = read_sys(f"/sys/class/net/{IFACE}/carrier")
    operstate = read_sys(f"/sys/class/net/{IFACE}/operstate")
    speed = read_sys(f"/sys/class/net/{IFACE}/speed")
    ip4 = iface_ipv4(IFACE)
    gw_ok = ping_ok(GATEWAY)
    health_code, health_body = http_json(HEALTH_URL)
    latest_code, latest_body = http_json(LATEST_URL)
    ts_ip = tailscale_ipv4()

    flags = []
    if carrier != "1":
        flags.append("NO_CARRIER")
    if operstate != "up":
        flags.append(f"OPER:{operstate}")
    if not ip4:
        flags.append("NO_IPV4")
    if not gw_ok:
        flags.append("GATEWAY_DOWN")
    if health_code != 200:
        flags.append(f"FLASK_HEALTH:{health_code}")
    elif not isinstance(health_body, dict) or health_body.get("status") != "ok":
        flags.append("FLASK_NOT_OK")

    if latest_code != 200 or not isinstance(latest_body, dict):
        flags.append(f"FLASK_LATEST:{latest_code}")
        node_summary = "nodes=?"
    else:
        node_summary, node_flags = summarize_nodes(latest_body)
        flags.extend(node_flags)

    if not ts_ip:
        flags.append("TAILSCALE_IP_MISSING")

    status = "OK" if not flags else "WARN"
    line = (
        f"{now_iso()} {status} iface={IFACE} carrier={carrier} "
        f"oper={operstate} speed={speed} ip={ip4 or '-'} "
        f"gw={GATEWAY}:{'up' if gw_ok else 'down'} "
        f"flask={health_code} ts={ts_ip or '-'} {node_summary}"
    )
    if flags:
        line += " flags=" + ",".join(flags)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

    print(line)
    # Always exit 0 so systemd timer stays healthy; WARN/OK is in the log line.
    return 0


if __name__ == "__main__":
    # Avoid DNS surprises if someone overrides URLs with hostnames.
    socket.setdefaulttimeout(5)
    sys.exit(main())