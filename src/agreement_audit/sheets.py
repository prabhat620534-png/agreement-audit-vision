"""
Google Sheets runner - the way the tool was used in production.

Sheet layout (configurable):  B = document link | C = Society Name | D = Is Stamped | E = Is Signed | F = Notes
The run is resumable: finished rows are skipped, errored rows are retried up to `max_attempts` times.
"""
import re
import threading
import time

import gspread

from .batch import run_jobs
from .config import SETTINGS
from .download import fetch
from .pipeline import audit_document

URL_COL, SOCIETY_COL, NOTES_COL, START_ROW = 2, 3, 6, 2
_sheet_lock = threading.Lock()


def _write_row(ws, row, values):
    rng = f"{gspread.utils.rowcol_to_a1(row, SOCIETY_COL)}:{gspread.utils.rowcol_to_a1(row, NOTES_COL)}"
    for attempt in range(5):
        try:
            with _sheet_lock:
                ws.update(range_name=rng, values=[values[:NOTES_COL - SOCIETY_COL + 1]], value_input_option="RAW")
            return
        except gspread.exceptions.APIError as e:
            if "429" in str(e) or "Quota" in str(e):
                time.sleep(20 * (attempt + 1))      # Sheets write quota - wait and retry
            else:
                raise


def _row_plan(url, existing, stamp, sign, redo_all, max_attempts):
    """Returns the attempt count to use for this row, or None to skip it."""
    if not url:
        return None
    if redo_all or existing in ("", "Processing..."):
        return 0
    if not existing.startswith("Error") and (not stamp or not sign):
        return 0                                    # name filled earlier, but stamp/sign never checked
    m = re.match(r"^Error \[(\d+)/", existing)
    if m:
        n = int(m.group(1))
        return n if n < max_attempts else None
    return 0 if existing.startswith("Error:") else None


def run_sheet(ws, creds, test_limit=None, redo_all=False, s=SETTINGS):
    values = ws.get_all_values()
    cell = lambda r, c: (r[c - 1].strip() if len(r) >= c else "")

    headers = ["Society Name", "Is Stamped", "Is Signed", "Notes"]
    first = values[0] if values else []
    if any(not cell(first, SOCIETY_COL + i) for i in range(len(headers))):
        _write_row(ws, 1, [cell(first, SOCIETY_COL + i) or h for i, h in enumerate(headers)])

    jobs = []
    for r_idx in range(START_ROW, len(values) + 1):
        row = values[r_idx - 1]
        attempts = _row_plan(cell(row, URL_COL), cell(row, SOCIETY_COL), cell(row, SOCIETY_COL + 1),
                             cell(row, SOCIETY_COL + 2), redo_all, s.max_attempts)
        if attempts is not None:
            jobs.append((f"Row {r_idx}", (r_idx, cell(row, URL_COL)), attempts))
    if test_limit:
        jobs = jobs[:test_limit]

    def process(payload):
        _, url = payload
        data, fname = fetch(url, creds)
        return audit_document(data, fname, s=s)

    row_of = {k: p[0] for k, p, _ in jobs}
    return run_jobs(
        jobs, process,
        on_result=lambda key, res: _write_row(ws, row_of[key], res.as_row()),
        on_error=lambda key, msg, a: _write_row(ws, row_of[key], [f"Error [{a + 1}/{s.max_attempts}]: {msg}"[:300], "", "", ""]),
        s=s)
