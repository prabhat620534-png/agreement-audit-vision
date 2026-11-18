"""
Audits ONE document: cheap deterministic checks first, the vision model only for what is still unknown.

    bytes -> sniff type -> open PDF/image -> digital-signature + table/text checks (free)
          -> vision model on the first / last / second-last page, asking ONLY the open questions
          -> guarded answers ("Review" instead of a guessed "No")
"""
import io
import re
from dataclasses import dataclass

import pymupdf
from PIL import Image, ImageOps

from .config import SETTINGS
from .download import file_kind
from .errors import RowError
from .prompts import build_prompt
from .signatures import ESIGN_TEXT, digital_signature
from .society_name import clean_name, name_from_tables, name_from_text, name_hint
from .vision import call_vision, parse_reply, render_page, to_b64, top_part


@dataclass
class AuditResult:
    society_name: str
    is_stamped: str      # "Yes" / "No" / "Review"
    is_signed: str       # "Yes" / "No" / "Review"
    notes: str           # how each answer was found - makes every result explainable

    def as_row(self):
        return [self.society_name, self.is_stamped, self.is_signed, self.notes]


def _pages_to_check(doc, limit):
    """First page (name table) + last and second-last pages (where signatures and stamps usually are)."""
    n = doc.page_count
    order = []
    for i in (0, n - 1, n - 2) + tuple(range(1, n)):
        if 0 <= i < n and i not in order:
            order.append(i)
    return [(f"p{i + 1}/{n}", (lambda i=i: render_page(doc[i])), (lambda i=i: render_page(doc[i], 2600)))
            for i in order[:limit]]


def audit_document(data: bytes, file_name: str = "", use_vision: bool = True, s=SETTINGS) -> AuditResult:
    notes = []
    hint = name_hint(file_name)
    kind = file_kind(data)
    if kind == "html":
        raise RowError("Link returned a web page, not a file (check link / sharing)")
    notes.append(kind.upper())

    # 1. Open the document and decide which pages the model may look at
    text, doc = "", None
    if kind == "pdf":
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception:
            raise RowError("Damaged or unreadable PDF")
        if doc.needs_pass:
            raise RowError("Password-protected PDF")
        text = "\n".join(p.get_text() for p in doc)
        pages = _pages_to_check(doc, s.max_pages_to_check)
        notes.append(f"{doc.page_count} page(s), text {len(text)} chars")
    elif kind in ("jpeg", "png"):
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")   # fixes phone-photo rotation
        pages = [("image", lambda: img, lambda: img)]
    else:
        try:                                        # other types PyMuPDF can open (XPS, EPUB, TIFF ...)
            doc = pymupdf.open(stream=data)
            text = "\n".join(p.get_text() for p in doc)
            pages = [(f"p{i + 1}", (lambda i=i: render_page(doc[i])), (lambda i=i: render_page(doc[i], 2600)))
                     for i in range(min(doc.page_count, s.max_pages_to_check))]
        except Exception:
            raise RowError("Unsupported file type (not PDF or image)")

    # 2. Free checks: digital signature + society name from tables / text
    if kind == "pdf":
        digital = digital_signature(data, text)
    else:
        digital = ["Aadhaar eSign text"] if ESIGN_TEXT.search(text) else []
    if digital:
        notes.append("Digital: " + ", ".join(digital))

    society, box_empty = None, False
    if doc is not None and kind == "pdf":
        society, box_empty = name_from_tables(doc)
        if society:
            notes.append("Name: table")
        elif box_empty:
            notes.append("Name box empty (table)")
    if not society and not box_empty and text:
        society = name_from_text(text)
        if society:
            notes.append("Name: text")

    stamped = "Yes" if (digital and s.esign_counts_as_stamp) else None
    signed = "Yes" if digital else None
    answered = {"st": stamped is not None, "sg": signed is not None}

    # 3. Vision model - only for the questions that are still open
    checked = []

    def note_rejected(raw, where):
        raw = str(raw or "").strip()
        if raw and not re.fullmatch(r"(?i)not\s*listed\.?", raw):
            notes.append(f'{where} name rejected: "{raw[:50]}"')

    for idx, (label, get_img, get_hi_img) in enumerate(pages if use_vision else []):
        want_name = society is None and not box_empty and idx == 0
        want_stamp, want_sign = stamped != "Yes", signed != "Yes"
        if not (want_name or want_stamp or want_sign):
            break                                   # everything answered - stop spending calls

        reply = parse_reply(call_vision(to_b64(get_img()), build_prompt(want_name, want_stamp, want_sign, hint), s=s))
        checked.append(label)

        if want_name:
            society = clean_name(reply["society_name"])
            if society:
                notes.append(f"Name: vision {label}")
            else:                                   # second try: zoom into the top table at high resolution
                note_rejected(reply["society_name"], "vision")
                r2 = parse_reply(call_vision(to_b64(top_part(get_hi_img(), 0.42)),
                                             build_prompt(True, False, False, hint), 100, s=s))
                society = clean_name(r2["society_name"])
                if society:
                    notes.append(f"Name: vision zoom {label}")
                else:
                    note_rejected(r2["society_name"], "zoom")
                    if (r2["name_box_filled"] or reply["name_box_filled"]) == "No":
                        box_empty = True
                        notes.append("Name box empty (vision)")

        if want_stamp and reply["is_stamped"] is not None:
            answered["st"] = True
            if reply["is_stamped"] == "Yes":
                stamped = "Yes"
                notes.append(f"stamp {label}")
        if want_sign and reply["is_signed"] is not None:
            answered["sg"] = True
            if reply["is_signed"] == "Yes":
                signed = "Yes"
                notes.append(f"sign {label}")

    if checked:
        notes.append("Vision checked " + ", ".join(checked))

    # Last resort for the name: the file name - only if the box actually has something written in it
    if not society and hint and not box_empty:
        society = hint
        notes.append("Name: file name (check)")

    # 4. "No" only if the model actually answered; otherwise flag for a human
    stamped = stamped or ("No" if answered["st"] else "Review")
    signed = signed or ("No" if answered["sg"] else "Review")
    return AuditResult(society or "Not listed", stamped, signed, " | ".join(notes))
