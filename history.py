"""Load sensor history from daily CSV files for plotting."""

import csv
import json
import os
import re
from datetime import datetime, timedelta, timezone

DATA_DIR = "data"
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.csv$")
DEFAULT_DIFF_TOL_S = 60.0
MAX_SERIES_POINTS = 5000


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


def parse_date(date_str):
    if not date_str or not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def resolve_range(start=None, end=None, date=None):
    """Return (start_str, end_str) inclusive, or None if invalid/empty."""
    if date and not start and not end:
        start = date
        end = date
    if not start and not end:
        return None
    if start and not end:
        end = start
    if end and not start:
        start = end
    start_d = parse_date(start)
    end_d = parse_date(end)
    if start_d is None or end_d is None:
        return None
    if end_d < start_d:
        start_d, end_d = end_d, start_d
    return start_d.isoformat(), end_d.isoformat()


def dates_in_range(start_str, end_str):
    start_d = parse_date(start_str)
    end_d = parse_date(end_str)
    if start_d is None or end_d is None or end_d < start_d:
        return []
    available = set(list_dates())
    days = []
    cur = start_d
    while cur <= end_d:
        key = cur.isoformat()
        if key in available:
            days.append(key)
        cur += timedelta(days=1)
    return days


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


def load_range(start_str, end_str, node_ids=None, after_ts=None, before_ts=None):
    records = []
    for day in dates_in_range(start_str, end_str):
        records.extend(load_day(day, node_ids))
    records.sort(key=lambda r: r["t"])
    if after_ts is None and before_ts is None:
        return records
    filtered = []
    for record in records:
        ts = _parse_ts(record["t"])
        if ts is None:
            continue
        if after_ts is not None and ts < after_ts:
            continue
        if before_ts is not None and ts > before_ts:
            continue
        filtered.append(record)
    return filtered


def day_meta(date_str):
    return range_meta(date_str, date_str)


def range_meta(start_str, end_str):
    days = dates_in_range(start_str, end_str)
    if not days:
        return None
    records = load_range(start_str, end_str)
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
        "start": start_str,
        "end": end_str,
        "date": start_str if start_str == end_str else None,
        "days": days,
        "day_count": len(days),
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


def parse_time_bound(value):
    """Parse ISO timestamp or epoch seconds into float epoch, or None."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    return _parse_ts(value)


def _downsample_points(points, max_points=MAX_SERIES_POINTS):
    if max_points <= 0 or len(points) <= max_points:
        return points
    stride = max(1, (len(points) + max_points - 1) // max_points)
    sampled = points[::stride]
    if sampled[-1] is not points[-1]:
        sampled.append(points[-1])
    return sampled


def series_time(start_str, end_str, node_ids, fields, after_ts=None, before_ts=None):
    records = load_range(start_str, end_str, node_ids, after_ts, before_ts)
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

    for entry in series.values():
        entry["points"] = _downsample_points(entry["points"])

    return {
        "mode": "time",
        "start": start_str,
        "end": end_str,
        "fields": fields,
        "series": series,
    }


def series_xy(start_str, end_str, node_ids, x_field, y_field, after_ts=None, before_ts=None):
    records = load_range(start_str, end_str, node_ids, after_ts, before_ts)
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

    for node_id in series:
        series[node_id] = _downsample_points(series[node_id])

    return {
        "mode": "xy",
        "start": start_str,
        "end": end_str,
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


def series_diff(start_str, end_str, diff_specs, tol_s=DEFAULT_DIFF_TOL_S,
                after_ts=None, before_ts=None):
    node_ids = sorted({
        spec["node_a"] for spec in diff_specs
    } | {
        spec["node_b"] for spec in diff_specs
    })
    records = load_range(start_str, end_str, node_ids, after_ts, before_ts)
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

        points = _downsample_points(points)
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
        "start": start_str,
        "end": end_str,
        "tol_s": tol_s,
        "series": series,
        "stats": stats,
    }
