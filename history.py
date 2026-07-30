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


def parse_series_specs(raw):
    """Parse 'Node:field,Node:field' into list of {node, field}."""
    specs = []
    for part in _split_csv_list(raw):
        match = re.match(r"^([^:]+):(.+)$", part)
        if not match:
            continue
        specs.append({
            "node": match.group(1).strip(),
            "field": match.group(2).strip(),
        })
    return specs


def series_time(start_str, end_str, node_ids, fields, after_ts=None, before_ts=None):
    """Legacy: cartesian product of nodes × fields."""
    specs = [
        {"node": node_id, "field": field}
        for node_id in node_ids
        for field in fields
    ]
    return series_time_specs(
        start_str, end_str, specs,
        after_ts=after_ts, before_ts=before_ts,
    )


def series_time_specs(start_str, end_str, specs, after_ts=None, before_ts=None):
    """Explicit series list: each {node, field} is one line."""
    node_ids = sorted({spec["node"] for spec in specs})
    fields = sorted({spec["field"] for spec in specs})
    records = load_range(start_str, end_str, node_ids, after_ts, before_ts)
    series = {}
    for spec in specs:
        node_id = spec["node"]
        field = spec["field"]
        key = f"{node_id}\u2022{field}"
        if key not in series:
            series[key] = {
                "node": node_id,
                "field": field,
                "points": [],
            }

    wanted = {(spec["node"], spec["field"]) for spec in specs}
    for record in records:
        node_id = record["node_id"]
        for field in fields:
            if (node_id, field) not in wanted:
                continue
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
    """Legacy same-node X vs Y scatter."""
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
    for part in _split_csv_list(raw):
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


def _split_csv_list(raw):
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


# Back-compat alias
_split_diff_list = _split_csv_list


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


def _nearest_pair(series_a, series_b, tol_s):
    """For each point in A, pair with nearest B within tol_s → {t,x,y,dt_s}."""
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
            "x": a["v"],
            "y": best["v"],
            "dt_s": round(best["ts"] - a["ts"], 3),
        })

    return points, {"matched": len(points), "unmatched": unmatched}


def series_xy_pairs(start_str, end_str, pair_specs, tol_s=DEFAULT_DIFF_TOL_S,
                    after_ts=None, before_ts=None):
    """Cross-node (or same-node) X vs Y using nearest-neighbor time alignment."""
    node_ids = sorted({
        spec["node_a"] for spec in pair_specs
    } | {
        spec["node_b"] for spec in pair_specs
    })
    records = load_range(start_str, end_str, node_ids, after_ts, before_ts)
    series = {}
    stats = {}

    for spec in pair_specs:
        node_a = spec["node_a"]
        field_a = spec["field_a"]
        node_b = spec["node_b"]
        field_b = spec["field_b"]
        label = f"{node_a}\u2022{field_a} vs {node_b}\u2022{field_b}"
        key = f"{node_a}:{field_a}-{node_b}:{field_b}"

        series_a = _extract_series(records, node_a, field_a)
        series_b = _extract_series(records, node_b, field_b)

        if node_a == node_b:
            by_t = {p["t"]: p["v"] for p in series_b}
            points = []
            unmatched = 0
            for a in series_a:
                if a["t"] not in by_t:
                    unmatched += 1
                    continue
                points.append({
                    "t": a["t"],
                    "x": a["v"],
                    "y": by_t[a["t"]],
                    "dt_s": 0.0,
                })
            entry_stats = {"matched": len(points), "unmatched": unmatched}
        else:
            points, entry_stats = _nearest_pair(series_a, series_b, tol_s)

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
        "mode": "xy_pair",
        "start": start_str,
        "end": end_str,
        "tol_s": tol_s,
        "series": series,
        "stats": stats,
    }


DIV_EPS_DEFAULT = 1e-12
EXPR_OPS = ("none", "sub", "div", "vs")


def _as_float(value, default):
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def normalize_expr_spec(raw):
    """Normalize one expression dict; returns None if invalid."""
    if not isinstance(raw, dict):
        return None
    node_a = str(raw.get("node_a", "")).strip()
    field_a = str(raw.get("field_a", "")).strip()
    if not node_a or not field_a:
        return None
    op = str(raw.get("op", "none")).strip().lower()
    if op not in EXPR_OPS:
        return None
    spec = {
        "a": _as_float(raw.get("a"), 1.0),
        "node_a": node_a,
        "field_a": field_a,
        "op": op,
        "b": _as_float(raw.get("b"), 1.0),
        "c": _as_float(raw.get("c"), 0.0),
        "node_b": str(raw.get("node_b", "")).strip(),
        "field_b": str(raw.get("field_b", "")).strip(),
    }
    if op != "none" and (not spec["node_b"] or not spec["field_b"]):
        return None
    return spec


