from flask import Flask, request, jsonify, send_from_directory, abort
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import csv
import json
import os

import history

DISPLAY_TZ = ZoneInfo("America/Chicago")

app = Flask(__name__)

DATA_DIR = "data"
FIRMWARE_DIR = "firmware/releases"
FIRMWARE_LATEST_FILE = "firmware/LATEST"
latest = {}

os.makedirs(DATA_DIR, exist_ok=True)


def read_latest_release_name():
    try:
        with open(FIRMWARE_LATEST_FILE, "r") as f:
            name = f.read().strip()
            if name:
                return name
    except OSError:
        pass
    return None


def read_manifest(release_name=None):
    release_name = release_name or read_latest_release_name()
    if not release_name:
        return None
    manifest_path = os.path.join(FIRMWARE_DIR, release_name, "manifest.json")
    try:
        with open(manifest_path, "r") as f:
            return json.load(f)
    except OSError:
        return None


def release_directory(release_name=None):
    release_name = release_name or read_latest_release_name()
    if not release_name:
        return None
    path = os.path.join(FIRMWARE_DIR, release_name)
    if not os.path.isdir(path):
        return None
    return path


def safe_release_file_path(release_dir, filepath):
    normalized = os.path.normpath(filepath)
    if normalized.startswith("..") or os.path.isabs(normalized):
        return None
    release_abs = os.path.abspath(release_dir)
    full_path = os.path.abspath(os.path.join(release_abs, normalized))
    if os.path.commonpath([release_abs, full_path]) != release_abs:
        return None
    if not os.path.isfile(full_path):
        return None
    return full_path


def now_utc():
    return datetime.now(timezone.utc)


def iso_now():
    return now_utc().isoformat()


def today_csv_filename():
    date_str = now_utc().date().isoformat()
    return os.path.join(DATA_DIR, f"{date_str}.csv")


def append_csv(record):
    filename = today_csv_filename()
    file_exists = os.path.exists(filename)

    with open(filename, "a", newline="") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow([
                "server_timestamp",
                "node_id",
                "firmware_version",
                "readings_json",
                "integrity_json",
                "attached_sensors_json",
            ])

        writer.writerow([
            record["server_timestamp"],
            record["node_id"],
            record.get("firmware_version", ""),
            json.dumps(record.get("readings", {})),
            json.dumps(record.get("integrity", {})),
            json.dumps(record.get("attached_sensors", [])),
        ])


def sensor_summary(attached_sensors):
    if not attached_sensors:
        return ""
    labels = []
    for entry in attached_sensors:
        label = entry.get("label") or entry.get("driver") or "?"
        if entry.get("driver") == "unknown":
            labels.append("unknown@" + entry.get("address", "?"))
        else:
            labels.append(label)
    return ", ".join(labels)


def primary_metric(readings, key):
    value = readings.get(key)
    if value is None or value == "":
        return ""
    return value


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "server": "plant-pi",
        "version": "step2-test"
    })


@app.route("/api/submit", methods=["POST"])
def submit():
    data = request.get_json(silent=True)

    if data is None:
        return jsonify({"status": "error", "message": "Invalid or missing JSON"}), 400

    if "node_id" not in data:
        return jsonify({"status": "error", "message": "Missing node_id"}), 400

    if "readings" not in data:
        return jsonify({"status": "error", "message": "Missing readings"}), 400

    node_id = data["node_id"]

    record = {
        "server_timestamp": iso_now(),
        "node_id": node_id,
        "firmware_version": data.get("firmware_version", ""),
        "timestamp_node": data.get("timestamp_node", ""),
        "readings": data.get("readings", {}),
        "integrity": data.get("integrity", {}),
        "attached_sensors": data.get("attached_sensors", []),
        "ble_scan": data.get("ble_scan", {}),
    }

    latest[node_id] = record
    append_csv(record)

    response = {"status": "received"}
    manifest = read_manifest()
    firmware_version = data.get("firmware_version", "")
    if manifest and firmware_version and firmware_version != manifest.get("version"):
        response["update_available"] = True
        response["manifest_url"] = request.host_url.rstrip("/") + "/api/firmware/manifest"
        response["target_version"] = manifest.get("version")

    return jsonify(response)


@app.route("/api/firmware/manifest", methods=["GET"])
def firmware_manifest():
    manifest = read_manifest()
    if manifest is None:
        return jsonify({"status": "error", "message": "No firmware release configured"}), 404
    return jsonify(manifest)


@app.route("/api/firmware/file/<path:filepath>", methods=["GET"])
def firmware_file(filepath):
    release_dir = release_directory()
    if release_dir is None:
        abort(404)
    full_path = safe_release_file_path(release_dir, filepath)
    if full_path is None:
        abort(404)
    directory = os.path.dirname(full_path)
    filename = os.path.basename(full_path)
    return send_from_directory(directory, filename, as_attachment=False)


