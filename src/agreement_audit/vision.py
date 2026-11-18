"""Image preparation + the rate-limited, retrying client for the vision model."""
import base64
import io
import json
import random
import re
import threading
import time

import pymupdf
import requests
from PIL import Image

from .config import SETTINGS
from .errors import FatalError, RowError


# ------------------------------ images ------------------------------
def render_page(page, width=1600):
    zoom = width / page.rect.width
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def to_b64(img, limit=None):
    """JPEG that always fits the API's inline-image limit: lowers quality first, then size."""
    limit = limit or SETTINGS.max_image_b64_chars
    img = img.convert("RGB")
    start = min(img.width, 1600)
    for w in [start] + [x for x in (1400, 1200, 1000, 850, 700, 560, 450) if x < start]:
        im = img if img.width == w else img.resize((w, round(img.height * w / img.width)), Image.LANCZOS)
        for q in (85, 75, 65):
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=q, optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode()
            if len(b64) <= limit:
                return b64
    raise RowError("Page image too large to send")


def top_part(img, share=0.45):
    """Crop used for the 'zoom in' second attempt at reading the name table."""
    return img.crop((0, 0, img.width, int(img.height * share)))


# ------------------------------ API client ------------------------------
_ai_lock = threading.Lock()
_last_ai_call = [0.0]


def call_vision(b64, prompt, max_tokens=150, s=SETTINGS):
    if not s.api_key:
        raise FatalError("NVIDIA_API_KEY is not set (see .env.example)")
    with _ai_lock:                                   # spaces out calls across ALL worker threads
        wait = _last_ai_call[0] + s.min_seconds_between_ai_calls - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_ai_call[0] = time.time()

    payload = {
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": prompt}]}],
        "max_tokens": max_tokens, "temperature": 0.0, "top_p": 1, "stream": False}
    headers = {"Authorization": f"Bearer {s.api_key}", "Accept": "application/json"}

    # 3 tries with the main model; if all time out / are busy, 1 last try with the faster fallback model
    models = [s.model] * 3 + ([s.fallback_model] if s.fallback_model else [s.model])
    last = len(models)
    for attempt, model in enumerate(models, 1):
        try:
            r = requests.post(s.api_url, headers=headers, json={"model": model, **payload}, timeout=s.ai_timeout)
        except requests.RequestException as e:
            if attempt == last:
                raise RowError(f"Vision API network error: {e.__class__.__name__} (after {last} tries)")
            time.sleep(attempt * 5 + random.random() * 3)        # backoff with jitter
            continue
        if r.status_code == 200:
            try:
                return r.json()["choices"][0]["message"]["content"] or ""
            except Exception:
                raise RowError("Unexpected vision API response")
        if r.status_code in (401, 402, 403):
            raise FatalError(f"Vision API {r.status_code}: check your key / credits - {r.text[:150]}")
        if r.status_code in (429, 500, 502, 503, 504) and attempt < last:
            time.sleep(attempt * 6 + random.random() * 3)        # rate limit / server busy
            continue
        try:
            j = r.json()
            msg = j.get("detail") or (j.get("error") or {}).get("message") or r.text[:150]
        except Exception:
            msg = r.text[:150]
        raise RowError(f"Vision API {r.status_code}: {msg}")


# ------------------------------ parsing the reply ------------------------------
def yes_no(v):
    if v is True:
        return "Yes"
    if v is False:
        return "No"
    s = str(v or "").strip()
    if re.match(r"(?i)^y", s):
        return "Yes"
    if re.match(r"(?i)^(no\b|n$)", s):
        return "No"
    return None


def parse_reply(text):
    """
    Reads the model's JSON even when it wraps it in markdown, adds extra words or breaks the format.
    A field the model did not answer comes back as None - never silently as "No".
    """
    text = re.sub(r"```(?:json)?", "", str(text or ""), flags=re.I).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            p = json.loads(m.group(0))
            return {"society_name": p.get("society_name"),
                    "name_box_filled": yes_no(p.get("name_box_filled")) if "name_box_filled" in p else None,
                    "is_stamped": yes_no(p.get("is_stamped")) if "is_stamped" in p else None,
                    "is_signed": yes_no(p.get("is_signed")) if "is_signed" in p else None}
        except Exception:
            pass
    name = re.search(r'"?society_name"?\s*:\s*"([^"]*)"', text, re.I)
    fl = re.search(r'"?name_box_filled"?\s*:\s*"?(yes|no)\b', text, re.I)
    st = re.search(r'"?is_stamped"?\s*:\s*"?(yes|no)\b', text, re.I)
    sg = re.search(r'"?is_signed"?\s*:\s*"?(yes|no)\b', text, re.I)
    return {"society_name": name.group(1) if name else None,
            "name_box_filled": yes_no(fl.group(1)) if fl else None,
            "is_stamped": yes_no(st.group(1)) if st else None,
            "is_signed": yes_no(sg.group(1)) if sg else None}
