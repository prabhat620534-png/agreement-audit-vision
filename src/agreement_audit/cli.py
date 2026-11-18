"""
Local runner: audit every PDF / image in a folder and write a CSV report.

    python -m agreement_audit.cli samples/ --out report.csv
    python -m agreement_audit.cli samples/ --no-vision      # free checks only, no API key needed
"""
import argparse
import csv
import threading
from pathlib import Path

from .batch import run_jobs
from .config import SETTINGS
from .pipeline import audit_document

EXTS = {".pdf", ".jpg", ".jpeg", ".png"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Audit agreements for customer name, stamp and signature.")
    ap.add_argument("folder", type=Path)
    ap.add_argument("--out", type=Path, default=Path("audit_report.csv"))
    ap.add_argument("--no-vision", action="store_true", help="run only the free deterministic checks")
    args = ap.parse_args(argv)

    files = sorted(p for p in args.folder.iterdir() if p.suffix.lower() in EXTS)
    rows, lock = {}, threading.Lock()

    def on_result(key, res):
        with lock:
            rows[key] = res.as_row()

    def on_error(key, msg, attempts):
        with lock:
            rows[key] = [f"Error: {msg}", "", "", ""]

    run_jobs([(p.name, p, 0) for p in files],
             lambda p: audit_document(p.read_bytes(), p.name, use_vision=not args.no_vision),
             on_result, on_error, s=SETTINGS)

    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["File", "Society Name", "Is Stamped", "Is Signed", "Notes"])
        for p in files:
            w.writerow([p.name, *rows.get(p.name, ["", "", "", ""])])
    print(f"Report written to {args.out}")


if __name__ == "__main__":
    main()
