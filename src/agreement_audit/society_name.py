"""Finding the customer (society) name: PDF tables first, then text, then the vision model, then the file name."""
import re

import pymupdf

from .config import SETTINGS


def clean_name(raw, vendor_regex=None):
    """
    Returns a clean society / customer name, or None if the value is empty, a form label,
    the vendor's own name, or a sentence (e.g. a model saying "Sorry, I cannot read...").
    This is the guardrail every candidate name - from tables, text or the LLM - must pass.
    """
    vendor_regex = vendor_regex or SETTINGS.vendor_regex
    s = re.sub(r"\s+", " ", str(raw or "")).strip()
    s = re.sub(r"^(?:society\s*name|name\s*of\s*(?:the\s*)?society(?:\s*\(\s*customer\s*\))?|name)\s*[:\-–]\s*",
               "", s, flags=re.I)
    s = s.strip("\"'“”‘’ ").strip()
    if not s or re.fullmatch(r"(?i)not\s*listed\.?|n/?a|nil|none|null|-+|blank|empty|unknown", s):
        return None
    if vendor_regex.search(s) or len(s) < 3 or len(s) > 100 or not re.search(r"[A-Za-z]{2,}", s):
        return None
    if len(s.split()) > 14 or s.startswith("(") or re.search(r"(?i)name\s+of", s):
        return None
    if re.match(r"(?i)(city|address|location|products?\s+sold|constructed|occupied|date|phone|email|customer)\b", s):
        return None
    if re.search(r"(?i)\b(sorry|cannot|unable|i\s+can|the\s+image|appears\s+to)\b", s):
        return None
    return s


LABEL = re.compile(r"name\s*of\s*(?:the\s*)?society", re.I)


def name_from_tables(doc):
    """
    Reads the cell next to (or below) 'Name of society' in the first pages' tables.
    Returns (name, box_empty). box_empty = True when the label was found and the box next to it
    is truly blank (no text, no image, no ink/annotation) - e.g. an unfilled template.
    """
    box_empty = False
    for page in list(doc)[:2]:
        try:
            tables = page.find_tables().tables
        except Exception:
            continue
        try:
            image_boxes = [pymupdf.Rect(i["bbox"]) for i in page.get_image_info()]
        except Exception:
            image_boxes = []
        annot_boxes = [a.rect for a in page.annots()] if page.first_annot else []

        for t in tables:
            # Read each cell's text from its area on the page (keeps the spaces between words)
            boxes = [list(trow.cells) for trow in t.rows]
            rows = [[(page.get_textbox(pymupdf.Rect(b)) or "").strip() if b else "" for b in brow] for brow in boxes]
            for r, row in enumerate(rows):
                for c, cell in enumerate(row):
                    if not cell or not LABEL.search(cell):
                        continue
                    for v in row[c + 1:]:                       # next filled cell, same row
                        if clean_name(v):
                            return clean_name(v), False
                    if r + 1 < len(rows) and c < len(rows[r + 1]) and clean_name(rows[r + 1][c]):
                        return clean_name(rows[r + 1][c]), False   # cell below
                    inline = LABEL.split(cell, 1)[-1]           # label and value in one cell
                    inline = re.sub(r"^\s*\(?\s*customer\s*\)?\s*[:\-–]?", "", inline, flags=re.I)
                    if clean_name(inline):
                        return clean_name(inline), False

                    # Nothing readable: is the value box really blank, or is there handwriting/an image?
                    value_boxes = [pymupdf.Rect(b) for b in boxes[r][c + 1:] if b]
                    no_text = all(not v.strip() for v in row[c + 1:]) and not inline.strip()
                    covered = any(vb.intersects(ob) for vb in value_boxes for ob in image_boxes + annot_boxes)
                    if value_boxes and no_text and not covered:
                        box_empty = True
    return None, box_empty


def name_from_text(text):
    """Fallback: 'Name of society (customer)' followed by the value on the same or next lines."""
    lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines()]
    lines = [l for l in lines if l]
    cut = lambda s: re.split(r"\s+(?:City|Constructed|Occupied|Products|Address|Location|Subscription)\b",
                             s, flags=re.I)[0]
    for i, line in enumerate(lines):
        m = re.search(r"name\s+of\s+(?:the\s+)?society\s*(?:\(?\s*customer\s*\)?)?\s*[:\-–]?\s*", line, re.I)
        if not m:
            continue
        cand = clean_name(cut(line[m.end():]))
        j = i + 1
        while not cand and j < min(i + 4, len(lines)):
            cand = clean_name(cut(re.sub(r"^\(?\s*customer\s*\)?\s*[:\-–]?\s*", "", lines[j], flags=re.I)))
            j += 1
        if cand:
            return cand
    return None


# Words that show up in uploaded file names but are never part of a society's name
_FILE_NOISE = (r"agreements?|contract|signed|unsigned|final|draft|copy|scan(?:ned)?|sales|pager|page|pages|one|"
               r"template|format|form|blank|sample|new|doc|document|file|image|img|pdf|annexure|version|v\d*|"
               r"updated|revised|whatsapp|uploads?")


def name_hint(file_name):
    """Cleans a file name into a name hint: 'Green Meadows B wing -1--<uuid>.pdf' -> 'Green Meadows B wing'."""
    s = str(file_name or "")
    s = re.sub(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", " ", s, flags=re.I)
    s = re.sub(r"\.(pdf|jpe?g|png|docx?)(?=[^a-z]|$)", " ", s, flags=re.I)
    s = re.sub(r"[_\-]+", " ", s)
    s = SETTINGS.vendor_regex.sub(" ", s)
    s = re.sub(rf"(?i)\b({_FILE_NOISE})\b", " ", s)
    s = re.sub(r"\b\d+\b", " ", s)                                          # loose numbers like "-1-"
    s = re.sub(r"\b(?=[a-f0-9]*\d)[a-f0-9]{6,}\b", " ", s, flags=re.I)      # leftover ID fragments
    s = re.sub(r"[^A-Za-z0-9&.' ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s if re.search(r"[A-Za-z]{3,}", s) else ""
