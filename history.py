"""Load sensor history from daily CSV files for plotting."""

import csv
import json
import os
import re
from datetime import datetime, timezone

DATA_DIR = "data"
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.csv$")
DEFAULT_DIFF_TOL_S = 60.0


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
    fields_by_node = {}
    seen_nodes = set()
    for record in records:
        node_id = record["node_id"]
        if node_id and node_id not in seen_nodes:
            seen_nodes.add(node_id)
            nodes.append(node_id)
            fields_by_node[node_id] = set()
        if not node_id:
            continue
        for key, value in record["readings"].items():
            if _is_numeric(value):
                fields.add(key)
                fields_by_node[node_id].add(key)
    return {
        "date": date_str,
        "nodes": sorted(nodes),
        "fields": sorted(fields),
        "fields_by_node": {
            node: sorted(fields_by_node.get(node, []))
            for node in sorted(nodes)
        },
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


def _parse_ts(value):
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def series_time(date_str, node_ids, fields):
    records = load_day(date_str, node_ids)
    series = {}
    for node_id in node_ids:
        for field in fields:
            series[f"{node_id}\u2022{field}"] = {
                "node": node_id,
                "field": field,
                "points": [],
            }

    for record in records:
        node_id = record["node_id"]
        if node_id not in node_ids:
            continue
        for field in fields:
            value = _numeric(record["readings"].get(field))
            if value is None:
                continue
            series[f"{node_id}\u2022{field}"]["points"].append(
                {"t": record["t"], "v": value}
            )

    return {
        "mode": "time",
        "fields": fields,
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


def parse_diff_specs(raw):
    """Parse 'A:fieldA-B:fieldB,A:f2-B:f2' into list of dicts."""
    specs = []
    for part in _split_diff_list(raw):
        match = re.match(
            r"^([^:]+):([^-]+)-([^:]+):(.+)$",
            part,
        )
        if not match:
            continue
        specs.append({
            "node_a": match.group(1).strip(),
            "field_a": match.group(2).strip(),
            "node_b": match.group(3).strip(),
            "field_b": match.group(4).strip(),
        })
    return specs


def _split_diff_list(raw):
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _extract_series(records, node_id, field):
    points = []
    for record in records:
        if record["node_id"] != node_id:
            continue
        value = _numeric(record["readings"].get(field))
        if value is None:
            continue
        ts = _parse_ts(record["t"])
        if ts is None:
            continue
        points.append({"t": record["t"], "ts": ts, "v": value})
    return points


def _nearest_diff(series_a, series_b, tol_s):
    """For each point in A, subtract nearest B within tol_s. Returns points + stats."""
    if not series_a or not series_b:
        return [], {"matched": 0, "unmatched": len(series_a)}

    points = []
    unmatched = 0
    j = 0
    n_b = len(series_b)

    for a in series_a:
        while j + 1 < n_b and series_b[j + 1]["ts"] <= a["ts"]:
            j += 1
        candidates = [series_b[j]]
        if j + 1 < n_b:
            candidates.append(series_b[j + 1])
        if j > 0:
            candidates.append(series_b[j - 1])
        best = min(candidates, key=lambda b: abs(b["ts"] - a["ts"]))
        best_dt = abs(best["ts"] - a["ts"])
        if best_dt > tol_s:
            unmatched += 1
            continue
        points.append({
            "t": a["t"],
            "v": a["v"] - best["v"],
            "dt_s": round(best["ts"] - a["ts"], 3),
        })

    return points, {"matched": len(points), "unmatched": unmatched}


def series_diff(date_str, diff_specs, tol_s=DEFAULT_DIFF_TOL_S):
    node_ids = sorted({
        spec["node_a"] for spec in diff_specs
    } | {
        spec["node_b"] for spec in diff_specs
    })
    records = load_day(date_str, node_ids)
    series = {}
    stats = {}

    for spec in diff_specs:
        node_a = spec["node_a"]
        field_a = spec["field_a"]
        node_b = spec["node_b"]
        field_b = spec["field_b"]
        label = f"{node_a}\u2022{field_a} \u2212 {node_b}\u2022{field_b}"
        key = f"{node_a}:{field_a}-{node_b}:{field_b}"

        series_a = _extract_series(records, node_a, field_a)
        series_b = _extract_series(records, node_b, field_b)

        if node_a == node_b and field_a != field_b:
            # Same timestamps when same node: exact join on t
            by_t = {p["t"]: p["v"] for p in series_b}
            points = []
            unmatched = 0
            for a in series_a:
                if a["t"] not in by_t:
                    unmatched += 1
                    continue
                points.append({
                    "t": a["t"],
                    "v": a["v"] - by_t[a["t"]],
                    "dt_s": 0.0,
                })
            entry_stats = {"matched": len(points), "unmatched": unmatched}
        else:
            points, entry_stats = _nearest_diff(series_a, series_b, tol_s)

        series[key] = {
            "label": label,
            "node_a": node_a,
            "field_a": field_a,
            "node_b": node_b,
            "field_b": field_b,
            "points": points,
        }
        stats[key] = entry_stats

    return {
        "mode": "diff",
        "tol_s": tol_s,
        "series": series,
        "stats": stats,
    }