def parse_expr_specs(raw):
    """Parse JSON list of expression dicts."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    specs = []
    for item in data:
        spec = normalize_expr_spec(item)
        if spec:
            specs.append(spec)
    return specs


def _expr_label(spec):
    a = spec["a"]
    c = spec["c"]
    left = f"{node_field(spec['node_a'], spec['field_a'])}"
    if a != 1.0:
        left = f"{_fmt_const(a)}·{left}"

    op = spec["op"]
    if op == "none":
        if c == 0.0:
            return left
        return f"{left} − {_fmt_const(c)}"

    right = f"{node_field(spec['node_b'], spec['field_b'])}"
    b = spec["b"]
    if b != 1.0:
        right = f"{_fmt_const(b)}·{right}"

    if op == "vs":
        label = f"{left} vs {right}"
        if c != 0.0:
            label += f" (Y−{_fmt_const(c)})"
        return label
    if op == "sub":
        label = f"{left} − {right}"
    else:
        label = f"{left} / {right}"
    if c != 0.0:
        label += f" − {_fmt_const(c)}"
    return label


def node_field(node, field):
    return f"{node}\u2022{field}"


def _fmt_const(value):
    if float(value) == int(value):
        return str(int(value))
    return str(value)


def _align_ab(series_a, series_b, tol_s, exact_same_t):
    """Pair A with B → list of {t, ts, va, vb, dt_s} plus stats."""
    if not series_a:
        return [], {"matched": 0, "unmatched": 0}
    if not series_b:
        return [], {"matched": 0, "unmatched": len(series_a)}

    points = []
    unmatched = 0

    if exact_same_t:
        by_t = {p["t"]: p for p in series_b}
        for a in series_a:
            b = by_t.get(a["t"])
            if b is None:
                unmatched += 1
                continue
            points.append({
                "t": a["t"],
                "ts": a["ts"],
                "va": a["v"],
                "vb": b["v"],
                "dt_s": 0.0,
            })
        return points, {"matched": len(points), "unmatched": unmatched}

    paired, stats = _nearest_pair(series_a, series_b, tol_s)
    # _nearest_pair returns x=va, y=vb
    out = []
    for p in paired:
        out.append({
            "t": p["t"],
            "ts": _parse_ts(p["t"]),
            "va": p["x"],
            "vb": p["y"],
            "dt_s": p["dt_s"],
        })
    return out, stats


def series_expr(start_str, end_str, specs, tol_s=DEFAULT_DIFF_TOL_S,
                after_ts=None, before_ts=None, div_eps=DIV_EPS_DEFAULT):
    """
    Evaluate expression rows:
      none: a*A - c
      sub:  a*A - b*B - c
      div:  a*A / (b*B) - c   (skip |b*B| < div_eps)
      vs:   scatter (a*A, b*B - c)
    Cannot mix vs with line ops in one request.
    """
    if not specs:
        return {
            "mode": "expr",
            "kind": "time",
            "start": start_str,
            "end": end_str,
            "tol_s": tol_s,
            "series": {},
            "stats": {},
        }

    ops = {spec["op"] for spec in specs}
    if "vs" in ops and ops - {"vs"}:
        raise ValueError("Cannot mix vs with − / none in one plot")

    kind = "xy" if "vs" in ops else "time"
    node_ids = set()
    for spec in specs:
        node_ids.add(spec["node_a"])
        if spec["op"] != "none":
            node_ids.add(spec["node_b"])
    records = load_range(start_str, end_str, sorted(node_ids), after_ts, before_ts)

    series = {}
    stats = {}

    for idx, spec in enumerate(specs):
        label = _expr_label(spec)
        key = f"expr{idx}:{label}"
        series_a = _extract_series(records, spec["node_a"], spec["field_a"])
        a_scale = spec["a"]
        c_off = spec["c"]
        op = spec["op"]

        if op == "none":
            points = [
                {"t": p["t"], "v": a_scale * p["v"] - c_off}
                for p in series_a
            ]
            entry_stats = {"matched": len(points), "unmatched": 0, "skipped": 0}
        else:
            series_b = _extract_series(records, spec["node_b"], spec["field_b"])
            exact = (
                spec["node_a"] == spec["node_b"]
            )
            aligned, entry_stats = _align_ab(series_a, series_b, tol_s, exact)
            entry_stats = dict(entry_stats)
            entry_stats["skipped"] = 0
            b_scale = spec["b"]
            points = []
            for p in aligned:
                va = a_scale * p["va"]
                vb = b_scale * p["vb"]
                if op == "vs":
                    points.append({
                        "t": p["t"],
                        "x": va,
                        "y": vb - c_off,
                        "dt_s": p["dt_s"],
                    })
                elif op == "sub":
                    points.append({
                        "t": p["t"],
                        "v": va - vb - c_off,
                        "dt_s": p["dt_s"],
                    })
                else:  # div
                    if abs(vb) < div_eps:
                        entry_stats["skipped"] += 1
                        continue
                    points.append({
                        "t": p["t"],
                        "v": va / vb - c_off,
                        "dt_s": p["dt_s"],
                    })

        points = _downsample_points(points)
        series[key] = {
            "label": label,
            "op": op,
            "spec": spec,
            "points": points,
        }
        stats[key] = entry_stats

    return {
        "mode": "expr",
        "kind": kind,
        "start": start_str,
        "end": end_str,
        "tol_s": tol_s,
        "series": series,
        "stats": stats,
    }
