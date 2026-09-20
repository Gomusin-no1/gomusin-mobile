#!/usr/bin/env python3
"""Pull TrustFlow customer documents from Render to the Synology NAS.

Required environment variables:
  TRUSTFLOW_URL=https://trustflow-3ihn.onrender.com
  NAS_SYNC_TOKEN=...
  TRUSTFLOW_NAS_ROOT=/volume1/TrustFlow
"""
import hashlib
import json
import os
import pathlib
import tempfile
import urllib.request

BASE = os.environ.get("TRUSTFLOW_URL", "https://trustflow-3ihn.onrender.com").rstrip("/")
TOKEN = os.environ.get("NAS_SYNC_TOKEN", "").strip()
ROOT = pathlib.Path(os.environ.get("TRUSTFLOW_NAS_ROOT", "/volume1/TrustFlow")).resolve()


def request(path, *, data=None):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    return urllib.request.urlopen(urllib.request.Request(BASE + path, data=data, headers=headers), timeout=60)


def safe_target(relative):
    target = (ROOT / relative).resolve()
    if ROOT not in target.parents:
        raise RuntimeError("unsafe storage path")
    return target


def main():
    if len(TOKEN) < 32:
        raise RuntimeError("NAS_SYNC_TOKEN is missing or too short")
    ROOT.mkdir(parents=True, exist_ok=True)
    with request("/api/nas-sync/pending") as response:
        documents = json.load(response)["documents"]
    for doc in documents:
        target = safe_target(doc["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        with request(f'/api/nas-sync/documents/{doc["id"]}') as response:
            content = response.read()
        digest = hashlib.sha256(content).hexdigest()
        if digest != doc["sha256"]:
            raise RuntimeError(f'hash mismatch for document {doc["id"]}')
        fd, temporary = tempfile.mkstemp(prefix=".trustflow-", dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        with request(f'/api/nas-sync/documents/{doc["id"]}/ack', data={"sha256": digest}):
            pass


if __name__ == "__main__":
    main()