@app.route("/api/latest", methods=["GET"])
def api_latest():
    output = {}

    now = now_utc()

    for node_id, record in latest.items():
        t = datetime.fromisoformat(record["server_timestamp"])
        age_s = (now - t).total_seconds()

        output[node_id] = {
            "node_id": node_id,
            "server_timestamp": record["server_timestamp"],
            "timestamp_node": record.get("timestamp_node", ""),
            "firmware_version": record.get("firmware_version", ""),
            "readings": record.get("readings", {}),
            "integrity": record.get("integrity", {}),
            "attached_sensors": record.get("attached_sensors", []),
            "ble_scan": record.get("ble_scan", {}),
            "data_age_s": age_s
        }

    return jsonify(output)


@app.route("/api/latest/<path:node_id>", methods=["DELETE"])
def forget_latest_node(node_id):
    """Drop a node from the live /check table only. CSV history is untouched."""
    if node_id in latest:
        del latest[node_id]
        return jsonify({"status": "forgotten", "node_id": node_id})
    return jsonify({"status": "not_found", "node_id": node_id}), 404


@app.route("/data", methods=["GET"])
def list_data_files():
    files = sorted(os.listdir(DATA_DIR))
    links = [f'<a href="/data/{f}">{f}</a>' for f in files]
    return "<br>".join(links)


@app.route("/data/<filename>", methods=["GET"])
def get_data_file(filename):
    return send_from_directory(DATA_DIR, filename, as_attachment=False)

@app.route("/check", methods=["GET"])
def check():
    now = now_utc()

    rows = ""

    for node_id, record in sorted(latest.items()):
        t = datetime.fromisoformat(record["server_timestamp"])
        age_s = int((now - t).total_seconds())

        readings = record.get("readings", {})
        integrity = record.get("integrity", {})
        attached_sensors = record.get("attached_sensors", [])

        temp = primary_metric(readings, "tmp119_temperature_F")
        if temp == "":
            temp = primary_metric(readings, "temperature_F")
        humidity = primary_metric(readings, "humidity_percent")
        co2 = primary_metric(readings, "co2_ppm")
        if co2 == "":
            co2 = primary_metric(readings, "sgp30_eco2_ppm")
        aqi = primary_metric(readings, "aqi")
        aqi_s = primary_metric(readings, "aqi_s")
        ble_seen = primary_metric(readings, "ble_devices_seen")
        ble_close = primary_metric(readings, "ble_devices_close")
        state = integrity.get("state", "")
        sensors = sensor_summary(attached_sensors)

        last_seen = t.astimezone(DISPLAY_TZ).strftime("%H:%M:%S %Z")

        rows += f"""
        <tr>
            <td>{node_id}</td>
            <td>{last_seen}</td>
            <td>{age_s} s</td>
            <td>{sensors}</td>
            <td>{temp}</td>
            <td>{humidity}</td>
            <td>{co2}</td>
            <td>{aqi}</td>
            <td>{aqi_s}</td>
            <td>{ble_seen}</td>
            <td>{ble_close}</td>
            <td>{state}</td>
        </tr>
        """

    html = f"""
    <!doctype html>
    <html>
    <head>
        <title>Plant Sensor Check</title>
        <style>
            body {{
                font-family: sans-serif;
                margin: 2em;
            }}
            table {{
                border-collapse: collapse;
            }}
            th, td {{
                border: 1px solid #ccc;
                padding: 0.5em 1em;
            }}
            th {{
                background: #eee;
            }}
        </style>
    </head>
    <body>
        <h1>Plant Sensor Check</h1>
        <p>Known nodes: {len(latest)} | <a href="/plot">Plot history</a></p>
        <p style="color:#555;font-size:0.9em">
            AQI = UBA 1–5 (ENS160/161). AQI-S = ScioSense relative 0–500 (ENS161 only; 100 ≈ recent average).
            Temp prefers TMP119 (tmp119_temperature_F); else AHT20 temperature_F.
            eCO2 prefers ENS; SGP30 uses sgp30_eco2_ppm when ENS is absent.
        </p>

        <table>
            <tr>
                <th>Node</th>
                <th>Last Seen (Central)</th>
                <th>Age</th>
                <th>Sensors</th>
                <th>Temp F</th>
                <th>Humidity %</th>
                <th>eCO2 ppm</th>
                <th>AQI</th>
                <th>AQI-S</th>
                <th>BLE seen</th>
                <th>BLE close</th>
                <th>Integrity</th>
            </tr>
            {rows}
        </table>
    </body>
    </html>
    """

    return html


