from flask import Flask, request, jsonify, send_from_directory, abort
from datetime import datetime, timezone
import csv
import json
import os

import history

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

        temp = primary_metric(readings, "temperature_F")
        humidity = primary_metric(readings, "humidity_percent")
        co2 = primary_metric(readings, "co2_ppm")
        ble_seen = primary_metric(readings, "ble_devices_seen")
        ble_close = primary_metric(readings, "ble_devices_close")
        state = integrity.get("state", "")
        sensors = sensor_summary(attached_sensors)

        last_seen = t.astimezone().strftime("%H:%M:%S")

        rows += f"""
        <tr>
            <td>{node_id}</td>
            <td>{last_seen}</td>
            <td>{age_s} s</td>
            <td>{sensors}</td>
            <td>{temp}</td>
            <td>{humidity}</td>
            <td>{co2}</td>
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

        <table>
            <tr>
                <th>Node</th>
                <th>Last Seen</th>
                <th>Age</th>
                <th>Sensors</th>
                <th>Temp F</th>
                <th>Humidity %</th>
                <th>eCO2 ppm</th>
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
    node_ids = _parse_node_list(request.args.get("nodes", ""))

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

    if not node_ids:
        return jsonify({"status": "error", "message": "Missing nodes"}), 400

    if mode == "time":
        fields = _parse_node_list(request.args.get("fields", ""))
        if not fields:
            single = request.args.get("field", "")
            if single:
                fields = [single]
        if not fields:
            return jsonify({"status": "error", "message": "Missing field"}), 400
        return jsonify(history.series_time(
            start_str, end_str, node_ids, fields,
            after_ts=after_ts, before_ts=before_ts,
        ))

    if mode == "xy":
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
        body { font-family: sans-serif; margin: 2em; max-width: 1100px; }
        fieldset { margin-bottom: 1em; border: 1px solid #ccc; padding: 1em; }
        label { margin-right: 1em; }
        .nodes label { display: inline-block; margin-right: 1.5em; margin-bottom: 0.5em; }
        .diff-row { display: flex; flex-wrap: wrap; gap: 0.5em; align-items: center; margin-bottom: 0.5em; }
        select, button { font-size: 1em; padding: 0.25em 0.5em; }
        #status { color: #555; margin: 1em 0; }
        #chart-wrap { max-width: 1000px; }
        a { color: #06c; }
        .hint { color: #666; font-size: 0.9em; }
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
        <label>From
            <select id="start-select"></select>
        </label>
        <label>To
            <select id="end-select"></select>
        </label>
        <span id="meta-info"></span>
        <p class="hint" id="range-hint"></p>
    </fieldset>

    <fieldset id="nodes-fieldset">
        <legend>Nodes</legend>
        <div id="node-list" class="nodes"></div>
        <p class="hint" id="nodes-hint"></p>
    </fieldset>

    <fieldset>
        <legend>Plot</legend>
        <label><input type="radio" name="mode" value="time" checked> vs time</label>
        <label><input type="radio" name="mode" value="xy"> X vs Y</label>
        <label><input type="radio" name="mode" value="diff"> difference vs time</label>

        <div id="time-fields" style="margin-top:0.75em">
            <div style="margin-bottom:0.35em">Fields for selected nodes:</div>
            <div id="field-list" class="nodes"></div>
        </div>

        <div id="xy-fields" style="margin-top:0.75em; display:none">
            <label>X <select id="x-select"></select></label>
            <label>Y <select id="y-select"></select></label>
        </div>

        <div id="diff-fields" style="margin-top:0.75em; display:none">
            <p class="hint">A − B, nearest sample within tolerance (default 60 s).</p>
            <div id="diff-rows"></div>
            <div style="margin-top:0.5em">
                <button id="add-diff-btn" type="button">Add difference</button>
                <button id="quick-diff-btn" type="button">All shared fields (first two nodes)</button>
                <label style="margin-left:1em">Tolerance (s)
                    <input id="tol-input" type="number" min="1" step="1" value="60" style="width:4em">
                </label>
            </div>
        </div>

        <div style="margin-top:0.75em">
            <button id="plot-btn" type="button">Plot</button>
        </div>
    </fieldset>

    <p id="status">Loading dates...</p>
    <div id="chart-wrap"><canvas id="chart"></canvas></div>

    <script>
    const startSelect = document.getElementById("start-select");
    const endSelect = document.getElementById("end-select");
    const rangePreset = document.getElementById("range-preset");
    const rangeHint = document.getElementById("range-hint");
    const nodeList = document.getElementById("node-list");
    const fieldList = document.getElementById("field-list");
    const xSelect = document.getElementById("x-select");
    const ySelect = document.getElementById("y-select");
    const metaInfo = document.getElementById("meta-info");
    const statusEl = document.getElementById("status");
    const timeFields = document.getElementById("time-fields");
    const xyFields = document.getElementById("xy-fields");
    const diffFields = document.getElementById("diff-fields");
    const diffRows = document.getElementById("diff-rows");
    const nodesHint = document.getElementById("nodes-hint");
    let chart = null;
    let metaCache = { nodes: [], fields: [], fields_by_node: {} };

    const COLORS = [
        "#2563eb", "#dc2626", "#16a34a", "#ca8a04",
        "#9333ea", "#0891b2", "#ea580c", "#4b5563",
    ];

    function setStatus(msg) { statusEl.textContent = msg; }

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

    function selectedNodes() {
        return Array.from(nodeList.querySelectorAll("input:checked")).map(cb => cb.value);
    }

    function selectedFields() {
        return Array.from(fieldList.querySelectorAll("input:checked")).map(cb => cb.value);
    }

    function plotMode() {
        return document.querySelector('input[name="mode"]:checked').value;
    }

    function fieldsForNodes(nodes) {
        const fbn = metaCache.fields_by_node || {};
        if (!nodes.length) return [];
        const sets = nodes.map(n => new Set(fbn[n] || []));
        const union = new Set();
        for (const s of sets) for (const f of s) union.add(f);
        return Array.from(union).sort();
    }

    function sharedFields(nodeA, nodeB) {
        const fbn = metaCache.fields_by_node || {};
        const a = new Set(fbn[nodeA] || []);
        return (fbn[nodeB] || []).filter(f => a.has(f)).sort();
    }

    function updateModePanels() {
        const mode = plotMode();
        timeFields.style.display = mode === "time" ? "block" : "none";
        xyFields.style.display = mode === "xy" ? "block" : "none";
        diffFields.style.display = mode === "diff" ? "block" : "none";
        document.getElementById("nodes-fieldset").style.display =
            mode === "diff" ? "none" : "block";
        if (mode === "diff" && diffRows.children.length === 0) addDiffRow();
        refreshFieldControls();
    }

    function refreshFieldControls() {
        const nodes = selectedNodes();
        const available = fieldsForNodes(nodes.length ? nodes : metaCache.nodes);
        const prevChecked = new Set(selectedFields());

        fieldList.innerHTML = "";
        for (const field of available) {
            const label = document.createElement("label");
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.value = field;
            cb.checked = prevChecked.has(field) ||
                (prevChecked.size === 0 && field === "temperature_F");
            label.appendChild(cb);
            label.appendChild(document.createTextNode(" " + field));
            fieldList.appendChild(label);
        }

        fillSelect(xSelect, available, "ble_devices_close");
        fillSelect(ySelect, available, "co2_ppm");

        const missing = [];
        if (nodes.length) {
            for (const field of selectedFields()) {
                const lacking = nodes.filter(n => !(metaCache.fields_by_node[n] || []).includes(field));
                if (lacking.length) missing.push(field + " missing on " + lacking.join(", "));
            }
        }
        nodesHint.textContent = missing.length
            ? "Note: " + missing.join("; ") + " (those series stay empty)."
            : "";

        for (const row of diffRows.querySelectorAll(".diff-row")) syncDiffRow(row);
    }

    function addDiffRow(preset) {
        const row = document.createElement("div");
        row.className = "diff-row";
        row.innerHTML =
            '<select class="node-a"></select>' +
            '<select class="field-a"></select>' +
            '<span>−</span>' +
            '<select class="node-b"></select>' +
            '<select class="field-b"></select>' +
            '<button type="button" class="remove-diff">Remove</button>';
        diffRows.appendChild(row);

        const nodeA = row.querySelector(".node-a");
        const nodeB = row.querySelector(".node-b");
        const fieldA = row.querySelector(".field-a");
        const fieldB = row.querySelector(".field-b");

        fillSelect(nodeA, metaCache.nodes, (preset && preset.node_a) || metaCache.nodes[0]);
        fillSelect(nodeB, metaCache.nodes,
            (preset && preset.node_b) || metaCache.nodes[1] || metaCache.nodes[0]);

        const onNodeChange = () => {
            const shared = sharedFields(nodeA.value, nodeB.value);
            const allA = metaCache.fields_by_node[nodeA.value] || [];
            const allB = metaCache.fields_by_node[nodeB.value] || [];
            fillSelect(fieldA, allA, (preset && preset.field_a) || shared[0] || allA[0]);
            fillSelect(fieldB, allB, (preset && preset.field_b) || fieldA.value || allB[0]);
        };
        nodeA.addEventListener("change", onNodeChange);
        nodeB.addEventListener("change", onNodeChange);
        fieldA.addEventListener("change", () => {
            const allB = metaCache.fields_by_node[nodeB.value] || [];
            if (allB.includes(fieldA.value)) fieldB.value = fieldA.value;
        });
        row.querySelector(".remove-diff").addEventListener("click", () => {
            if (diffRows.children.length > 1) row.remove();
        });
        onNodeChange();
        if (preset) {
            if (preset.field_a) fieldA.value = preset.field_a;
            if (preset.field_b) fieldB.value = preset.field_b;
        }
    }

    function syncDiffRow(row) {
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
    }

    function collectDiffs() {
        return Array.from(diffRows.querySelectorAll(".diff-row")).map(row => {
            return row.querySelector(".node-a").value + ":" +
                row.querySelector(".field-a").value + "-" +
                row.querySelector(".node-b").value + ":" +
                row.querySelector(".field-b").value;
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
            rangeHint.textContent = "Single day: " + newest + ".";
        } else if (name === "yesterday") {
            start = end = availableDates[1] || newest;
            rangeHint.textContent = "Single day: " + start + ".";
        } else if (name === "last24h") {
            afterBound = new Date(now - 24 * 3600 * 1000).toISOString();
            const afterDay = afterBound.slice(0, 10);
            const daysAsc = availableDates.slice().reverse();
            if (afterDay <= oldest) start = oldest;
            else if (availableDates.includes(afterDay)) start = afterDay;
            else start = daysAsc.find(d => d >= afterDay) || newest;
            end = newest;
            rangeHint.textContent = "Rolling window: points after " + afterBound.slice(0, 19) + " UTC.";
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
        if (availableDates.length === 0) {
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
            nodeList.innerHTML = "";
            return;
        }
        const meta = await res.json();
        metaCache = meta;
        metaInfo.textContent = meta.day_count + " day(s), " + meta.row_count +
            " rows, " + meta.fields.length + " fields";

        nodeList.innerHTML = "";
        for (const node of meta.nodes) {
            const label = document.createElement("label");
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.value = node;
            cb.checked = true;
            cb.addEventListener("change", refreshFieldControls);
            label.appendChild(cb);
            label.appendChild(document.createTextNode(" " + node));
            nodeList.appendChild(label);
        }

        diffRows.innerHTML = "";
        updateModePanels();
        setStatus("Ready. Select options and click Plot.");
    }

    function destroyChart() {
        if (chart) { chart.destroy(); chart = null; }
    }

    function fmtTime(ms) {
        const d = new Date(ms);
        const multiDay = (metaCache.start && metaCache.end && metaCache.start !== metaCache.end)
            || (rangePreset.value !== "today" && rangePreset.value !== "yesterday");
        if (multiDay || afterBound) {
            return d.toISOString().slice(5, 16).replace("T", " ");
        }
        return d.toISOString().slice(11, 16);
    }

    function buildLineChart(datasets, yTitleOrFields) {
        const fields = Array.isArray(yTitleOrFields) ? yTitleOrFields : null;
        const useMultiAxis = fields && fields.length > 1;
        const axisId = f => "y_" + f.replace(/[^a-zA-Z0-9]/g, "_");

        const scales = {
            x: {
                type: "linear",
                title: { display: true, text: "Time (UTC)" },
                ticks: { maxTicksLimit: 12, callback: v => fmtTime(v) },
            },
        };

        if (useMultiAxis) {
            fields.forEach((f, idx) => {
                scales[axisId(f)] = {
                    type: "linear",
                    position: idx % 2 === 0 ? "left" : "right",
                    title: { display: true, text: f },
                    grid: { drawOnChartArea: idx === 0 },
                };
            });
            datasets.forEach(ds => {
                if (ds._axisField) ds.yAxisID = axisId(ds._axisField);
            });
        } else {
            scales.y = {
                title: {
                    display: true,
                    text: fields ? (fields[0] || "") : (yTitleOrFields || ""),
                },
            };
            datasets.forEach(ds => { ds.yAxisID = "y"; });
        }

        destroyChart();
        chart = new Chart(document.getElementById("chart"), {
            type: "line",
            data: { datasets },
            options: {
                parsing: false,
                scales: scales,
                plugins: {
                    legend: { display: true },
                    tooltip: {
                        callbacks: {
                            title: items => items.length
                                ? new Date(items[0].parsed.x).toISOString().slice(11, 19) + " UTC"
                                : "",
                        },
                    },
                },
            },
        });
    }

    function buildTimeChart(payload) {
        const fields = payload.fields || [];
        const datasets = [];
        let i = 0;
        for (const entry of Object.values(payload.series)) {
            datasets.push({
                label: entry.node + " \\u2022 " + entry.field,
                data: entry.points.map(p => ({ x: Date.parse(p.t), y: p.v })),
                borderColor: COLORS[i % COLORS.length],
                backgroundColor: COLORS[i % COLORS.length],
                tension: 0.1,
                pointRadius: 0,
                showLine: true,
                _axisField: entry.field,
            });
            i += 1;
        }
        buildLineChart(datasets, fields);
    }

    function buildDiffChart(payload) {
        const datasets = [];
        const axisFields = [];
        let i = 0;
        for (const entry of Object.values(payload.series)) {
            const axisField = entry.field_a === entry.field_b
                ? ("\\u0394 " + entry.field_a)
                : ("\\u0394 " + entry.field_a + "-" + entry.field_b);
            if (!axisFields.includes(axisField)) axisFields.push(axisField);
            datasets.push({
                label: entry.label,
                data: entry.points.map(p => ({ x: Date.parse(p.t), y: p.v })),
                borderColor: COLORS[i % COLORS.length],
                backgroundColor: COLORS[i % COLORS.length],
                tension: 0.1,
                pointRadius: 0,
                showLine: true,
                _axisField: axisField,
            });
            i += 1;
        }
        buildLineChart(datasets, axisFields);
    }

    function buildXYChart(payload) {
        const datasets = [];
        let i = 0;
        for (const [node, points] of Object.entries(payload.series)) {
            datasets.push({
                label: node,
                data: points.map(p => ({ x: p.x, y: p.y })),
                borderColor: COLORS[i % COLORS.length],
                backgroundColor: COLORS[i % COLORS.length],
                pointRadius: 3,
                showLine: false,
            });
            i += 1;
        }
        destroyChart();
        chart = new Chart(document.getElementById("chart"), {
            type: "scatter",
            data: { datasets },
            options: {
                scales: {
                    x: { title: { display: true, text: payload.x_field } },
                    y: { title: { display: true, text: payload.y_field } },
                },
                plugins: { legend: { display: true } },
            },
        });
    }

    async function runPlot() {
        const { start, end, q } = rangeQuery();
        const mode = plotMode();
        let url = "/api/series?" + q + "&mode=" + mode;

        if (mode === "diff") {
            const diffs = collectDiffs();
            if (!diffs.length) {
                setStatus("Add at least one difference.");
                return;
            }
            const tol = document.getElementById("tol-input").value || "60";
            url += "&diffs=" + encodeURIComponent(diffs.join(","))
                + "&tol_s=" + encodeURIComponent(tol);
        } else {
            const nodes = selectedNodes();
            if (nodes.length === 0) {
                setStatus("Select at least one node.");
                return;
            }
            url += "&nodes=" + encodeURIComponent(nodes.join(","));
            if (mode === "time") {
                const fields = selectedFields();
                if (fields.length === 0) {
                    setStatus("Select at least one field.");
                    return;
                }
                url += "&fields=" + encodeURIComponent(fields.join(","));
            } else {
                url += "&x=" + encodeURIComponent(xSelect.value)
                    + "&y=" + encodeURIComponent(ySelect.value);
            }
        }

        setStatus("Plotting...");
        const res = await fetch(url);
        const payload = await res.json();
        if (!res.ok) {
            setStatus(payload.message || "Plot failed");
            return;
        }

        let total = 0;
        if (mode === "xy") {
            for (const pts of Object.values(payload.series)) total += pts.length;
        } else {
            for (const entry of Object.values(payload.series)) total += entry.points.length;
        }
        if (total === 0) {
            setStatus("No numeric data for selection.");
            destroyChart();
            return;
        }

        const rangeLabel = start === end ? start : (start + " → " + end);
        if (mode === "time") buildTimeChart(payload);
        else if (mode === "diff") {
            buildDiffChart(payload);
            const parts = [];
            for (const [key, st] of Object.entries(payload.stats || {})) {
                parts.push(st.matched + " matched / " + st.unmatched + " unmatched");
            }
            setStatus("Plotted " + total + " diff points for " + rangeLabel +
                " (tol " + payload.tol_s + " s). " + parts.join("; "));
            return;
        } else buildXYChart(payload);
        setStatus("Plotted " + total + " points for " + rangeLabel + ".");
    }

    document.querySelectorAll('input[name="mode"]').forEach(r => {
        r.addEventListener("change", updateModePanels);
    });
    document.getElementById("add-diff-btn").addEventListener("click", () => addDiffRow());
    document.getElementById("quick-diff-btn").addEventListener("click", () => {
        if (metaCache.nodes.length < 2) {
            setStatus("Need at least two nodes for quick compare.");
            return;
        }
        const a = metaCache.nodes[0];
        const b = metaCache.nodes[1];
        const shared = sharedFields(a, b);
        if (!shared.length) {
            setStatus("No shared numeric fields between " + a + " and " + b + ".");
            return;
        }
        diffRows.innerHTML = "";
        for (const field of shared) {
            addDiffRow({ node_a: a, field_a: field, node_b: b, field_b: field });
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
