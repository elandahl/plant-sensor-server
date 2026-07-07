#!/usr/bin/env python3
"""Build manifest.json for a firmware release directory."""

import hashlib
import json
import sys
from pathlib import Path


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(release_dir):
    release_dir = Path(release_dir)
    if not release_dir.is_dir():
        raise SystemExit(f"Not a directory: {release_dir}")

    files = []
    for path in sorted(release_dir.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        rel = path.relative_to(release_dir).as_posix()
        files.append({
            "path": rel,
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
        })

    manifest = {"version": release_dir.name, "files": files}
    manifest_path = release_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Wrote {manifest_path} ({len(files)} files, version {release_dir.name})")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} firmware/releases/<version>")
    build_manifest(sys.argv[1])