def _parse_node_list(raw):
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _request_time_range():
    """Resolve start/end from query args. Supports date= (single day) or start/end."""
    resolved = history.resolve_range(
        start=request.args.get("start", ""),
        end=request.args.get("end", ""),
        date=request.args.get("date", ""),
    )
    if resolved is None:
        return None, (jsonify({"status": "error", "message": "Missing date or start/end"}), 400)
    start_str, end_str = resolved
    if not history.dates_in_range(start_str, end_str):
        return None, (jsonify({"status": "error", "message": "No data for range"}), 404)
    after_ts = history.parse_time_bound(request.args.get("after", ""))
    before_ts = history.parse_time_bound(request.args.get("before", ""))
    return (start_str, end_str, after_ts, before_ts), None


@app.route("/api/plot/dates", methods=["GET"])
def plot_dates():
    return jsonify({"dates": history.list_dates()})


@app.route("/api/plot/meta", methods=["GET"])
def plot_meta():
    resolved, err = _request_time_range()
    if err:
        return err
    start_str, end_str, _, _ = resolved
    meta = history.range_meta(start_str, end_str)
    if meta is None:
        return jsonify({"status": "error", "message": "No data for range"}), 404
    return jsonify(meta)


@app.route("/api/series", methods=["GET"])
def plot_series():
    resolved, err = _request_time_range()
    if err:
        return err
    start_str, end_str, after_ts, before_ts = resolved
    mode = request.args.get("mode", "time")

    if mode == "expr":
        specs = history.parse_expr_specs(request.args.get("exprs", ""))
        if not specs:
            return jsonify({"status": "error", "message": "Missing or invalid exprs"}), 400
        try:
            tol_s = float(request.args.get("tol_s", history.DEFAULT_DIFF_TOL_S))
        except ValueError:
            return jsonify({"status": "error", "message": "Invalid tol_s"}), 400
        if tol_s <= 0:
            return jsonify({"status": "error", "message": "tol_s must be positive"}), 400
        try:
            return jsonify(history.series_expr(
                start_str, end_str, specs, tol_s=tol_s,
                after_ts=after_ts, before_ts=before_ts,
            ))
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400

    if mode == "diff":
        specs = history.parse_diff_specs(request.args.get("diffs", ""))
        if not specs:
            return jsonify({"status": "error", "message": "Missing or invalid diffs"}), 400
        try:
            tol_s = float(request.args.get("tol_s", history.DEFAULT_DIFF_TOL_S))
        except ValueError:
            return jsonify({"status": "error", "message": "Invalid tol_s"}), 400
        if tol_s <= 0:
            return jsonify({"status": "error", "message": "tol_s must be positive"}), 400
        return jsonify(history.series_diff(
            start_str, end_str, specs, tol_s=tol_s,
            after_ts=after_ts, before_ts=before_ts,
        ))

    if mode == "xy_pair":
        specs = history.parse_diff_specs(request.args.get("pairs", ""))
        if not specs:
            return jsonify({"status": "error", "message": "Missing or invalid pairs"}), 400
        try:
            tol_s = float(request.args.get("tol_s", history.DEFAULT_DIFF_TOL_S))
        except ValueError:
            return jsonify({"status": "error", "message": "Invalid tol_s"}), 400
        if tol_s <= 0:
            return jsonify({"status": "error", "message": "tol_s must be positive"}), 400
        return jsonify(history.series_xy_pairs(
            start_str, end_str, specs, tol_s=tol_s,
            after_ts=after_ts, before_ts=before_ts,
        ))

    if mode == "time":
        specs = history.parse_series_specs(request.args.get("series", ""))
        if specs:
            return jsonify(history.series_time_specs(
                start_str, end_str, specs,
                after_ts=after_ts, before_ts=before_ts,
            ))
        node_ids = _parse_node_list(request.args.get("nodes", ""))
        fields = _parse_node_list(request.args.get("fields", ""))
        if not fields:
            single = request.args.get("field", "")
            if single:
                fields = [single]
        if not node_ids:
            return jsonify({"status": "error", "message": "Missing series or nodes"}), 400
        if not fields:
            return jsonify({"status": "error", "message": "Missing field"}), 400
        return jsonify(history.series_time(
            start_str, end_str, node_ids, fields,
            after_ts=after_ts, before_ts=before_ts,
        ))

    if mode == "xy":
        node_ids = _parse_node_list(request.args.get("nodes", ""))
        if not node_ids:
            return jsonify({"status": "error", "message": "Missing nodes"}), 400
        x_field = request.args.get("x", "")
        y_field = request.args.get("y", "")
        if not x_field or not y_field:
            return jsonify({"status": "error", "message": "Missing x or y field"}), 400
        return jsonify(history.series_xy(
            start_str, end_str, node_ids, x_field, y_field,
            after_ts=after_ts, before_ts=before_ts,
        ))

    return jsonify({"status": "error", "message": "Unknown mode"}), 400


