from flask import Flask, request, jsonify, send_from_directory, abort
from datetime import datetime, timezone
import csv
import json
import os

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
        <p>Known nodes: {len(latest)}</p>

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
