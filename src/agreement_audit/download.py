"""Turning a link from the tracker sheet into file bytes."""
import io
import re
import threading
import time
from urllib.parse import quote, unquote

import requests

from .errors import RowError


def drive_id(url):
    """Google Drive file id, or None for any other kind of link (incl. docs.google.com/viewer wrappers)."""
    if not re.search(r"(drive|docs)\.google\.com", url) or re.search(r"docs\.google\.com/viewer", url):
        return None
    m = re.search(r"/d/([a-zA-Z0-9_-]{20,})", url) or re.search(r"[?&]id=([a-zA-Z0-9_-]{20,})", url)
    return m.group(1) if m else None


def direct_url(raw):
    """Google viewer link -> real file link, safely encoded (avoids double-encoding %20 -> %2520)."""
    url = raw.strip()
    if re.search(r"docs\.google\.com/viewer", url, re.I):
        m = re.search(r"[?&]url=(.+)$", url)
        if m:
            url = re.sub(r"&(?:embedded|a|chrome|hl|pid|srcid)=[^&]*", "", m.group(1), flags=re.I)
            if re.match(r"https?%3A", url, re.I):
                url = unquote(url)
    url = re.sub(r"%(?![0-9A-Fa-f]{2})", "%25", url)
    return quote(url, safe=":/?#[]@!$&'()*+,;=%-._~")


def file_name_from_url(url):
    """'.../files/Green%20Meadows%20B%20wing%20-1--<uuid>.pdf/<id>' -> 'Green Meadows B wing -1--<uuid>.pdf'"""
    path = unquote(url.split("?")[0].split("#")[0])
    parts = [p for p in path.split("/") if p]
    with_ext = [p for p in parts if re.search(r"\.(pdf|jpe?g|png)(?=[^a-z]|$)", p, re.I)]
    return with_ext[-1] if with_ext else ""


def download_direct(url):
    """HTTP download with retries only for errors that can fix themselves (429 / 5xx / network)."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "Accept": "*/*"}
    last = ""
    for attempt in range(1, 4):
        try:
            r = requests.get(url, headers=headers, timeout=60, allow_redirects=True)
        except requests.RequestException as e:
            last = f"Network error: {e.__class__.__name__}"
            time.sleep(attempt * 2)
            continue
        if r.status_code == 200:
            return r.content
        last = f"Download failed (HTTP {r.status_code})"
        if r.status_code not in (429, 500, 502, 503, 504):
            break                      # 403 / 404 won't fix themselves
        time.sleep(attempt * 2)
    raise RowError(last or "Download failed")


# ---------- Google Drive (only used when running against a Google Sheet) ----------
_local = threading.local()


def _drive_service(creds):
    # googleapiclient isn't thread-safe, so each worker thread gets its own client
    from googleapiclient.discovery import build
    if not hasattr(_local, "drive"):
        _local.drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _local.drive


def download_drive(file_id, creds):
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaIoBaseDownload
    svc = _drive_service(creds)
    try:
        meta = svc.files().get(fileId=file_id, fields="name,mimeType", supportsAllDrives=True).execute()
        if meta["mimeType"].startswith("application/vnd.google-apps"):
            req = svc.files().export_media(fileId=file_id, mimeType="application/pdf")
        else:
            req = svc.files().get_media(fileId=file_id, supportsAllDrives=True)
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        return buf.getvalue(), meta.get("name", "")
    except HttpError as e:
        code = e.resp.status
        if code == 404:
            raise RowError("No access to this Drive file (check sharing)")
        if code == 403 and "cannotDownload" in str(e):
            raise RowError("Owner has blocked downloads for viewers")
        raise RowError(f"Drive download failed (HTTP {code})")


def fetch(url, creds=None):
    """Returns (bytes, file_name) for a Drive link or any direct / viewer-wrapped link."""
    fid = drive_id(url)
    if fid:
        if creds is None:
            raise RowError("Drive link needs Google credentials")
        return download_drive(fid, creds)
    durl = direct_url(url)
    return download_direct(durl), file_name_from_url(durl)


def file_kind(data):
    """Sniffs the real file type from magic bytes (links often lie about extensions)."""
    head = data[:1024]
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b"%PDF" in head:
        return "pdf"
    low = head.lower()
    if b"<html" in low or b"<!doctype" in low:
        return "html"
    return "other"
