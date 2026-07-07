"""Load sensor history from daily CSV files for plotting."""

import csv
import json
import os
import re

DATA_DIR = "data"
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.csv$")


def list_dates():
    if not os.path.isdir(DATA_DIR):
        return []
    dates = []
    for name in os.listdir(DATA_DIR):
        match = DATE_RE.match(name)
        if match:
            dates.append(match.group(1))
    return sorted(dates, reverse=True)


def csv_path(date_str):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return None
    path = os.path.join(DATA_DIR, f"{date_str}.csv")
    if not os.path.isfile(path):
        return None
    return path


def load_day(date_str, node_ids=None):
    path = csv_path(date_str)
    if path is None:
        return []

    wanted = set(node_ids) if node_ids else None
    records = []

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            node_id = row.get("node_id", "")
            if wanted is not None and node_id not in wanted:
                continue
            try:
                readings = json.loads(row.get("readings_json", "{}"))
            except (TypeError, json.JSONDecodeError):
                readings = {}
            if not isinstance(readings, dict):
                readings = {}
            records.append({
                "t": row.get("server_timestamp", ""),
                "node_id": node_id,
                "readings": readings,
            })

    records.sort(key=lambda r: r["t"])
    return records


def day_meta(date_str):
    records = load_day(date_str)
    nodes = []
    fields = set()
    seen_nodes = set()
    for record in records:
        node_id = record["node_id"]
        if node_id and node_id not in seen_nodes:
            seen_nodes.add(node_id)
            nodes.append(node_id)
        for key, value in record["readings"].items():
            if _is_numeric(value):
                fields.add(key)
    return {
        "date": date_str,
        "nodes": sorted(nodes),
        "fields": sorted(fields),
        "row_count": len(records),
    }


def _is_numeric(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return False


def _numeric(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def series_time(date_str, node_ids, field):
    records = load_day(date_str, node_ids)
    series = {node_id: [] for node_id in node_ids}

    for record in records:
        node_id = record["node_id"]
        if node_id not in series:
            continue
        value = _numeric(record["readings"].get(field))
        if value is None:
            continue
        series[node_id].append({"t": record["t"], "v": value})

    return {
        "mode": "time",
        "field": field,
        "series": series,
    }


def series_xy(date_str, node_ids, x_field, y_field):
    records = load_day(date_str, node_ids)
    series = {node_id: [] for node_id in node_ids}

    for record in records:
        node_id = record["node_id"]
        if node_id not in series:
            continue
        x_val = _numeric(record["readings"].get(x_field))
        y_val = _numeric(record["readings"].get(y_field))
        if x_val is None or y_val is None:
            continue
        series[node_id].append({
            "t": record["t"],
            "x": x_val,
            "y": y_val,
        })

    return {
        "mode": "xy",
        "x_field": x_field,
        "y_field": y_field,
        "series": series,
    }
