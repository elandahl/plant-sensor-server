from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime, timezone
import csv
import json
import os

app = Flask(__name__)

DATA_DIR = "data"
latest = {}

os.makedirs(DATA_DIR, exist_ok=True)


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
                "integrity_json"
            ])

        writer.writerow([
            record["server_timestamp"],
            record["node_id"],
            record.get("firmware_version", ""),
            json.dumps(record.get("readings", {})),
            json.dumps(record.get("integrity", {}))
        ])


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
        "integrity": data.get("integrity", {})
    }

    latest[node_id] = record
    append_csv(record)

    return jsonify({"status": "received"})


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

        temp = readings.get("temperature_F", "")
        humidity = readings.get("humidity_percent", "")
        state = integrity.get("state", "")

        last_seen = t.astimezone().strftime("%H:%M:%S")

        rows += f"""
        <tr>
            <td>{node_id}</td>
            <td>{last_seen}</td>
            <td>{age_s} s</td>
            <td>{temp}</td>
            <td>{humidity}</td>
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
                <th>Temp F</th>
                <th>Humidity %</th>
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
