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


@app.route("/api/plot/dates", methods=["GET"])
def plot_dates():
    return jsonify({"dates": history.list_dates()})


@app.route("/api/plot/meta", methods=["GET"])
def plot_meta():
    date_str = request.args.get("date", "")
    if not date_str:
        return jsonify({"status": "error", "message": "Missing date"}), 400
    if history.csv_path(date_str) is None:
        return jsonify({"status": "error", "message": "No data for date"}), 404
    return jsonify(history.day_meta(date_str))


@app.route("/api/series", methods=["GET"])
def plot_series():
    date_str = request.args.get("date", "")
    mode = request.args.get("mode", "time")
    node_ids = _parse_node_list(request.args.get("nodes", ""))

    if not date_str:
        return jsonify({"status": "error", "message": "Missing date"}), 400
    if history.csv_path(date_str) is None:
        return jsonify({"status": "error", "message": "No data for date"}), 404
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
        return jsonify(history.series_time(date_str, node_ids, fields))

    if mode == "xy":
        x_field = request.args.get("x", "")
        y_field = request.args.get("y", "")
        if not x_field or not y_field:
            return jsonify({"status": "error", "message": "Missing x or y field"}), 400
        return jsonify(history.series_xy(date_str, node_ids, x_field, y_field))

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
        select, button { font-size: 1em; padding: 0.25em 0.5em; }
        #status { color: #555; margin: 1em 0; }
        #chart-wrap { max-width: 1000px; }
        a { color: #06c; }
    </style>
</head>
<body>
    <h1>Plant Sensor Plot</h1>
    <p><a href="/check">Back to check</a></p>

    <fieldset>
        <legend>Data</legend>
        <label>Date
            <select id="date-select"></select>
        </label>
        <span id="meta-info"></span>
    </fieldset>

    <fieldset>
        <legend>Nodes</legend>
        <div id="node-list" class="nodes"></div>
    </fieldset>

    <fieldset>
        <legend>Plot</legend>
        <label><input type="radio" name="mode" value="time" checked> vs time</label>
        <label><input type="radio" name="mode" value="xy"> X vs Y</label>
        <div id="time-fields" style="margin-top:0.75em">
            <div style="margin-bottom:0.35em">Fields (select one or more):</div>
            <div id="field-list" class="nodes"></div>
        </div>
        <div id="xy-fields" style="margin-top:0.75em; display:none">
            <label>X <select id="x-select"></select></label>
            <label>Y <select id="y-select"></select></label>
        </div>
        <div style="margin-top:0.75em">
            <button id="plot-btn" type="button">Plot</button>
        </div>
    </fieldset>

    <p id="status">Loading dates...</p>
    <div id="chart-wrap"><canvas id="chart"></canvas></div>

    <script>
    const dateSelect = document.getElementById("date-select");
    const nodeList = document.getElementById("node-list");
    const fieldList = document.getElementById("field-list");
    const xSelect = document.getElementById("x-select");
    const ySelect = document.getElementById("y-select");
    const metaInfo = document.getElementById("meta-info");
    const statusEl = document.getElementById("status");
    const timeFields = document.getElementById("time-fields");
    const xyFields = document.getElementById("xy-fields");
    let chart = null;

    const COLORS = [
        "#2563eb", "#dc2626", "#16a34a", "#ca8a04",
        "#9333ea", "#0891b2", "#ea580c", "#4b5563",
    ];

    function setStatus(msg) { statusEl.textContent = msg; }

    function fillSelect(select, items, preferred) {
        select.innerHTML = "";
        for (const item of items) {
            const opt = document.createElement("option");
            opt.value = item;
            opt.textContent = item;
            select.appendChild(opt);
        }
        if (preferred && items.includes(preferred)) {
            select.value = preferred;
        }
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

    async function loadDates() {
        const res = await fetch("/api/plot/dates");
        const data = await res.json();
        dateSelect.innerHTML = "";
        for (const d of data.dates) {
            const opt = document.createElement("option");
            opt.value = d;
            opt.textContent = d;
            dateSelect.appendChild(opt);
        }
        if (data.dates.length === 0) {
            setStatus("No CSV data files found.");
            return;
        }
        await loadMeta();
    }

    async function loadMeta() {
        const date = dateSelect.value;
        setStatus("Loading " + date + "...");
        const res = await fetch("/api/plot/meta?date=" + encodeURIComponent(date));
        if (!res.ok) {
            setStatus("No data for " + date);
            nodeList.innerHTML = "";
            return;
        }
        const meta = await res.json();
        metaInfo.textContent = meta.row_count + " rows, " + meta.fields.length + " fields";

        nodeList.innerHTML = "";
        for (const node of meta.nodes) {
            const label = document.createElement("label");
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.value = node;
            cb.checked = true;
            label.appendChild(cb);
            label.appendChild(document.createTextNode(" " + node));
            nodeList.appendChild(label);
        }

        fieldList.innerHTML = "";
        for (const field of meta.fields) {
            const label = document.createElement("label");
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.value = field;
            cb.checked = field === "temperature_F";
            label.appendChild(cb);
            label.appendChild(document.createTextNode(" " + field));
            fieldList.appendChild(label);
        }

        fillSelect(xSelect, meta.fields, "ble_devices_close");
        fillSelect(ySelect, meta.fields, "co2_ppm");
        setStatus("Ready. Select nodes and click Plot.");
    }

    function destroyChart() {
        if (chart) { chart.destroy(); chart = null; }
    }

    function buildTimeChart(payload) {
        const datasets = [];
        const fields = payload.fields || [];
        const useMultiAxis = fields.length > 1;
        const axisId = f => "y_" + f;

        let i = 0;
        for (const entry of Object.values(payload.series)) {
            datasets.push({
                label: entry.node + " \u2022 " + entry.field,
                data: entry.points.map(p => ({ x: p.t, y: p.v })),
                borderColor: COLORS[i % COLORS.length],
                backgroundColor: COLORS[i % COLORS.length],
                tension: 0.1,
                pointRadius: 2,
                showLine: true,
                yAxisID: useMultiAxis ? axisId(entry.field) : "y",
            });
            i += 1;
        }

        const scales = {
            x: {
                type: "category",
                title: { display: true, text: "Time (UTC)" },
                ticks: { maxTicksLimit: 12 },
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
        } else {
            scales.y = { title: { display: true, text: fields[0] || "" } };
        }

        destroyChart();
        chart = new Chart(document.getElementById("chart"), {
            type: "line",
            data: { datasets },
            options: {
                parsing: false,
                scales: scales,
                plugins: { legend: { display: true } },
            },
        });
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
        const nodes = selectedNodes();
        if (nodes.length === 0) {
            setStatus("Select at least one node.");
            return;
        }
        const date = dateSelect.value;
        const mode = plotMode();
        let url = "/api/series?date=" + encodeURIComponent(date)
            + "&nodes=" + encodeURIComponent(nodes.join(","))
            + "&mode=" + mode;
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
        setStatus("Plotting...");
        const res = await fetch(url);
        const payload = await res.json();
        if (!res.ok) {
            setStatus(payload.message || "Plot failed");
            return;
        }
        let total = 0;
        for (const entry of Object.values(payload.series)) {
            total += mode === "time" ? entry.points.length : entry.length;
        }
        if (total === 0) {
            setStatus("No numeric data for selection.");
            destroyChart();
            return;
        }
        if (mode === "time") buildTimeChart(payload);
        else buildXYChart(payload);
        setStatus("Plotted " + total + " points for " + date + ".");
    }

    document.querySelectorAll('input[name="mode"]').forEach(r => {
        r.addEventListener("change", () => {
            const xy = plotMode() === "xy";
            timeFields.style.display = xy ? "none" : "block";
            xyFields.style.display = xy ? "block" : "none";
        });
    });
    dateSelect.addEventListener("change", loadMeta);
    document.getElementById("plot-btn").addEventListener("click", runPlot);

    loadDates();
    </script>
</body>
</html>"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
