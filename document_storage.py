import base64
import hashlib
import os
import posixpath
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime


class StorageUnavailable(RuntimeError):
    pass


def _env(name, default=""):
    return os.environ.get(name, default).strip()


def nas_enabled():
    return bool(_env("NAS_WEBDAV_URL") and _env("NAS_WEBDAV_USERNAME") and _env("NAS_WEBDAV_PASSWORD"))


def build_object_path(company_code, branch_id, sale_id, original_name, now=None):
    now = now or datetime.utcnow()
    ext = os.path.splitext(original_name or "")[1].lower()
    if ext not in {".pdf", ".jpg", ".jpeg", ".png", ".webp"}:
        ext = ""
    safe_company = "".join(c for c in (company_code or "trustflow") if c.isalnum() or c in "-_") or "trustflow"
    safe_branch = str(int(branch_id or 0))
    safe_sale = str(int(sale_id))
    return posixpath.join(safe_company, safe_branch, now.strftime("%Y"), now.strftime("%m"), safe_sale, f"{uuid.uuid4().hex}{ext}")


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def _request(method, relative_path, data=None, content_type=None):
    base = _env("NAS_WEBDAV_URL").rstrip("/") + "/"
    quoted = "/".join(urllib.parse.quote(p, safe="") for p in relative_path.strip("/").split("/"))
    url = urllib.parse.urljoin(base, quoted)
    token = base64.b64encode(f'{_env("NAS_WEBDAV_USERNAME")}:{_env("NAS_WEBDAV_PASSWORD")}'.encode()).decode()
    headers = {"Authorization": f"Basic {token}"}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    timeout = float(_env("NAS_WEBDAV_TIMEOUT", "12"))
    context = ssl.create_default_context()
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=context)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        raise StorageUnavailable(str(exc)) from exc


def _ensure_directories(relative_path):
    current = []
    for part in relative_path.strip("/").split("/")[:-1]:
        current.append(part)
        try:
            with _request("MKCOL", "/".join(current)):
                pass
        except StorageUnavailable as exc:
            # 405 means the collection already exists. urllib wraps it, so inspect the message.
            if "405" not in str(exc):
                raise


def put(relative_path, data, content_type):
    if not nas_enabled():
        raise StorageUnavailable("NAS WebDAV is not configured")
    _ensure_directories(relative_path)
    with _request("PUT", relative_path, data=data, content_type=content_type) as response:
        if response.status not in (200, 201, 204):
            raise StorageUnavailable(f"unexpected WebDAV status: {response.status}")


def get(relative_path):
    if not nas_enabled():
        raise StorageUnavailable("NAS WebDAV is not configured")
    with _request("GET", relative_path) as response:
        return response.read()


def delete(relative_path):
    if not relative_path or not nas_enabled():
        return
    try:
        with _request("DELETE", relative_path):
            pass
    except StorageUnavailable as exc:
        if "404" not in str(exc):
            raise


def encrypt_fallback(data):
    key = _env("DOCUMENT_ENCRYPTION_KEY")
    if not key:
        return data, False
    from cryptography.fernet import Fernet
    return Fernet(key.encode()).encrypt(data), True


def decrypt_fallback(data, encrypted):
    if not encrypted:
        return data
    key = _env("DOCUMENT_ENCRYPTION_KEY")
    if not key:
        raise StorageUnavailable("DOCUMENT_ENCRYPTION_KEY is missing")
    from cryptography.fernet import Fernet
    return Fernet(key.encode()).decrypt(data)
