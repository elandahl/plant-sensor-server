"""WiFi OTA client for MicroPython Pico W."""

import hashlib
import json
import machine
import os
import urequests

PROTECTED = {"secrets.py"}


def _server_base(server_base):
    return server_base.rstrip("/")


def fetch_manifest(server_base):
    url = _server_base(server_base) + "/api/firmware/manifest"
    response = urequests.get(url)
    try:
        if response.status_code != 200:
            print("OTA manifest HTTP", response.status_code)
            return None
        return json.loads(response.text)
    finally:
        response.close()


def _sha256(data):
    digest = hashlib.sha256(data).digest()
    return "".join("{:02x}".format(b) for b in digest)


def _ensure_parent_dir(filepath):
    if "/" not in filepath:
        return
    directory = filepath.rsplit("/", 1)[0]
    parts = directory.split("/")
    path = ""
    for part in parts:
        path = part if not path else path + "/" + part
        try:
            os.mkdir(path)
        except OSError:
            pass


def _download_file(server_base, rel_path):
    url = _server_base(server_base) + "/api/firmware/file/" + rel_path
    response = urequests.get(url)
    try:
        if response.status_code != 200:
            raise OSError("HTTP " + str(response.status_code))
        return response.content
    finally:
        response.close()


def _install_file(rel_path, data, expected_sha256, expected_size):
    if len(data) != expected_size:
        raise OSError("size mismatch for " + rel_path)

    digest = _sha256(data)
    if digest != expected_sha256:
        raise OSError("hash mismatch for " + rel_path)

    temp_path = rel_path + ".new"
    backup_path = rel_path + ".bak"

    _ensure_parent_dir(rel_path)

    with open(temp_path, "wb") as f:
        f.write(data)

    try:
        os.remove(backup_path)
    except OSError:
        pass

    try:
        os.rename(rel_path, backup_path)
    except OSError:
        pass

    try:
        os.rename(temp_path, rel_path)
    except OSError:
        try:
            os.rename(backup_path, rel_path)
        except OSError:
            pass
        raise


def update_available(manifest, current_version):
    if manifest is None:
        return False
    return manifest.get("version") != current_version


def apply_manifest(server_base, manifest):
    for entry in manifest.get("files", []):
        rel_path = entry["path"]
        if rel_path in PROTECTED:
            print("OTA skip protected", rel_path)
            continue

        print("OTA fetch", rel_path)
        data = _download_file(server_base, rel_path)
        _install_file(rel_path, data, entry["sha256"], entry["size"])
        print("OTA installed", rel_path)


def check_and_apply(server_base, current_version):
    """Return True if an update was applied (caller should reset)."""
    try:
        manifest = fetch_manifest(server_base)
        if not update_available(manifest, current_version):
            return False

        print("OTA update", current_version, "->", manifest.get("version"))
        apply_manifest(server_base, manifest)
        print("OTA complete, rebooting")
        return True
    except Exception as e:
        print("OTA failed:", e)
        return False