@app.route("/plot", methods=["GET"])
def plot_page():
    return """<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>Plant Sensor Plot</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        body { font-family: sans-serif; margin: 2em; max-width: 1200px; }
        fieldset { margin-bottom: 1em; border: 1px solid #ccc; padding: 1em; }
        label { margin-right: 0.35em; }
        .expr-row { display: flex; flex-wrap: wrap; gap: 0.4em; align-items: center; margin-bottom: 0.55em; }
        .expr-row input[type="number"] { width: 4.5em; }
        select, button, input[type="number"] { font-size: 1em; padding: 0.25em 0.4em; }
        #status { color: #555; margin: 1em 0; }
        #chart-wrap { max-width: 1000px; }
        a { color: #06c; }
        .hint { color: #666; font-size: 0.9em; }
        #readout-panel { display: none; }
        #readout-table { border-collapse: collapse; margin-top: 0.5em; }
        #readout-table th, #readout-table td { border: 1px solid #ccc; padding: 0.35em 0.75em; text-align: left; }
        #readout-table th { background: #eee; }
        .preset-row { margin-top: 0.6em; display: flex; flex-wrap: wrap; gap: 0.5em; align-items: center; }
    </style>
</head>
<body>
    <h1>Plant Sensor Plot</h1>
    <p><a href="/check">Back to check</a></p>

    <fieldset>
        <legend>Time range</legend>
        <label>Preset
            <select id="range-preset">
                <option value="today" selected>Today</option>
                <option value="yesterday">Yesterday</option>
                <option value="last24h">Last 24 hours</option>
                <option value="last3d">Last 3 days</option>
                <option value="last7d">Last 7 days</option>
                <option value="last14d">Last 14 days</option>
                <option value="all">All available</option>
                <option value="custom">Custom dates</option>
            </select>
        </label>
        <label>From <select id="start-select"></select></label>
        <label>To <select id="end-select"></select></label>
        <span id="meta-info"></span>
        <p class="hint" id="range-hint"></p>
    </fieldset>

    <fieldset>
        <legend>Expressions</legend>
        <p class="hint">
            Plot <code>a·A − c</code>, <code>a·A − b·B − c</code>, <code>a·A / b·B − c</code>, or <code>A vs B</code>.
            Do not mix <code>vs</code> with the other ops in one plot. Division skips near-zero denominators.
            Constants are display-only (not saved).
        </p>
        <div id="expr-rows"></div>
        <div class="preset-row">
            <button id="add-expr-btn" type="button">Add expression</button>
            <button id="preset-temp-btn" type="button">All nodes × temperature_F</button>
            <button id="preset-diff-btn" type="button">Diff shared (first two nodes)</button>
            <button id="preset-ratio-btn" type="button">Ratio shared (first two)</button>
            <button id="preset-xy-btn" type="button">XY shared (first two)</button>
            <label>Tolerance (s)
                <input id="tol-input" type="number" min="1" step="1" value="60" style="width:4em">
            </label>
            <button id="plot-btn" type="button">Plot</button>
        </div>
    </fieldset>

    <fieldset id="readout-panel">
        <legend>Values at cursor</legend>
        <p class="hint" id="readout-time">Click the chart to read nearest samples at that time.</p>
        <table id="readout-table">
            <thead><tr><th>Expression</th><th>Value</th><th>Sample time (Central)</th><th>|Δt| s</th></tr></thead>
            <tbody id="readout-body"></tbody>
        </table>
    </fieldset>

    <p id="status">Loading dates...</p>
    <div id="chart-wrap"><canvas id="chart"></canvas></div>

    <script>
    const TZ = "America/Chicago";
    const startSelect = document.getElementById("start-select");
    const endSelect = document.getElementById("end-select");
    const rangePreset = document.getElementById("range-preset");
    const rangeHint = document.getElementById("range-hint");
    const metaInfo = document.getElementById("meta-info");
    const statusEl = document.getElementById("status");
    const exprRows = document.getElementById("expr-rows");
    const readoutPanel = document.getElementById("readout-panel");
    const readoutBody = document.getElementById("readout-body");
    const readoutTime = document.getElementById("readout-time");

    let chart = null;
    let metaCache = { nodes: [], fields: [], fields_by_node: {} };
    let rowsInitialized = false;
    let lastPlot = null;
    let cursorMs = null;

    const COLORS = [
        "#2563eb", "#dc2626", "#16a34a", "#ca8a04",
        "#9333ea", "#0891b2", "#ea580c", "#4b5563",
    ];

    function setStatus(msg) { statusEl.textContent = msg; }

    function fmtCentral(ms, opts) {
        return new Intl.DateTimeFormat("en-US", Object.assign({ timeZone: TZ }, opts)).format(new Date(ms));
    }

    function fmtCentralHint(isoOrMs) {
        const ms = typeof isoOrMs === "number" ? isoOrMs : Date.parse(isoOrMs);
        if (!Number.isFinite(ms)) return String(isoOrMs);
        return fmtCentral(ms, {
            year: "numeric", month: "2-digit", day: "2-digit",
            hour: "2-digit", minute: "2-digit", second: "2-digit",
            hour12: false,
        }) + " CT";
    }

    function fillSelect(select, items, preferred) {
        const prev = select.value;
        select.innerHTML = "";
        for (const item of items) {
            const opt = document.createElement("option");
            opt.value = item;
            opt.textContent = item;
            select.appendChild(opt);
        }
        if (preferred && items.includes(preferred)) select.value = preferred;
        else if (items.includes(prev)) select.value = prev;
    }

    function sharedFields(nodeA, nodeB) {
        const fbn = metaCache.fields_by_node || {};
        const a = new Set(fbn[nodeA] || []);
        return (fbn[nodeB] || []).filter(f => a.has(f)).sort();
    }

    function numVal(input, fallback) {
        const v = parseFloat(input.value);
        return Number.isFinite(v) ? v : fallback;
    }

    function syncBVisibility(row) {
        const op = row.querySelector(".op").value;
        const showB = op !== "none";
        row.querySelectorAll(".b-part").forEach(el => {
            el.style.display = showB ? "" : "none";
        });
    }

    function addExprRow(preset) {
        const row = document.createElement("div");
        row.className = "expr-row";
        row.innerHTML =
            '<input class="scale-a" type="number" step="any" value="1" title="a">' +
            '<span>·</span>' +
            '<select class="node-a"></select>' +
            '<select class="field-a"></select>' +
            '<select class="op">' +
            '<option value="none">(none)</option>' +
            '<option value="sub">−</option>' +
            '<option value="div">/</option>' +
            '<option value="vs">vs</option>' +
            '</select>' +
            '<span class="b-part"></span>' +
            '<input class="scale-b b-part" type="number" step="any" value="1" title="b">' +
            '<span class="b-part">·</span>' +
            '<select class="node-b b-part"></select>' +
            '<select class="field-b b-part"></select>' +
            '<span>−</span>' +
            '<input class="scale-c" type="number" step="any" value="0" title="c">' +
            '<button type="button" class="remove-row">Remove</button>';
        exprRows.appendChild(row);

        const nodeA = row.querySelector(".node-a");
        const nodeB = row.querySelector(".node-b");
        const fieldA = row.querySelector(".field-a");
        const fieldB = row.querySelector(".field-b");
        const op = row.querySelector(".op");

        fillSelect(nodeA, metaCache.nodes, (preset && preset.node_a) || metaCache.nodes[0]);
        fillSelect(nodeB, metaCache.nodes,
            (preset && preset.node_b) || metaCache.nodes[1] || metaCache.nodes[0]);

        const syncFields = () => {
            const allA = metaCache.fields_by_node[nodeA.value] || [];
            const allB = metaCache.fields_by_node[nodeB.value] || [];
            const shared = sharedFields(nodeA.value, nodeB.value);
            fillSelect(fieldA, allA, (preset && preset.field_a) ||
                (allA.includes("temperature_F") ? "temperature_F" : allA[0]));
            fillSelect(fieldB, allB, (preset && preset.field_b) || shared[0] || allB[0]);
        };
        nodeA.addEventListener("change", syncFields);
        nodeB.addEventListener("change", syncFields);
        fieldA.addEventListener("change", () => {
            const allB = metaCache.fields_by_node[nodeB.value] || [];
            if (allB.includes(fieldA.value)) fieldB.value = fieldA.value;
        });
        op.addEventListener("change", () => syncBVisibility(row));
        row.querySelector(".remove-row").addEventListener("click", () => {
            if (exprRows.children.length > 1) row.remove();
        });

        syncFields();
        if (preset) {
            if (preset.a != null) row.querySelector(".scale-a").value = preset.a;
            if (preset.b != null) row.querySelector(".scale-b").value = preset.b;
            if (preset.c != null) row.querySelector(".scale-c").value = preset.c;
            if (preset.op) op.value = preset.op;
            if (preset.field_a) fieldA.value = preset.field_a;
            if (preset.field_b) fieldB.value = preset.field_b;
        }
        syncBVisibility(row);
    }

    function syncExprRow(row) {
        const nodeA = row.querySelector(".node-a");
        const nodeB = row.querySelector(".node-b");
        const fieldA = row.querySelector(".field-a");
        const fieldB = row.querySelector(".field-b");
        const fa = fieldA.value;
        const fb = fieldB.value;
        fillSelect(nodeA, metaCache.nodes, nodeA.value);
        fillSelect(nodeB, metaCache.nodes, nodeB.value);
        fillSelect(fieldA, metaCache.fields_by_node[nodeA.value] || [], fa);
        fillSelect(fieldB, metaCache.fields_by_node[nodeB.value] || [], fb);
        syncBVisibility(row);
    }

    function collectExprs() {
        return Array.from(exprRows.querySelectorAll(".expr-row")).map(row => {
            const op = row.querySelector(".op").value;
            const spec = {
                a: numVal(row.querySelector(".scale-a"), 1),
                node_a: row.querySelector(".node-a").value,
                field_a: row.querySelector(".field-a").value,
                op: op,
                b: numVal(row.querySelector(".scale-b"), 1),
                node_b: row.querySelector(".node-b").value,
                field_b: row.querySelector(".field-b").value,
                c: numVal(row.querySelector(".scale-c"), 0),
            };
            if (op === "none") {
                spec.node_b = "";
                spec.field_b = "";
            }
            return spec;
        });
    }

    let availableDates = [];
    let afterBound = null;

    function fillDateSelect(select, preferred) {
        fillSelect(select, availableDates, preferred);
    }

    function applyPreset(name) {
        if (!availableDates.length) return;
        afterBound = null;
        const newest = availableDates[0];
        const oldest = availableDates[availableDates.length - 1];
        const custom = name === "custom";
        startSelect.disabled = !custom;
        endSelect.disabled = !custom;
        if (name === "custom") {
            rangeHint.textContent = "Pick From/To dates, then Plot.";
            return;
        }
        let start = newest;
        let end = newest;
        const now = Date.now();
        if (name === "today") {
            start = end = newest;
            rangeHint.textContent = "Single day: " + newest + " (chart times Central).";
        } else if (name === "yesterday") {
            start = end = availableDates[1] || newest;
            rangeHint.textContent = "Single day: " + start + " (chart times Central).";
        } else if (name === "last24h") {
            afterBound = new Date(now - 24 * 3600 * 1000).toISOString();
            const afterDay = afterBound.slice(0, 10);
            const daysAsc = availableDates.slice().reverse();
            if (afterDay <= oldest) start = oldest;
            else if (availableDates.includes(afterDay)) start = afterDay;
            else start = daysAsc.find(d => d >= afterDay) || newest;
            end = newest;
            rangeHint.textContent = "Rolling window: points after " + fmtCentralHint(afterBound) + ".";
        } else if (name === "last3d" || name === "last7d" || name === "last14d") {
            const n = name === "last3d" ? 3 : (name === "last7d" ? 7 : 14);
            const slice = availableDates.slice(0, n);
            end = newest;
            start = slice[slice.length - 1];
            rangeHint.textContent = n + " most recent days with data (" + start + " → " + end + ").";
        } else if (name === "all") {
            start = oldest;
            end = newest;
            rangeHint.textContent = "All days with CSV data (" + start + " → " + end + ").";
        }
        fillDateSelect(startSelect, start);
        fillDateSelect(endSelect, end);
    }

    function rangeQuery() {
        let start = startSelect.value;
        let end = endSelect.value;
        if (start > end) { const tmp = start; start = end; end = tmp; }
        let q = "start=" + encodeURIComponent(start) + "&end=" + encodeURIComponent(end);
        if (afterBound) q += "&after=" + encodeURIComponent(afterBound);
        return { start, end, q };
    }

    async function loadDates() {
        const res = await fetch("/api/plot/dates");
        const data = await res.json();
        availableDates = data.dates || [];
        if (!availableDates.length) {
            setStatus("No CSV data files found.");
            return;
        }
        fillDateSelect(startSelect, availableDates[0]);
        fillDateSelect(endSelect, availableDates[0]);
        applyPreset(rangePreset.value);
        await loadMeta();
    }

    async function loadMeta() {
        const { start, end, q } = rangeQuery();
        setStatus("Loading " + start + " → " + end + "...");
        const res = await fetch("/api/plot/meta?" + q);
        if (!res.ok) {
            setStatus("No data for " + start + " → " + end);
            return;
        }
        const prev = rowsInitialized ? collectExprs() : null;
        metaCache = await res.json();
        metaInfo.textContent = metaCache.day_count + " day(s), " + metaCache.row_count +
            " rows, " + metaCache.fields.length + " fields";

        if (prev && prev.length) {
            exprRows.innerHTML = "";
            for (const spec of prev) addExprRow(spec);
        } else if (!exprRows.children.length) {
            addExprRow({ op: "none" });
        } else {
            for (const row of exprRows.querySelectorAll(".expr-row")) syncExprRow(row);
        }
        rowsInitialized = true;
        setStatus("Ready. Edit expressions and click Plot.");
    }

    function destroyChart() {
        if (chart) { chart.destroy(); chart = null; }
    }

    function fmtTime(ms) {
        const multiDay = (metaCache.start && metaCache.end && metaCache.start !== metaCache.end)
            || (rangePreset.value !== "today" && rangePreset.value !== "yesterday");
        if (multiDay || afterBound) {
            return fmtCentral(ms, {
                month: "2-digit", day: "2-digit",
                hour: "2-digit", minute: "2-digit",
                hour12: false,
            });
        }
        return fmtCentral(ms, { hour: "2-digit", minute: "2-digit", hour12: false });
    }

    function nearestPoint(points, targetMs, valueKey) {
        let best = null;
        let bestDt = Infinity;
        for (const p of points) {
            const ms = Date.parse(p.t);
            if (!Number.isFinite(ms)) continue;
            const dt = Math.abs(ms - targetMs);
            if (dt < bestDt) {
                bestDt = dt;
                best = p;
            }
        }
        return best ? { point: best, dt: bestDt, ms: Date.parse(best.t), valueKey } : null;
    }

    function updateReadout(targetMs) {
        if (!lastPlot || lastPlot.payload.kind !== "time") {
            readoutPanel.style.display = "none";
            return;
        }
        cursorMs = targetMs;
        readoutPanel.style.display = "block";
        readoutTime.textContent = "Cursor: " + fmtCentralHint(targetMs) + " (nearest sample per expression).";
        readoutBody.innerHTML = "";
        for (const entry of Object.values(lastPlot.payload.series)) {
            const hit = nearestPoint(entry.points, targetMs, "v");
            const tr = document.createElement("tr");
            if (!hit) {
                tr.innerHTML = "<td>" + entry.label + "</td><td>—</td><td>—</td><td>—</td>";
            } else {
                tr.innerHTML = "<td>" + entry.label + "</td><td>" + hit.point.v + "</td><td>" +
                    fmtCentralHint(hit.ms) + "</td><td>" + hit.dt.toFixed(1) + "</td>";
            }
            readoutBody.appendChild(tr);
        }
    }

    function cursorPlugin() {
        return {
            id: "centralCursor",
            afterDraw(c) {
                if (cursorMs == null || !c.scales.x) return;
                const x = c.scales.x.getPixelForValue(cursorMs);
                if (x < c.chartArea.left || x > c.chartArea.right) return;
                const ctx = c.ctx;
                ctx.save();
                ctx.strokeStyle = "#666";
                ctx.lineWidth = 1;
                ctx.setLineDash([4, 4]);
                ctx.beginPath();
                ctx.moveTo(x, c.chartArea.top);
                ctx.lineTo(x, c.chartArea.bottom);
                ctx.stroke();
                ctx.restore();
            },
        };
    }

    function buildTimeChart(payload) {
        const datasets = [];
        let i = 0;
        for (const entry of Object.values(payload.series)) {
            datasets.push({
                label: entry.label,
                data: entry.points.map(p => ({ x: Date.parse(p.t), y: p.v })),
                borderColor: COLORS[i % COLORS.length],
                backgroundColor: COLORS[i % COLORS.length],
                tension: 0.1,
                pointRadius: 0,
                showLine: true,
            });
            i += 1;
        }
        readoutPanel.style.display = "block";
        destroyChart();
        chart = new Chart(document.getElementById("chart"), {
            type: "line",
            data: { datasets },
            options: {
                parsing: false,
                scales: {
                    x: {
                        type: "linear",
                        title: { display: true, text: "Time (Central)" },
                        ticks: { maxTicksLimit: 12, callback: v => fmtTime(v) },
                    },
                    y: { title: { display: true, text: "Value" } },
                },
                plugins: {
                    legend: { display: true },
                    tooltip: {
                        callbacks: {
                            title: items => items.length
                                ? fmtCentral(items[0].parsed.x, {
                                    hour: "2-digit", minute: "2-digit", second: "2-digit",
                                    hour12: false,
                                }) + " CT"
                                : "",
                        },
                    },
                },
                onClick: (evt, _els, c) => {
                    const xScale = c.scales.x;
                    if (!xScale) return;
                    const x = xScale.getValueForPixel(evt.x);
                    if (Number.isFinite(x)) {
                        updateReadout(x);
                        c.draw();
                    }
                },
            },
            plugins: [cursorPlugin()],
        });
        if (cursorMs != null) updateReadout(cursorMs);
    }

    function buildXYChart(payload) {
        const datasets = [];
        let i = 0;
        for (const entry of Object.values(payload.series)) {
            datasets.push({
                label: entry.label,
                data: entry.points.map(p => ({ x: p.x, y: p.y })),
                borderColor: COLORS[i % COLORS.length],
                backgroundColor: COLORS[i % COLORS.length],
                pointRadius: 3,
                showLine: false,
            });
            i += 1;
        }
        readoutPanel.style.display = "none";
        destroyChart();
        chart = new Chart(document.getElementById("chart"), {
            type: "scatter",
            data: { datasets },
            options: {
                scales: {
                    x: { title: { display: true, text: "X (= a·A)" } },
                    y: { title: { display: true, text: "Y (= b·B − c)" } },
                },
                plugins: { legend: { display: true } },
            },
        });
    }

    async function runPlot() {
        const exprs = collectExprs();
        if (!exprs.length) {
            setStatus("Add at least one expression.");
            return;
        }
        const ops = new Set(exprs.map(e => e.op));
        if (ops.has("vs") && [...ops].some(o => o !== "vs")) {
            setStatus("Cannot mix vs with − / / (none) in one plot.");
            return;
        }
        const { start, end, q } = rangeQuery();
        const tol = document.getElementById("tol-input").value || "60";
        const url = "/api/series?" + q + "&mode=expr&tol_s=" + encodeURIComponent(tol) +
            "&exprs=" + encodeURIComponent(JSON.stringify(exprs));

        setStatus("Plotting...");
        const res = await fetch(url);
        const payload = await res.json();
        if (!res.ok) {
            setStatus(payload.message || "Plot failed");
            return;
        }
        let total = 0;
        for (const entry of Object.values(payload.series || {})) total += entry.points.length;
        if (total === 0) {
            setStatus("No numeric data for selection.");
            destroyChart();
            return;
        }
        lastPlot = { payload };
        cursorMs = null;
        const rangeLabel = start === end ? start : (start + " → " + end);
        const parts = [];
        for (const st of Object.values(payload.stats || {})) {
            let s = st.matched + " matched";
            if (st.unmatched) s += " / " + st.unmatched + " unmatched";
            if (st.skipped) s += " / " + st.skipped + " ÷0 skipped";
            parts.push(s);
        }
        if (payload.kind === "xy") {
            buildXYChart(payload);
            setStatus("Plotted " + total + " XY points for " + rangeLabel +
                " (tol " + payload.tol_s + " s). " + parts.join("; "));
        } else {
            buildTimeChart(payload);
            setStatus("Plotted " + total + " points for " + rangeLabel +
                (parts.length ? " (" + parts.join("; ") + ")" : "") +
                ". Click chart for readout.");
        }
    }

    function firstTwoShared() {
        if (metaCache.nodes.length < 2) {
            setStatus("Need at least two nodes.");
            return null;
        }
        const a = metaCache.nodes[0];
        const b = metaCache.nodes[1];
        const shared = sharedFields(a, b);
        if (!shared.length) {
            setStatus("No shared fields between " + a + " and " + b + ".");
            return null;
        }
        return { a, b, shared };
    }

    document.getElementById("add-expr-btn").addEventListener("click", () => addExprRow({ op: "none" }));
    document.getElementById("preset-temp-btn").addEventListener("click", () => {
        exprRows.innerHTML = "";
        for (const node of metaCache.nodes) {
            const fields = metaCache.fields_by_node[node] || [];
            if (fields.includes("temperature_F")) {
                addExprRow({ op: "none", node_a: node, field_a: "temperature_F", a: 1, c: 0 });
            }
        }
        if (!exprRows.children.length) addExprRow({ op: "none" });
    });
    document.getElementById("preset-diff-btn").addEventListener("click", () => {
        const info = firstTwoShared();
        if (!info) return;
        exprRows.innerHTML = "";
        for (const field of info.shared) {
            addExprRow({
                op: "sub", a: 1, b: 1, c: 0,
                node_a: info.a, field_a: field,
                node_b: info.b, field_b: field,
            });
        }
    });
    document.getElementById("preset-ratio-btn").addEventListener("click", () => {
        const info = firstTwoShared();
        if (!info) return;
        exprRows.innerHTML = "";
        for (const field of info.shared) {
            addExprRow({
                op: "div", a: 1, b: 1, c: 0,
                node_a: info.a, field_a: field,
                node_b: info.b, field_b: field,
            });
        }
    });
    document.getElementById("preset-xy-btn").addEventListener("click", () => {
        const info = firstTwoShared();
        if (!info) return;
        exprRows.innerHTML = "";
        for (const field of info.shared) {
            addExprRow({
                op: "vs", a: 1, b: 1, c: 0,
                node_a: info.a, field_a: field,
                node_b: info.b, field_b: field,
            });
        }
    });
    rangePreset.addEventListener("change", async () => {
        applyPreset(rangePreset.value);
        await loadMeta();
    });
    startSelect.addEventListener("change", async () => {
        if (rangePreset.value !== "custom") rangePreset.value = "custom";
        startSelect.disabled = false;
        endSelect.disabled = false;
        afterBound = null;
        await loadMeta();
    });
    endSelect.addEventListener("change", async () => {
        if (rangePreset.value !== "custom") rangePreset.value = "custom";
        startSelect.disabled = false;
        endSelect.disabled = false;
        afterBound = null;
        await loadMeta();
    });
    document.getElementById("plot-btn").addEventListener("click", runPlot);

    loadDates();
    </script>
</body>
</html>"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
